/* SPDX-License-Identifier: MIT */
/* Role thread: requests, stage deadlines, procedure enable/disable, STOP and
 * interruption, and the CS callbacks shared by both roles.
 */
#include <errno.h>
#include <string.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/kernel.h>

#include "app_log/app_log.h"
#include "cs_role_internal.h"

APP_LOG_MODULE(cs_roles);

struct cs_role_ctx cs_role;
struct cs_role_data cs_role_data;
atomic_ptr_t cs_role_conn_ptr;
atomic_t cs_role_link_phase;

K_MSGQ_DEFINE(role_msgs,
              sizeof(struct cs_role_msg),
              CONFIG_APP_CS_ROLES_MSG_QUEUE_DEPTH,
              4);
K_THREAD_STACK_DEFINE(role_stack,
                      CONFIG_APP_CS_ROLES_THREAD_STACK_SIZE);
static struct k_thread role_thread;
static atomic_t initialized;
static atomic_t running;

bool cs_role_is_role_thread(void) {
	return k_current_get() == &role_thread;
}

bool cs_role_is_ours(const struct bt_conn *conn) {
	return conn != NULL && atomic_ptr_get(&cs_role_conn_ptr) == conn;
}

void cs_role_post(const struct cs_role_msg *msg) {
	/* Bluetooth context: never wait. The queue holds requests and single
	 * completions of commands the role thread issued, so it does not fill.
	 */
	if (k_msgq_put(&role_msgs, msg, K_NO_WAIT) != 0) {
		APP_LOG_WRN("Role message %u dropped: queue full", msg->type);
		if (msg->conn) {
			bt_conn_unref(msg->conn);
		}
	}
}

static void reply(const struct cs_role_msg *msg,
                  int result) {
	if (msg->done) {
		*msg->result = result;
		k_sem_give(msg->done);
	}
}

/* Post a request; wait for its result unless called from the event thread,
 * whose callbacks must not wait for the role thread (it may be waiting to
 * deliver an event).
 */
static int request(struct cs_role_msg *msg) {
	struct k_sem done;
	int result = 0;
	bool wait = !cs_role_is_event_thread();

	if (!atomic_get(&initialized)) {
		return -EINVAL;
	}
	if (wait) {
		k_sem_init(&done, 0, 1);
		msg->done = &done;
		msg->result = &result;
	}
	if (k_msgq_put(&role_msgs, msg, wait ? K_FOREVER : K_NO_WAIT) != 0) {
		return -EAGAIN;
	}
	if (wait) {
		/* Every request is answered: at once, or when its deadline passes. */
		(void)k_sem_take(&done, K_FOREVER);
	}
	return result;
}

void cs_role_set_stage(enum cs_role_stage stage,
                       bool deadline) {
	cs_role.stage = stage;
	cs_role.deadline_set = deadline;
	if (deadline) {
		k_timeout_t timeout = K_MSEC(CONFIG_APP_CS_ROLES_SETUP_TIMEOUT_MS);

		if (stage == CS_ROLE_STAGE_STOPPING) {
			timeout = K_MSEC(CONFIG_APP_CS_ROLES_STOP_TIMEOUT_MS);
		}
#if defined(CONFIG_APP_CS_ROLES_INITIATOR)
		if (stage == CS_ROLE_STAGE_STOP_RAS) {
			timeout = K_MSEC(CONFIG_APP_CS_ROLES_STOP_RAS_TIMEOUT_MS);
		}
#endif
		cs_role.deadline = sys_timepoint_calc(timeout);
	}
}

static bool setup_in_progress(void) {
	return cs_role.stage != CS_ROLE_STAGE_IDLE && cs_role.stage != CS_ROLE_STAGE_RUNNING &&
	       cs_role.stage != CS_ROLE_STAGE_STOPPING && cs_role.stage != CS_ROLE_STAGE_STOP_RAS;
}

static void release_role(enum cs_role_kind kind,
                         bool link_down) {
	if (kind == CS_ROLE_KIND_INITIATOR) {
		IF_ENABLED(CONFIG_APP_CS_ROLES_INITIATOR, (cs_role_initiator_release(link_down)));
	} else if (kind == CS_ROLE_KIND_REFLECTOR) {
		IF_ENABLED(CONFIG_APP_CS_ROLES_REFLECTOR, (cs_role_reflector_release(link_down)));
	}
}

