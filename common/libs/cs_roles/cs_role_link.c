/* SPDX-License-Identifier: MIT */
/* Scan / advertise -> connect -> encrypt, with explicit peer or name patterns
 * and optional restart. Role thread, except the Bluetooth callbacks at the end.
 */
#include <errno.h>
#include <string.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>

#include "app_log/app_log.h"
#include "cs_role_internal.h"

APP_LOG_MODULE(cs_roles);

/* Scan 60 ms every 120 ms; connection creation gives up after 10 s. */
#define SCAN_INTERVAL 0x0060
#define SCAN_WINDOW 0x0030
#define CREATE_TIMEOUT 1000

static void report_connection_params(struct bt_conn *conn);
/* Registered in cs_role_link_init(); defined with the other link callbacks below. */
static struct bt_gatt_cb cs_role_gatt_callbacks;

/* 16-bit UUID of the Ranging Service. */
#define RAS_UUID_VAL 0x185B

/* Scanning for a pattern: one match is posted per scan. */
static atomic_t match_posted;

static void set_phase(enum cs_role_link_phase phase) {
	cs_role.link = phase;
	atomic_set(&cs_role_link_phase, phase);
}

static void notify(enum cs_role_state state) {
	cs_role_notify(state, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE, 0U, 0);
}

static void notify_error(enum cs_role_failure_stage failure, uint8_t hci_status, int error) {
	cs_role_notify(CS_ROLE_STATE_ERROR, failure, CS_ROLE_STOP_NONE, hci_status, error);
}

#if defined(CONFIG_BT_OBSERVER)
static int scan_start(void) {
	const struct bt_le_scan_param params = {
		.type = BT_LE_SCAN_TYPE_ACTIVE,
		.interval = SCAN_INTERVAL,
		.window = SCAN_WINDOW,
	};

	return bt_le_scan_start(&params, NULL);
}

static int scan_stop(void) {
	int err = bt_le_scan_stop();

	return err == -EALREADY ? 0 : err;
}
#else
static int scan_start(void) {
	return -ENOTSUP;
}

static int scan_stop(void) {
	return 0;
}
#endif

int cs_role_link_scan(void) {
	int err;

	if (cs_role.link != CS_ROLE_LINK_IDLE) {
		return -EBUSY;
	}
	/* Mirror the phase first: reports can arrive before bt_le_scan_start() returns. */
	set_phase(CS_ROLE_LINK_DISCOVERY);
	err = scan_start();
	if (err) {
		set_phase(CS_ROLE_LINK_IDLE);
		return err;
	}
	notify(CS_ROLE_STATE_SCANNING);
	return 0;
}

#if defined(CONFIG_BT_CENTRAL)
static int connect_to(const bt_addr_le_t *addr) {
	const struct bt_conn_le_create_param create = {
		.interval = SCAN_INTERVAL,
		.window = SCAN_WINDOW,
		.timeout = CREATE_TIMEOUT,
	};
	const struct bt_le_conn_param conn_param = {
		.interval_min = cs_role.params.connection.interval_min,
		.interval_max = cs_role.params.connection.interval_max,
		.latency = cs_role.params.connection.latency,
		.timeout = cs_role.params.connection.timeout,
	};
	struct bt_conn *conn = NULL;
	int err;

	set_phase(CS_ROLE_LINK_CONNECTING);
	err = bt_conn_le_create(addr, &create, &conn_param, &conn);
	if (err) {
		set_phase(CS_ROLE_LINK_IDLE);
		return err;
	}
	cs_role.connecting = conn;
	notify(CS_ROLE_STATE_LINK_CONNECTING);
	return 0;
}
#else
static int connect_to(const bt_addr_le_t *addr) {
	ARG_UNUSED(addr);
	return -ENOTSUP;
}
#endif

#if defined(CONFIG_BT_PERIPHERAL)
static struct bt_le_ext_adv *advertiser;

