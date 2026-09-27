/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <string.h>
#include <cs_utils/cs_capabilities.h>
#include <cs_utils/cs_config.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/byteorder.h>

#include "cdc_out.h"
#include "cs_events.h"
#include "record_queue.h"
#include "report_printer.h"
#include "test_cfg.h"

LOG_MODULE_REGISTER(main, LOG_LEVEL_INF);

BUILD_ASSERT(CONFIG_BT_MAX_CONN == 1, "This test supports one connection");

/* Ranging Service UUID; bluetooth/services/ras.h needs CONFIG_BT_RAS. */
#define RANGING_SERVICE_UUID_VAL 0x185B

enum test_event_type {
	TEST_PEER_FOUND,
	TEST_CONNECTED,
	TEST_CONNECT_FAILED,
	TEST_SECURITY_CHANGED,
	TEST_CS_STAGE,
	TEST_DISCONNECTED,
	TEST_RECYCLED,
};

struct test_event {
	enum test_event_type type;
	/** TEST_CS_STAGE only. */
	enum cs_events_stage stage;
	/** HCI or security status; 0 on success. */
	uint8_t status;
	/** TEST_PEER_FOUND only. */
	bt_addr_le_t addr;
};

/* Setup steps complete one at a time, and at most one peer report is posted
 * per scan, so a few slots cover a disconnect racing the pending step.
 */
K_MSGQ_DEFINE(events, sizeof(struct test_event), 8, sizeof(void *));

/* Set when a peer is reported; cleared when scanning restarts. */
static atomic_t peer_reported;

static void post(const struct test_event *event) {
	int err = k_msgq_put(&events, event, K_NO_WAIT);

	__ASSERT_NO_MSG(err == 0);
	ARG_UNUSED(err);
}

static void queue_current_connection_params(struct bt_conn *conn) {
	struct bt_conn_info info;

	if (bt_conn_get_info(conn, &info) == 0 && info.type == BT_CONN_TYPE_LE) {
		const uint16_t interval = (uint16_t)(info.le.interval_us / 1250U);

		(void)record_queue_put(RECORD_CONNECTION_PARAMETERS,
		                       &(struct cs_config_connection){
			                       .interval_min = interval,
			                       .interval_max = interval,
			                       .latency = info.le.latency,
			                       .timeout = info.le.timeout,
		                       },
		                       sizeof(struct cs_config_connection));
	}
}

struct adv_match {
	bool ranging_service;
	bool name;
};

static bool adv_data_cb(struct bt_data *data, void *user_data) {
	struct adv_match *match = user_data;
	const char *name = test_cfg_peer_name();

	switch (data->type) {
	case BT_DATA_UUID16_SOME:
	case BT_DATA_UUID16_ALL:
		for (size_t i = 0; i + sizeof(uint16_t) <= data->data_len; i += sizeof(uint16_t)) {
			if (sys_get_le16(&data->data[i]) == RANGING_SERVICE_UUID_VAL) {
				match->ranging_service = true;
			}
		}
		break;
	case BT_DATA_NAME_SHORTENED:
	case BT_DATA_NAME_COMPLETE:
		match->name = data->data_len == strlen(name) &&
		              memcmp(data->data, name, data->data_len) == 0;
		break;
	default:
		break;
	}
	return true;
}

static void device_found_cb(const bt_addr_le_t *addr, int8_t rssi, uint8_t adv_type,
                            struct net_buf_simple *ad) {
	struct adv_match match = {.name = test_cfg_peer_name()[0] == '\0'};

	if (adv_type != BT_GAP_ADV_TYPE_ADV_IND && adv_type != BT_GAP_ADV_TYPE_ADV_DIRECT_IND) {
		return;
	}
	bt_data_parse(ad, adv_data_cb, &match);
	if (!match.ranging_service || !match.name || atomic_set(&peer_reported, 1)) {
		return;
	}

	struct test_event event = {.type = TEST_PEER_FOUND};

	bt_addr_le_copy(&event.addr, addr);
	LOG_INF("Peer found (RSSI %d dBm)", rssi);
	post(&event);
}