static void clear_progress(void) {
	cs_role.capabilities_read = false;
	cs_role.fae_read = false;
	cs_role.config_created = false;
	cs_role.security_enabled = false;
}

void cs_role_fail(enum cs_role_failure_stage failure,
                  uint8_t hci_status,
                  int error) {
	bool in_setup = setup_in_progress();

	atomic_clear(&running);
	cs_role_set_stage(CS_ROLE_STAGE_IDLE, false);
	cs_role_notify(CS_ROLE_STATE_ERROR, failure, CS_ROLE_STOP_NONE, hci_status, error ? error : -EIO);
	if (in_setup) {
		/* The link stays; the next START repeats the setup from the start. */
		release_role(cs_role.role, false);
		clear_progress();
		/* A peer without IPT or the antennas asked for fails again on every
		 * new link: no restart.
		 */
		if (cs_role.params.auto_restart && cs_role.conn && failure != CS_ROLE_FAILURE_PEER_IPT &&
		    failure != CS_ROLE_FAILURE_PEER_ANTENNA) {
			cs_role.link_failed = true;
			(void)bt_conn_disconnect(cs_role.conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
		}
	}
}

void cs_role_advance(void) {
	if (cs_role.role == CS_ROLE_KIND_INITIATOR) {
		IF_ENABLED(CONFIG_APP_CS_ROLES_INITIATOR, (cs_role_initiator_advance()));
	} else if (cs_role.role == CS_ROLE_KIND_REFLECTOR) {
		IF_ENABLED(CONFIG_APP_CS_ROLES_REFLECTOR, (cs_role_reflector_advance()));
	}
}

static uint8_t current_config_id(void) {
	return cs_role.role == CS_ROLE_KIND_INITIATOR ? cs_role.initiator.config_id : cs_role.reflector.config_id;
}

static int procedures_disable(uint8_t config_id) {
	const struct bt_le_cs_procedure_enable_param param = {
		.config_id = config_id,
		.enable = BT_CONN_LE_CS_PROCEDURES_DISABLED,
	};

	return bt_le_cs_procedure_enable(cs_role.conn, &param);
}

/* Procedures have ended; report and release a STOP waiter. */
static void finish_stop(int outcome) {
	enum cs_role_stop_reason reason = cs_role.stop_reason;

	atomic_clear(&running);
	atomic_clear(&cs_role_data.ras_waiter);
	cs_role_set_stage(CS_ROLE_STAGE_IDLE, false);
	if (reason == CS_ROLE_STOP_COMPLETE) {
		cs_role_event_procedures_complete(
				(uint16_t)MIN(atomic_get(&cs_role_data.procedures_completed), UINT16_MAX));
	}
	cs_role_notify(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, reason, 0U, cs_role.stop_error);
	cs_role.stop_requested = false;
	cs_role.stop_error = 0;
	if (cs_role.stop_done) {
		*cs_role.stop_result = outcome;
		k_sem_give(cs_role.stop_done);
		cs_role.stop_done = NULL;
	}
}

/* The disable event arrived (or the controller/peer ended the procedures). */
static void procedures_disabled(void) {
	if (cs_role.role == CS_ROLE_KIND_INITIATOR) {
		IF_ENABLED(CONFIG_APP_CS_ROLES_INITIATOR, (cs_role_initiator_disabled(); return;));
	}
	finish_stop(0);
}

void cs_role_stop_finish(int outcome) {
	finish_stop(outcome);
}

static void handle_stop_request(struct cs_role_msg *msg,
                                enum cs_role_stop_reason reason,
                                int error) {
	int err;

	if (!cs_role.conn) {
		reply(msg, 0);
		return;
	}
	if (setup_in_progress()) {
		if (reason != CS_ROLE_STOP_HOST) {
			/* An interruption concerns running procedures only. */
			reply(msg, 0);
			return;
		}
		/* Late completions are ignored in IDLE; procedures enabled meanwhile
		 * are disabled when their event arrives.
		 */
		cs_role.stop_reason = CS_ROLE_STOP_HOST;
		cs_role.stop_error = -ECANCELED;
		finish_stop(0);
		reply(msg, 0);
		return;
	}
	if (cs_role.stage != CS_ROLE_STAGE_RUNNING) {
		/* Idle, or a stop is already in progress: nothing more to do. */
		reply(msg, 0);
		return;
	}
	err = procedures_disable(current_config_id());
	if (err) {
		reply(msg, err);
		return;
	}
	cs_role.stop_requested = true;
	cs_role.stop_reason = reason;
	cs_role.stop_error = error;
	cs_role.stop_done = msg->done;
	cs_role.stop_result = msg->result;
	cs_role_set_stage(CS_ROLE_STAGE_STOPPING, true);
}

static void handle_procedure(const struct cs_role_msg *msg) {
	bool enabled = msg->cs.state == BT_CONN_LE_CS_PROCEDURES_ENABLED;

	if (msg->status) {
		if (cs_role.stage == CS_ROLE_STAGE_STOPPING) {
			if (cs_role.stop_done) {
				*cs_role.stop_result = -EIO;
				k_sem_give(cs_role.stop_done);
				cs_role.stop_done = NULL;
			}
			cs_role.stop_requested = false;
		}
		if (cs_role.stage != CS_ROLE_STAGE_IDLE) {
			cs_role_fail(CS_ROLE_FAILURE_PROCEDURE, msg->status, -EIO);
		}
		return;
	}
	if (enabled) {
		if (cs_role.stage == CS_ROLE_STAGE_ENABLE ||
		    (cs_role.role == CS_ROLE_KIND_REFLECTOR && cs_role.stage == CS_ROLE_STAGE_WAIT_PEER_CONFIG)) {
			atomic_set(&running, 1);
			atomic_clear(&cs_role_data.procedures_completed);
			cs_role_set_stage(CS_ROLE_STAGE_RUNNING, false);
			cs_role_notify(CS_ROLE_STATE_RUNNING, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE, 0U, 0);
		} else if (cs_role.stage != CS_ROLE_STAGE_RUNNING) {
			/* Enabled after a STOP, or by a peer while no role is started. */
			APP_LOG_WRN("Procedures enabled while not started; disabling");
			(void)procedures_disable(msg->cs.config_id);
		}
		return;
	}
	if (cs_role.stage == CS_ROLE_STAGE_STOPPING) {
		procedures_disabled();
	} else if (cs_role.stage == CS_ROLE_STAGE_RUNNING) {
		/* Not requested here: the initiator's controller completed the
		 * procedure count, or the initiator disabled a reflector.
		 */
		cs_role.stop_reason = cs_role.role == CS_ROLE_KIND_INITIATOR ? CS_ROLE_STOP_COMPLETE
		                                                             : CS_ROLE_STOP_PEER;
		cs_role.stop_error = 0;
		cs_role_set_stage(CS_ROLE_STAGE_STOPPING, true);
		procedures_disabled();
		if (cs_role.role == CS_ROLE_KIND_REFLECTOR) {
			/* The reflector stays started: wait for the initiator's next run. */
			cs_role_set_stage(CS_ROLE_STAGE_ENABLE, false);
			cs_role_notify(CS_ROLE_STATE_RAS_READY, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE, 0U, 0);
		}
	}
}

static void handle_timeout(void) {
	enum cs_role_failure_stage failure = CS_ROLE_FAILURE_NONE;

	cs_role.deadline_set = false;
	switch (cs_role.stage) {
	case CS_ROLE_STAGE_WAIT_ENCRYPTION:
		failure = CS_ROLE_FAILURE_LINK_SECURITY;
		break;
	case CS_ROLE_STAGE_RAS_DISCOVERY:
	case CS_ROLE_STAGE_RAS_FEATURES:
		failure = CS_ROLE_FAILURE_RAS_DISCOVERY;
		break;
	case CS_ROLE_STAGE_REMOTE_CAPABILITIES:
	case CS_ROLE_STAGE_FAE:
		failure = CS_ROLE_FAILURE_CAPABILITIES;
		break;
	case CS_ROLE_STAGE_CONFIG:
		failure = CS_ROLE_FAILURE_CONFIG;
		break;
	case CS_ROLE_STAGE_SECURITY:
		failure = CS_ROLE_FAILURE_SECURITY;
		break;
	case CS_ROLE_STAGE_ENABLE:
		failure = CS_ROLE_FAILURE_PROCEDURE;
		break;
	case CS_ROLE_STAGE_STOPPING:
		/* The controller never confirmed the disable. */
		if (cs_role.stop_done) {
			*cs_role.stop_result = -ETIME;
			k_sem_give(cs_role.stop_done);
			cs_role.stop_done = NULL;
		}
		cs_role.stop_requested = false;
		cs_role.stop_error = 0;
		atomic_clear(&running);
		cs_role_set_stage(CS_ROLE_STAGE_IDLE, false);
		cs_role_notify(CS_ROLE_STATE_ERROR, CS_ROLE_FAILURE_PROCEDURE, CS_ROLE_STOP_NONE, 0U, -ETIMEDOUT);
		return;
	case CS_ROLE_STAGE_STOP_RAS:
		IF_ENABLED(CONFIG_APP_CS_ROLES_INITIATOR, (cs_role_initiator_stop_ras_timeout()));
		return;
	default:
		return;
	}
	APP_LOG_WRN("Setup stage %u timed out", cs_role.stage);
	cs_role_fail(failure, 0U, -ETIMEDOUT);
}

static int start_role(const struct cs_role_msg *msg,
                      enum cs_role_kind kind) {
	if (!cs_role.conn) {
		return -ENOTCONN;
	}
	if (cs_role.stage != CS_ROLE_STAGE_IDLE) {
		return -EBUSY;
	}
	if (cs_role.role != kind) {
		/* Role change on the same link: free the other role's RAS resource. */
		release_role(cs_role.role, false);
		clear_progress();
	} else if (kind == CS_ROLE_KIND_INITIATOR &&
	           msg->initiator.peer_data != CS_CONFIG_PEER_DATA_RAS_REALTIME) {
		/* No reflector data wanted: drop a RAS subscription of an earlier run. */
		release_role(kind, false);
	}
	cs_role.role = kind;
	atomic_set(&cs_role_data.role, kind);
	if (kind == CS_ROLE_KIND_INITIATOR) {
		cs_role.initiator = msg->initiator;
		atomic_set(&cs_role_data.ras, cs_role.initiator.peer_data == CS_CONFIG_PEER_DATA_RAS_REALTIME);
	} else {
		cs_role.reflector = msg->reflector;
	}
	cs_role.stop_requested = false;
	cs_role.stop_error = 0;
	cs_role_advance();
	return 0;
}

/* Link is down: wake waiters, report a running role, drop per-link progress. */
void cs_role_link_down(void) {
	if (cs_role.stage == CS_ROLE_STAGE_RUNNING || cs_role.stage == CS_ROLE_STAGE_STOPPING ||
	    cs_role.stage == CS_ROLE_STAGE_STOP_RAS) {
		atomic_clear(&running);
		cs_role_notify(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_LINK_LOST, 0U, -ENOTCONN);
	}
	if (cs_role.stop_done) {
		*cs_role.stop_result = -ENOTCONN;
		k_sem_give(cs_role.stop_done);
		cs_role.stop_done = NULL;
	}
	cs_role.stop_requested = false;
	cs_role.stop_error = 0;
	atomic_clear(&cs_role_data.ras_waiter);
	cs_role_set_stage(CS_ROLE_STAGE_IDLE, false);
	release_role(CS_ROLE_KIND_INITIATOR, true);
	release_role(CS_ROLE_KIND_REFLECTOR, true);
	clear_progress();
	cs_role.peer_config = false;
}

static void handle(struct cs_role_msg *msg) {
	switch (msg->type) {
	case CS_ROLE_MSG_SCAN_START:
		reply(msg, cs_role_link_scan());
		break;
	case CS_ROLE_MSG_LINK_START:
		reply(msg, cs_role_link_begin(msg));
		break;
	case CS_ROLE_MSG_LINK_DISCONNECT:
		if (cs_role.stage != CS_ROLE_STAGE_IDLE) {
			cs_role.stop_reason = CS_ROLE_STOP_HOST;
			cs_role.stop_error = -ECANCELED;
			if (cs_role.stage == CS_ROLE_STAGE_RUNNING || !setup_in_progress()) {
				finish_stop(0);
			} else {
				cs_role_set_stage(CS_ROLE_STAGE_IDLE, false);
			}
		}
		cs_role_link_disconnect_request(msg);
		break;
	case CS_ROLE_MSG_START_INITIATOR:
		reply(msg,
		      IS_ENABLED(CONFIG_APP_CS_ROLES_INITIATOR) ? start_role(msg, CS_ROLE_KIND_INITIATOR) : -ENOTSUP);
		break;
	case CS_ROLE_MSG_START_REFLECTOR:
		reply(msg,
		      IS_ENABLED(CONFIG_APP_CS_ROLES_REFLECTOR) ? start_role(msg, CS_ROLE_KIND_REFLECTOR) : -ENOTSUP);
		break;
	case CS_ROLE_MSG_STOP:
		handle_stop_request(msg, CS_ROLE_STOP_HOST, -ECANCELED);
		break;
	case CS_ROLE_MSG_INTERRUPT:
		handle_stop_request(msg, CS_ROLE_STOP_INTERRUPTED, msg->error ? msg->error : -ECANCELED);
		break;
	case CS_ROLE_MSG_CONNECTED:
		cs_role_link_connected(msg);
		break;
	case CS_ROLE_MSG_DISCONNECTED:
		cs_role_link_disconnected(msg);
		break;
	case CS_ROLE_MSG_SECURITY_CHANGED:
		cs_role_link_security(msg);
		break;
	case CS_ROLE_MSG_SCAN_MATCH:
		cs_role_link_scan_match(msg);
		break;
	case CS_ROLE_MSG_PROCEDURE:
		handle_procedure(msg);
		break;
	default:
		if (cs_role.role == CS_ROLE_KIND_INITIATOR) {
			IF_ENABLED(CONFIG_APP_CS_ROLES_INITIATOR, (cs_role_initiator_handle(msg)));
		} else if (cs_role.role == CS_ROLE_KIND_REFLECTOR) {
			IF_ENABLED(CONFIG_APP_CS_ROLES_REFLECTOR, (cs_role_reflector_handle(msg)));
		} else if (msg->type == CS_ROLE_MSG_CONFIG) {
			/* A peer configuration before any START: remember it for the reflector. */
			IF_ENABLED(CONFIG_APP_CS_ROLES_REFLECTOR, (cs_role_reflector_handle(msg)));
		}
		break;
	}
	if (msg->conn) {
		bt_conn_unref(msg->conn);
	}
}

static k_timeout_t next_timeout(void) {
	k_timepoint_t next = cs_role_link_next_timer();

	if (cs_role.deadline_set && (sys_timepoint_cmp(cs_role.deadline, next) < 0)) {
		next = cs_role.deadline;
	}
	return sys_timepoint_timeout(next);
}

static void role_loop(void *p1,
                      void *p2,
                      void *p3) {
	struct cs_role_msg msg;

	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);
	for (;;) {
		if (k_msgq_get(&role_msgs, &msg, next_timeout()) == 0) {
			handle(&msg);
		}
		if (cs_role.deadline_set && sys_timepoint_expired(cs_role.deadline)) {
			handle_timeout();
		}
		cs_role_link_timers();
	}
}