static int advertise(void) {
	const char *name = bt_get_name();
	const struct bt_data basic[] = {
		BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
		BT_DATA(BT_DATA_NAME_COMPLETE, name, strlen(name)),
	};
	const struct bt_data with_ras[] = {
		BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
		BT_DATA_BYTES(BT_DATA_UUID16_ALL, BT_UUID_16_ENCODE(RAS_UUID_VAL)),
		BT_DATA(BT_DATA_NAME_COMPLETE, name, strlen(name)),
	};
	int err = 0;

	if (!advertiser) {
		/* Extended advertising carries the whole configured name. */
		const struct bt_le_adv_param params = {
			.options = BT_LE_ADV_OPT_EXT_ADV | BT_LE_ADV_OPT_CONN,
			.interval_min = BT_GAP_ADV_FAST_INT_MIN_2,
			.interval_max = BT_GAP_ADV_FAST_INT_MAX_2,
		};

		err = bt_le_ext_adv_create(&params, NULL, &advertiser);
	}
	if (!err) {
		err = cs_role.params.advertise_ras_uuid ?
		              bt_le_ext_adv_set_data(advertiser, with_ras, ARRAY_SIZE(with_ras), NULL, 0) :
		              bt_le_ext_adv_set_data(advertiser, basic, ARRAY_SIZE(basic), NULL, 0);
	}
	if (err) {
		return err;
	}
	set_phase(CS_ROLE_LINK_ADVERTISING);
	err = bt_le_ext_adv_start(advertiser, BT_LE_EXT_ADV_START_DEFAULT);
	if (err) {
		set_phase(CS_ROLE_LINK_IDLE);
		return err;
	}
	notify(CS_ROLE_STATE_ADVERTISING);
	return 0;
}

static int advertise_stop(void) {
	int err = advertiser ? bt_le_ext_adv_stop(advertiser) : 0;

	return err == -EALREADY ? 0 : err;
}
#else
static int advertise(void) {
	return -ENOTSUP;
}

static int advertise_stop(void) {
	return 0;
}
#endif

/* Start from IDLE with the stored parameters. */
static int link_open(void) {
	if (!cs_role.params.central) {
		return advertise();
	}
	if (cs_role.params.peer) {
		return connect_to(&cs_role.peer);
	}
	atomic_clear(&match_posted);
	set_phase(CS_ROLE_LINK_SCANNING);
	int err = scan_start();

	if (err) {
		set_phase(CS_ROLE_LINK_IDLE);
		return err;
	}
	notify(CS_ROLE_STATE_SCANNING);
	return 0;
}

void cs_role_link_schedule_restart(void) {
	if (cs_role.link_requested && cs_role.params.auto_restart) {
		cs_role.restart_pending = true;
		cs_role.restart_at = sys_timepoint_calc(K_MSEC(CONFIG_APP_CS_ROLES_LINK_RESTART_DELAY_MS));
	}
}

int cs_role_link_begin(const struct cs_role_msg *msg) {
	int err;

	if (cs_role.link == CS_ROLE_LINK_DISCOVERY) {
		err = scan_stop();
		if (err) {
			return err;
		}
		set_phase(CS_ROLE_LINK_IDLE);
	}
	if (cs_role.link != CS_ROLE_LINK_IDLE) {
		return -EBUSY;
	}
	cs_role.params = msg->link.params;
	cs_role.peer = msg->link.peer;
	/* The address is copied; keep the pointer only as a flag. */
	cs_role.params.peer = msg->link.params.peer ? &cs_role.peer : NULL;
	cs_role.link_requested = true;
	cs_role.disconnect_requested = false;
	cs_role.link_failed = false;
	cs_role.restart_pending = false;
	err = link_open();
	if (err) {
		cs_role.link_requested = false;
	}
	return err;
}

static void finish_disconnect(int result) {
	if (cs_role.disconnect_done) {
		*cs_role.disconnect_result = result;
		k_sem_give(cs_role.disconnect_done);
		cs_role.disconnect_done = NULL;
	}
	cs_role.disconnect_requested = false;
}