static void connected_cb(struct bt_conn *conn, uint8_t err) {
	/* main already owns the reference returned by bt_conn_le_create(). */
	if (err) {
		LOG_ERR("Connection failed (HCI status 0x%02x)", err);
	} else {
		queue_current_connection_params(conn);
	}
	post(&(struct test_event){
		.type = err ? TEST_CONNECT_FAILED : TEST_CONNECTED,
		.status = err,
	});
}

static void disconnected_cb(struct bt_conn *conn, uint8_t reason) {
	ARG_UNUSED(conn);
	LOG_INF("Disconnected (reason 0x%02x)", reason);
	/* Clear the cached session record so a later USB attach cannot receive
	 * parameters from a previous Bluetooth link. */
	(void)record_queue_put(RECORD_CONNECTION_PARAMETERS, &(struct cs_config_connection){0},
	                       sizeof(struct cs_config_connection));
	post(&(struct test_event){.type = TEST_DISCONNECTED, .status = reason});
}

static void recycled_cb(void) {
	post(&(struct test_event){.type = TEST_RECYCLED});
}

static void security_changed_cb(struct bt_conn *conn, bt_security_t level,
                                enum bt_security_err err) {
	ARG_UNUSED(conn);
	if (err) {
		LOG_ERR("Security failed: level %u, err %d", level, err);
	} else {
		LOG_INF("Security level %u", level);
	}
	post(&(struct test_event){.type = TEST_SECURITY_CHANGED, .status = (uint8_t)err});
}

static void le_param_updated_cb(struct bt_conn *conn, uint16_t interval, uint16_t latency,
                                uint16_t timeout) {
	ARG_UNUSED(conn);
	LOG_INF("ACL parameters: interval %u us, latency %u, timeout %u ms",
	        interval * 1250U, latency, timeout * 10U);
	(void)record_queue_put(RECORD_CONNECTION_PARAMETERS,
	                       &(struct cs_config_connection){
		                       .interval_min = interval,
		                       .interval_max = interval,
		                       .latency = latency,
		                       .timeout = timeout,
	                       },
	                       sizeof(struct cs_config_connection));
}

BT_CONN_CB_DEFINE(conn_callbacks) = {
	.connected = connected_cb,
	.disconnected = disconnected_cb,
	.recycled = recycled_cb,
	.security_changed = security_changed_cb,
	.le_param_updated = le_param_updated_cb,
};

static void cs_stage_cb(enum cs_events_stage stage, uint8_t status) {
	post(&(struct test_event){.type = TEST_CS_STAGE, .stage = stage, .status = status});
}

static int start_scanning(void) {
	int err;

	atomic_clear(&peer_reported);
	err = bt_le_scan_start(BT_LE_SCAN_PASSIVE, device_found_cb);
	if (err == -EALREADY) {
		return 0;
	}
	if (err) {
		LOG_ERR("TEST FAIL scanning (err %d)", err);
	} else if (test_cfg_peer_name()[0] != '\0') {
		LOG_INF("Scanning for Ranging Service advertiser \"%s\"", test_cfg_peer_name());
	} else {
		LOG_INF("Scanning for any Ranging Service advertiser");
	}
	return err;
}

static int connect_peer(const struct cs_initiator_config *config, const bt_addr_le_t *addr,
                        struct bt_conn **conn) {
	const struct bt_le_conn_param param = {
		.interval_min = config->connection.interval_min,
		.interval_max = config->connection.interval_max,
		.latency = config->connection.latency,
		.timeout = config->connection.timeout,
	};
	int err = bt_le_scan_stop();

	if (err && err != -EALREADY) {
		LOG_ERR("Scan stop failed (err %d)", err);
		return err;
	}
	err = bt_conn_le_create(addr, BT_CONN_LE_CREATE_CONN, &param, conn);
	if (err) {
		LOG_ERR("Connection request failed (err %d)", err);
	}
	return err;
}

/* Starts the next setup step after @p stage succeeded.
 * The sequence is: pairing, remote capabilities, FAE table, configuration
 * creation, CS security, procedure parameters and enable.
 */