/* CS callbacks, Bluetooth context: copy and post. */

static struct bt_conn *conn_ref_if_ours(struct bt_conn *conn) {
	return cs_role_is_ours(conn) ? bt_conn_ref(conn) : NULL;
}

static void remote_capabilities_cb(struct bt_conn *conn,
                                   uint8_t status,
                                   struct bt_conn_le_cs_capabilities *params) {
	struct cs_capabilities record;
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_REMOTE_CAPABILITIES, .status = status };

	msg.conn = conn_ref_if_ours(conn);
	if (!msg.conn) {
		return;
	}
	if (!status && params && cs_capabilities_pack(&record, conn, params, 0U) == 0) {
		cs_role_event_capabilities(&record);
		msg.cs.fae_needed = !params->cs_without_fae_supported;
		msg.cs.ipt = params->cs_ipt_reflector;
	}
	if (!status && params) {
		msg.cs.num_antennas = params->num_antennas_supported;
	}
	cs_role_post(&msg);
}

static void config_cb(struct bt_conn *conn,
                      uint8_t status,
                      struct bt_conn_le_cs_config *config) {
	struct cs_config_complete record;
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_CONFIG, .status = status };

	msg.conn = conn_ref_if_ours(conn);
	if (!msg.conn) {
		return;
	}
	/* TEMPORARY (2026-09-23): the Zephyr struct as the controller delivered it,
	 * before cs_config_complete_pack() touches it, to check the reported
	 * main-mode steps against the recording. Remove once that is answered. */
	if (!status && config) {
		APP_LOG_INF("Zephyr config: id %u, mode 0x%02x, main steps %u-%u, main rep %u, "
		            "mode-0 steps %u, role %u, RTT type %u, sync PHY %u",
		            (unsigned int)config->id,
		            (unsigned int)config->mode,
		            (unsigned int)config->min_main_mode_steps,
		            (unsigned int)config->max_main_mode_steps,
		            (unsigned int)config->main_mode_repetition,
		            (unsigned int)config->mode_0_steps,
		            (unsigned int)config->role,
		            (unsigned int)config->rtt_type,
		            (unsigned int)config->cs_sync_phy);
		APP_LOG_INF("Zephyr config: map rep %u, chsel %u, 3c shape %u, 3c jump %u, "
		            "enh 0x%02x, T_IP1 %u, T_IP2 %u, T_FCS %u, T_PM %u us",
		            (unsigned int)config->channel_map_repetition,
		            (unsigned int)config->channel_selection_type,
		            (unsigned int)config->ch3c_shape,
		            (unsigned int)config->ch3c_jump,
		            (unsigned int)config->cs_enhancements_1,
		            (unsigned int)config->t_ip1_time_us,
		            (unsigned int)config->t_ip2_time_us,
		            (unsigned int)config->t_fcs_time_us,
		            (unsigned int)config->t_pm_time_us);
	}
	if (cs_config_complete_pack(&record, conn, status, config, 0U) == 0) {
		cs_role_event_configuration(&record);
	}
	if (!status && config) {
		msg.cs.config_id = config->id;
		msg.cs.rtt_type = config->rtt_type;
		msg.cs.ipt = (config->cs_enhancements_1 & CS_CONFIG_ENHANCEMENTS_1_IPT) != 0U;
		if (config->id <= CS_CONFIG_ID_MAX) {
			/* The data path needs the layout before the first subevent. */
			cs_role_data.rtt_types[config->id] = config->rtt_type;
			atomic_or(&cs_role_data.layouts, BIT(config->id));
			cs_role_data.counter = (struct cs_subevent_counter){ 0 };
		}
	}
	cs_role_post(&msg);
}