void cs_role_link_disconnect_request(const struct cs_role_msg *msg) {
	int err = 0;

	cs_role.link_requested = false;
	cs_role.restart_pending = false;
	switch (cs_role.link) {
	case CS_ROLE_LINK_DISCOVERY:
	case CS_ROLE_LINK_SCANNING:
		err = scan_stop();
		if (!err) {
			set_phase(CS_ROLE_LINK_IDLE);
			notify(CS_ROLE_STATE_LINK_DISCONNECTED);
		}
		break;
	case CS_ROLE_LINK_ADVERTISING:
		err = advertise_stop();
		if (!err) {
			set_phase(CS_ROLE_LINK_IDLE);
			notify(CS_ROLE_STATE_LINK_DISCONNECTED);
		}
		break;
	case CS_ROLE_LINK_CONNECTING:
	case CS_ROLE_LINK_CONNECTED:
		/* Completed by the connected (cancelled) or disconnected event. */
		err = bt_conn_disconnect(cs_role.link == CS_ROLE_LINK_CONNECTED ? cs_role.conn
		                                                                : cs_role.connecting,
		                         BT_HCI_ERR_REMOTE_USER_TERM_CONN);
		if (err && err != -ENOTCONN) {
			break;
		}
		finish_disconnect(-ECANCELED);
		cs_role.disconnect_requested = true;
		cs_role.disconnect_done = msg->done;
		cs_role.disconnect_result = msg->result;
		cs_role.disconnect_deadline = sys_timepoint_calc(msg->timeout);
		return;
	default:
		break;
	}
	if (msg->done) {
		*msg->result = err;
		k_sem_give(msg->done);
	}
}