static int advance(const struct cs_initiator_config *config, struct bt_conn *conn,
                   enum cs_events_stage stage) {
	int err;

	switch (stage) {
	case CS_STAGE_REMOTE_CAPABILITIES:
		err = bt_le_cs_read_remote_fae_table(conn);
		if (err == 0) {
			return 0;
		}
		/* The table only refines results; continue without it. */
		LOG_WRN("FAE table request failed (err %d)", err);
		__fallthrough;
	case CS_STAGE_FAE_TABLE:
		err = cs_initiator_config_apply_creation(config, conn);
		if (err) {
			LOG_ERR("TEST FAIL CS configuration create (err %d)", err);
		}
		return err;
	case CS_STAGE_CONFIG_CREATED:
		err = bt_le_cs_security_enable(conn);
		if (err) {
			LOG_ERR("TEST FAIL CS security enable (err %d)", err);
		}
		return err;
	case CS_STAGE_SECURITY_ENABLED: {
		const struct bt_le_cs_procedure_enable_param enable = {
			.config_id = config->config_id,
			.enable = BT_CONN_LE_CS_PROCEDURES_ENABLED,
		};

		err = cs_initiator_config_apply_procedure(config, conn);
		if (err) {
			LOG_ERR("TEST FAIL CS procedure parameters (err %d)", err);
			return err;
		}
		err = bt_le_cs_procedure_enable(conn, &enable);
		if (err) {
			LOG_ERR("TEST FAIL CS procedure enable (err %d)", err);
		}
		return err;
	}
	case CS_STAGE_PROCEDURE_ENABLED:
		return 0;
	}
	return -EINVAL;
}

/* Local settings first, then the exchange that feeds the shared configuration. */
static int start_cs(const struct cs_initiator_config *config, struct bt_conn *conn) {
	int err = cs_initiator_config_apply_default_settings(config, conn);

	if (err) {
		LOG_ERR("TEST FAIL CS default settings (err %d)", err);
		return err;
	}
	err = bt_le_cs_read_remote_supported_capabilities(conn);
	if (err) {
		LOG_ERR("TEST FAIL CS capability exchange (err %d)", err);
	}
	return err;
}

/* Handles one step outcome; returns non-zero if the connection must end. */
static int handle_stage(const struct cs_initiator_config *config, struct bt_conn *conn,
                        enum cs_events_stage stage, uint8_t status) {
	static const char *const names[] = {
		[CS_STAGE_REMOTE_CAPABILITIES] = "CS capability exchange",
		[CS_STAGE_FAE_TABLE] = "CS FAE table",
		[CS_STAGE_CONFIG_CREATED] = "CS configuration create",
		[CS_STAGE_SECURITY_ENABLED] = "CS security enable",
		[CS_STAGE_PROCEDURE_ENABLED] = "CS procedure enable",
	};

	/* A missing FAE table is not fatal; the reflector may not have one. */
	if (status && stage != CS_STAGE_FAE_TABLE) {
		LOG_ERR("TEST FAIL %s (HCI status 0x%02x)", names[stage], status);
		return -EIO;
	}
	return advance(config, conn, stage);
}

static void log_stats(void) {
	struct cs_events_stats cs;
	struct record_queue_stats queue;
	struct report_printer_stats printer;
	struct cdc_out_stats cdc;

	cs_events_stats_get(&cs);
	record_queue_stats_get(&queue);
	report_printer_stats_get(&printer);
	cdc_out_stats_get(&cdc);

	LOG_INF("CS: subevents %u, procedures %u complete / %u aborted, truncated %u, "
	        "parse errors %u",
	        cs.subevents, cs.procedures_complete, cs.procedures_aborted, cs.truncated,
	        cs.parse_errors);
	LOG_INF("Reports: queued %u, dropped %u, high water %u/%u, printed %u, "
	        "discarded %u, format errors %u",
	        queue.queued, queue.dropped, queue.high_water, queue.capacity, printer.printed,
	        printer.discarded, printer.format_errors);
	LOG_INF("USB CDC: host %s, %llu bytes, aborted writes %u",
	        cdc_out_host_ready() ? "attached" : "detached", (unsigned long long)cdc.bytes,
	        cdc.aborted_writes);
}