static void security_cb(struct bt_conn *conn,
                        uint8_t status) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_CS_SECURITY, .status = status };

	msg.conn = conn_ref_if_ours(conn);
	if (msg.conn) {
		cs_role_post(&msg);
	}
}

static void procedure_cb(struct bt_conn *conn,
                         uint8_t status,
                         struct bt_conn_le_cs_procedure_enable_complete *params) {
	struct cs_procedure_enable_complete record;
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_PROCEDURE, .status = status };

	msg.conn = conn_ref_if_ours(conn);
	if (!msg.conn) {
		return;
	}
	if (cs_procedure_enable_complete_pack(&record, conn, status, params, 0U) == 0) {
		cs_role_event_procedure(&record);
	}
	if (params) {
		msg.cs.config_id = params->config_id;
		msg.cs.state = params->state;
	}
	cs_role_post(&msg);
}

static void subevent_cb(struct bt_conn *conn,
                        struct bt_conn_le_cs_subevent_result *result) {
	enum cs_role_kind kind = (enum cs_role_kind)atomic_get(&cs_role_data.role);

	if (!cs_role_is_ours(conn) || !result || kind == CS_ROLE_KIND_NONE) {
		return;
	}
	if (result->header.procedure_done_status == BT_CONN_LE_CS_PROCEDURE_COMPLETE) {
		atomic_inc(&cs_role_data.procedures_completed);
	}
	cs_role_stream_hci(result,
	                   kind == CS_ROLE_KIND_INITIATOR ? BT_CONN_LE_CS_ROLE_INITIATOR
	                                                  : BT_CONN_LE_CS_ROLE_REFLECTOR);
	/* The local steps are buffered only for the RAS parser. */
	if (kind == CS_ROLE_KIND_INITIATOR && atomic_get(&cs_role_data.ras)) {
		IF_ENABLED(CONFIG_APP_CS_ROLES_INITIATOR, (cs_role_initiator_local_subevent(result)));
	}
}