void cs_role_link_connected(const struct cs_role_msg *msg) {
	if (msg->status) {
		if (cs_role.link != CS_ROLE_LINK_CONNECTING) {
			return;
		}
		if (cs_role.connecting) {
			bt_conn_unref(cs_role.connecting);
			cs_role.connecting = NULL;
		}
		set_phase(CS_ROLE_LINK_IDLE);
		if (cs_role.disconnect_requested) {
			notify(CS_ROLE_STATE_LINK_DISCONNECTED);
			finish_disconnect(0);
			return;
		}
		notify_error(CS_ROLE_FAILURE_CONNECT, msg->status, -ECONNREFUSED);
		cs_role_link_schedule_restart();
		return;
	}
	if (cs_role.connecting) {
		bt_conn_unref(cs_role.connecting);
		cs_role.connecting = NULL;
	}
	cs_role.conn = bt_conn_ref(msg->conn);
	cs_role.encrypted = false;
	set_phase(CS_ROLE_LINK_CONNECTED);
	if (cs_role.disconnect_requested) {
		(void)bt_conn_disconnect(cs_role.conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
		return;
	}
	notify(CS_ROLE_STATE_LINK_CONNECTED);
	/* Encryption only: CS security needs an encrypted link, no stored bond. */
	int err = bt_conn_set_security(cs_role.conn, BT_SECURITY_L2);

	if (err) {
		notify_error(CS_ROLE_FAILURE_LINK_SECURITY, 0U, err);
		cs_role.link_failed = true;
		(void)bt_conn_disconnect(cs_role.conn, BT_HCI_ERR_AUTH_FAIL);
	}
}

void cs_role_link_security(const struct cs_role_msg *msg) {
	if (msg->conn != cs_role.conn || cs_role.disconnect_requested) {
		return;
	}
	if (msg->err || msg->security_level < BT_SECURITY_L2) {
		/* bt_security_err is not an HCI status. */
		APP_LOG_ERR("Link security failed: %d, level %u", msg->err, msg->security_level);
		cs_role.link_failed = true;
		cs_role_fail(CS_ROLE_FAILURE_LINK_SECURITY, 0U, -EACCES);
		(void)bt_conn_disconnect(cs_role.conn, BT_HCI_ERR_AUTH_FAIL);
		return;
	}
	if (cs_role.encrypted) {
		return;
	}
	cs_role.encrypted = true;
	notify(CS_ROLE_STATE_LINK_ENCRYPTED);
	if (cs_role.stage == CS_ROLE_STAGE_WAIT_ENCRYPTION) {
		cs_role_advance();
	}
}

void cs_role_link_disconnected(const struct cs_role_msg *msg) {
	if (msg->conn != cs_role.conn) {
		return;
	}
	cs_role_link_down();
	bt_conn_unref(cs_role.conn);
	cs_role.conn = NULL;
	cs_role.encrypted = false;
	set_phase(CS_ROLE_LINK_IDLE);
	if (cs_role.disconnect_requested) {
		notify(CS_ROLE_STATE_LINK_DISCONNECTED);
		finish_disconnect(0);
	} else if (cs_role.link_failed) {
		/* An ERROR already reported why. */
		cs_role.link_failed = false;
		cs_role_link_schedule_restart();
	} else {
		cs_role_notify(CS_ROLE_STATE_LINK_LOST, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE,
		               msg->status, -ENOTCONN);
		cs_role_link_schedule_restart();
	}
}

void cs_role_link_scan_match(const struct cs_role_msg *msg) {
	int err;

	if (cs_role.link != CS_ROLE_LINK_SCANNING) {
		return;
	}
	err = scan_stop();
	if (err) {
		APP_LOG_WRN("Scan stop failed: %d", err);
	}
	set_phase(CS_ROLE_LINK_IDLE);
	err = connect_to(&msg->addr);
	if (err) {
		notify_error(CS_ROLE_FAILURE_CONNECT, 0U, err);
		cs_role_link_schedule_restart();
	}
}

k_timepoint_t cs_role_link_next_timer(void) {
	k_timepoint_t next = sys_timepoint_calc(K_FOREVER);

	if (cs_role.restart_pending) {
		next = cs_role.restart_at;
	}
	if (cs_role.disconnect_done && sys_timepoint_cmp(cs_role.disconnect_deadline, next) < 0) {
		next = cs_role.disconnect_deadline;
	}
	return next;
}

void cs_role_link_timers(void) {
	if (cs_role.disconnect_done && sys_timepoint_expired(cs_role.disconnect_deadline)) {
		/* Still disconnecting; the event completes the state later. */
		*cs_role.disconnect_result = -ETIMEDOUT;
		k_sem_give(cs_role.disconnect_done);
		cs_role.disconnect_done = NULL;
	}
	if (cs_role.restart_pending && sys_timepoint_expired(cs_role.restart_at)) {
		cs_role.restart_pending = false;
		if (cs_role.link_requested && cs_role.link == CS_ROLE_LINK_IDLE) {
			int err = link_open();

			if (err) {
				notify_error(CS_ROLE_FAILURE_CONNECT, 0U, err);
				cs_role_link_schedule_restart();
			}
		}
	}
}

/* Bluetooth context. */

#if defined(CONFIG_BT_OBSERVER)
struct match_ctx {
	const struct cs_role_link_params *params;
	struct cs_role_scan_result result;
	bool ras_uuid;
	bool name_match;
};

static bool name_matches(const struct cs_role_link_params *params, const uint8_t *name,
                         uint8_t len) {
	for (size_t i = 0; i < params->pattern_count; i++) {
		size_t plen = strlen(params->patterns[i]);

		if (plen <= len && memcmp(name, params->patterns[i], plen) == 0) {
			return true;
		}
	}
	return false;
}

static bool parse_ad(struct bt_data *data, void *user_data) {
	struct match_ctx *ctx = user_data;

	switch (data->type) {
	case BT_DATA_NAME_COMPLETE:
	case BT_DATA_NAME_SHORTENED:
		if (data->type == BT_DATA_NAME_COMPLETE || !ctx->result.name_complete) {
			ctx->result.name = data->data;
			ctx->result.name_len = data->data_len;
			ctx->result.name_complete = data->type == BT_DATA_NAME_COMPLETE;
		}
		break;
	case BT_DATA_UUID16_ALL:
	case BT_DATA_UUID16_SOME:
		for (uint8_t i = 0; i + 1U < data->data_len; i += 2U) {
			if (sys_get_le16(&data->data[i]) == RAS_UUID_VAL) {
				ctx->ras_uuid = true;
			}
		}
		break;
	default:
		break;
	}
	return true;
}

static void scan_recv(const struct bt_le_scan_recv_info *info, struct net_buf_simple *buf) {
	enum cs_role_link_phase phase = atomic_get(&cs_role_link_phase);
	struct match_ctx ctx = {
		.params = &cs_role.params,
		.result = {
			.address = *info->addr,
			.rssi = info->rssi,
			.connectable = (info->adv_props & BT_GAP_ADV_PROP_CONNECTABLE) != 0U,
		},
	};

	if (phase != CS_ROLE_LINK_DISCOVERY && phase != CS_ROLE_LINK_SCANNING) {
		return;
	}
	bt_data_parse(buf, parse_ad, &ctx);
	if (phase == CS_ROLE_LINK_DISCOVERY) {
		if (cs_role.callbacks->scan_result) {
			cs_role.callbacks->scan_result(&ctx.result);
		}
		return;
	}
	/* The parameters are not changed while scanning for a match. */
	if (!ctx.result.connectable ||
	    !(cs_role.params.pattern_count ?
	              (ctx.result.name && name_matches(&cs_role.params, ctx.result.name,
	                                               ctx.result.name_len)) :
	              ctx.ras_uuid)) {
		return;
	}
	if (atomic_cas(&match_posted, 0, 1)) {
		struct cs_role_msg msg = { .type = CS_ROLE_MSG_SCAN_MATCH, .addr = *info->addr };

		cs_role_post(&msg);
	}
}

static struct bt_le_scan_cb scan_callbacks = {
	.recv = scan_recv,
};

int cs_role_link_init(void) {
	bt_gatt_cb_register(&cs_role_gatt_callbacks);
	return bt_le_scan_cb_register(&scan_callbacks);
}
#else
int cs_role_link_init(void) {
	bt_gatt_cb_register(&cs_role_gatt_callbacks);
	return 0;
}
#endif

static void connected(struct bt_conn *conn, uint8_t err) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_CONNECTED, .status = err };

	if (err) {
		/* Only a connection this library created can fail here. */
		if (atomic_get(&cs_role_link_phase) != CS_ROLE_LINK_CONNECTING) {
			return;
		}
	} else if (!atomic_ptr_cas(&cs_role_conn_ptr, NULL, conn)) {
		APP_LOG_WRN("Second connection ignored");
		return;
	}
	if (!err) {
		report_connection_params(conn);
	}
	msg.conn = bt_conn_ref(conn);
	cs_role_post(&msg);
}