/* Logs the verdict once, when the expected number of procedures has ended. */
static void check_verdict(void) {
	static bool reported;
	const unsigned int expected = test_cfg_expected_procedures();
	struct cs_events_stats cs;

	if (reported || expected == 0U) {
		return;
	}
	cs_events_stats_get(&cs);
	if (cs.procedures_complete + cs.procedures_aborted < expected) {
		return;
	}
	reported = true;
	if (cs.procedures_aborted == 0U) {
		LOG_INF("TEST PASS: %u procedures complete", cs.procedures_complete);
	} else {
		LOG_ERR("TEST FAIL procedures: %u complete, %u aborted", cs.procedures_complete,
		        cs.procedures_aborted);
	}
}

static void disconnect(struct bt_conn *conn) {
	/* Recover through the normal disconnect/recycle path. */
	int err = bt_conn_disconnect(conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);

	if (err) {
		LOG_ERR("Disconnect request failed (err %d)", err);
	}
}

int main(void) {
	struct cs_initiator_config config;
	struct cs_capabilities local;
	struct bt_conn *conn = NULL;
	int err;

	LOG_INF("CS initiator test");

	err = test_cfg_get(&config);
	if (err) {
		LOG_ERR("TEST FAIL configuration rejected (err %d)", err);
		return 0;
	}
	(void)record_queue_put(RECORD_INITIATOR_CONFIG, &config, config.size);

	cs_events_register(cs_stage_cb);

	err = bt_enable(NULL);
	if (err) {
		LOG_ERR("TEST FAIL Bluetooth init (err %d)", err);
		return 0;
	}
	if (IS_ENABLED(CONFIG_BT_SETTINGS)) {
		err = settings_load();
		if (err) {
			LOG_ERR("TEST FAIL settings load (err %d)", err);
			return 0;
		}
	}

	err = cs_capabilities_read_local(&local);
	if (err) {
		LOG_ERR("TEST FAIL local CS capabilities (err %d)", err);
		return 0;
	}
	(void)record_queue_put(RECORD_LOCAL_CAPABILITIES, &local, local.size);

	if (start_scanning()) {
		return 0;
	}

	for (;;) {
		struct test_event event;

		if (k_msgq_get(&events, &event, K_MSEC(CONFIG_CS_INITIATOR_TEST_STATS_INTERVAL_MS))) {
			log_stats();
			check_verdict();
			continue;
		}

		switch (event.type) {
		case TEST_PEER_FOUND:
			if (conn) {
				break;
			}
			if (connect_peer(&config, &event.addr, &conn)) {
				conn = NULL;
				if (start_scanning()) {
					return 0;
				}
			}
			break;
		case TEST_CONNECTED:
			if (!conn) {
				break;
			}
			LOG_INF("Connected; pairing");
			err = bt_conn_set_security(conn, BT_SECURITY_L2);
			if (err) {
				LOG_ERR("TEST FAIL pairing request (err %d)", err);
				disconnect(conn);
			}
			break;
		case TEST_SECURITY_CHANGED:
			if (!conn) {
				break;
			}
			if (event.status) {
				LOG_ERR("TEST FAIL pairing (err %u)", event.status);
				disconnect(conn);
			} else if (start_cs(&config, conn)) {
				disconnect(conn);
			}
			break;
		case TEST_CS_STAGE:
			if (conn && handle_stage(&config, conn, event.stage, event.status)) {
				disconnect(conn);
			}
			break;
		case TEST_CONNECT_FAILED:
		case TEST_DISCONNECTED:
			if (conn) {
				bt_conn_unref(conn);
				conn = NULL;
			}
			break;
		case TEST_RECYCLED:
			/* Wait for a free connection object before scanning again. */
			if (start_scanning()) {
				return 0;
			}
			break;
		}
	}
}