#if defined(CONFIG_APP_CS_ROLES_INITIATOR)
static void fae_cb(struct bt_conn *conn,
                   uint8_t status,
                   struct bt_conn_le_cs_fae_table *params) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_FAE, .status = status };

	msg.conn = conn_ref_if_ours(conn);
	if (!msg.conn) {
		return;
	}
	cs_role_event_fae(status, (!status && params) ? params->remote_fae_table : NULL);
	cs_role_post(&msg);
}
#endif

BT_CONN_CB_DEFINE(cs_role_cs_callbacks) = {
	.le_cs_read_remote_capabilities_complete = remote_capabilities_cb,
#if defined(CONFIG_APP_CS_ROLES_INITIATOR)
	.le_cs_read_remote_fae_table_complete = fae_cb,
#endif
	.le_cs_config_complete = config_cb,
	.le_cs_security_enable_complete = security_cb,
	.le_cs_procedure_enable_complete = procedure_cb,
	.le_cs_subevent_data_available = subevent_cb,
};

/* API. */

int cs_role_init(const struct cs_role_callbacks *callbacks) {
	if (!callbacks) {
		return -EINVAL;
	}
	if (!atomic_cas(&initialized, 0, 1)) {
		return -EALREADY;
	}
	cs_role.callbacks = callbacks;
	int err = cs_role_link_init();

	if (err) {
		atomic_clear(&initialized);
		return err;
	}
	cs_role_events_init(callbacks);
	k_thread_create(&role_thread,
	                role_stack,
	                K_THREAD_STACK_SIZEOF(role_stack),
	                role_loop,
	                NULL,
	                NULL,
	                NULL,
	                K_PRIO_PREEMPT(CONFIG_APP_CS_ROLES_THREAD_PRIORITY),
	                0,
	                K_NO_WAIT);
	k_thread_name_set(&role_thread, "cs_role");
	return 0;
}