static void disconnected(struct bt_conn *conn, uint8_t reason) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_DISCONNECTED, .status = reason };

	if (!atomic_ptr_cas(&cs_role_conn_ptr, conn, NULL)) {
		return;
	}
	/* The data path belongs to this context: reset it before any new link. */
	atomic_clear(&cs_role_data.layouts);
	cs_role_data.counter = (struct cs_subevent_counter){ 0 };
	IF_ENABLED(CONFIG_APP_CS_ROLES_INITIATOR, (cs_role_initiator_data_reset();));
	msg.conn = bt_conn_ref(conn);
	cs_role_post(&msg);
}

static void security_changed(struct bt_conn *conn, bt_security_t level, enum bt_security_err err) {
	struct cs_role_msg msg = {
		.type = CS_ROLE_MSG_SECURITY_CHANGED,
		.err = (int)err,
		.security_level = (uint8_t)level,
	};

	if (!cs_role_is_ours(conn)) {
		return;
	}
	msg.conn = bt_conn_ref(conn);
	cs_role_post(&msg);
}

static void report_connection_params(struct bt_conn *conn) {
	struct bt_conn_info info;
	struct cs_config_connection params;

	if (!cs_role_is_ours(conn) || !cs_role.callbacks || !cs_role.callbacks->connection_params ||
	    bt_conn_get_info(conn, &info) || info.type != BT_CONN_TYPE_LE) {
		return;
	}
	params = (struct cs_config_connection){
		.interval_min = (uint16_t)(info.le.interval_us / 1250U),
		.interval_max = (uint16_t)(info.le.interval_us / 1250U),
		.latency = info.le.latency,
		.timeout = info.le.timeout,
	};
	cs_role.callbacks->connection_params(&params, bt_gatt_get_mtu(conn));
}

static void le_param_updated(struct bt_conn *conn, uint16_t interval, uint16_t latency,
				     uint16_t timeout) {
	struct cs_config_connection params = {
		.interval_min = interval,
		.interval_max = interval,
		.latency = latency,
		.timeout = timeout,
	};

	if (!cs_role_is_ours(conn) || !cs_role.callbacks || !cs_role.callbacks->connection_params) {
		return;
	}
	cs_role.callbacks->connection_params(&params, bt_gatt_get_mtu(conn));
}

static void att_mtu_updated(struct bt_conn *conn, uint16_t tx, uint16_t rx) {
	ARG_UNUSED(tx);
	ARG_UNUSED(rx);
	report_connection_params(conn);
}

static struct bt_gatt_cb cs_role_gatt_callbacks = {
	.att_mtu_updated = att_mtu_updated,
};

BT_CONN_CB_DEFINE(cs_role_link_callbacks) = {
	.connected = connected,
	.disconnected = disconnected,
	.security_changed = security_changed,
	.le_param_updated = le_param_updated,
};