int cs_role_scan_start(void) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_SCAN_START };

	return request(&msg);
}

int cs_role_link_start(const struct cs_role_link_params *params) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_LINK_START };

	if (!params || (params->pattern_count && !params->patterns)) {
		return -EINVAL;
	}
	msg.link.params = *params;
	if (params->peer) {
		msg.link.peer = *params->peer;
	}
	return request(&msg);
}

int cs_role_link_disconnect(k_timeout_t timeout) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_LINK_DISCONNECT, .timeout = timeout };

	return request(&msg);
}

bool cs_role_link_active(void) {
	return atomic_get(&cs_role_link_phase) != CS_ROLE_LINK_IDLE;
}

int cs_role_start_initiator(const struct cs_initiator_config *config) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_START_INITIATOR };

	if (!config || cs_initiator_config_check_peer_data(config)) {
		return -EINVAL;
	}
	msg.initiator = *config;
	return request(&msg);
}

int cs_role_start_reflector(const struct cs_reflector_config *config) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_START_REFLECTOR };

	if (!config) {
		return -EINVAL;
	}
	msg.reflector = *config;
	return request(&msg);
}

int cs_role_stop(void) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_STOP };

	return request(&msg);
}

void cs_role_interrupt(int error) {
	struct cs_role_msg msg = { .type = CS_ROLE_MSG_INTERRUPT, .error = error };

	if (atomic_get(&running)) {
		(void)request(&msg);
	}
}

bool cs_role_running(void) {
	return atomic_get(&running);
}
