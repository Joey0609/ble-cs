/* SPDX-License-Identifier: MIT */
/* Bluetooth build: host link handlers -> CS initiator / reflector roles. */
#include <app_version.h>
#include <errno.h>
#include <string.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/kernel.h>

#include "app_log/app_log.h"
#include "client_state.h"
#include "cs_roles/cs_role.h"
#include "cs_utils/cs_config.h"
#include "host_link/host_link.h"
#include "host_link/host_link_config.h"
#include "host_link/host_link_reports.h"
#include "peer_discovery.h"
#include "session.h"

APP_LOG_MODULE(cs_session);

/* Records of the applied configuration, converted with the cs_utils setters. */
static struct cs_initiator_config initiator;
static struct cs_reflector_config reflector;
static uint8_t gap_role;

/* The link layer owns the negotiated values; retain the latest snapshot so a
 * host that opens USB after Bluetooth connection setup still receives them. */
static struct k_spinlock connection_params_lock;
static struct cs_config_connection connection_params;
static uint16_t connection_mtu;
static bool connection_params_valid;

static void report_connection_params_work(struct k_work *work);
static K_WORK_DEFINE(connection_params_report_work,
                     report_connection_params_work);

static void role_connection_params(const struct cs_config_connection *params,
                                   uint16_t mtu) {
	if (!params) {
		return;
	}
	K_SPINLOCK(&connection_params_lock) {
		connection_params = *params;
		connection_mtu = mtu;
		connection_params_valid = true;
	}
	(void)k_work_submit(&connection_params_report_work);
}

static void report_connection_params_work(struct k_work *work) {
	struct cs_config_connection params;
	uint16_t mtu = 0;
	bool valid = false;

	ARG_UNUSED(work);
	if (!host_link_session_active()) {
		return;
	}
	K_SPINLOCK(&connection_params_lock) {
		params = connection_params;
		mtu = connection_mtu;
		valid = connection_params_valid;
	}
	if (valid) {
		(void)host_link_report_connection_parameters(params.interval_min,
		                                             params.latency,
		                                             params.timeout,
		                                             mtu);
	}
}

static uint8_t get_state(void) {
	return client_state_get();
}

/* Discovery and connection establishment are separate from CS START. */
static bool link_active(void) {
	return peer_discovery_active();
}

static const char *peer_data_name(uint8_t peer_data) {
	return peer_data == CS_CONFIG_PEER_DATA_NONE ? "none (initiator only)" : "RAS real-time";
}

static int convert(uint8_t mode,
                   const uint8_t *payload,
                   size_t len,
                   struct cs_initiator_config *initiator_out,
                   struct cs_reflector_config *reflector_out) {
	switch (mode) {
	case CS_PROTOCOL_MODE_CS_INITIATOR:
		return host_link_config_to_initiator(payload, len, initiator_out);
	case CS_PROTOCOL_MODE_CS_REFLECTOR:
		return host_link_config_to_reflector(payload, len, reflector_out);
	default:
		return -ENOTSUP;
	}
}

static struct host_link_result validate_config(uint8_t mode,
                                               const uint8_t *payload,
                                               size_t len) {
	struct cs_initiator_config initiator_check;
	struct cs_reflector_config reflector_check;
	int err = convert(mode, payload, len, &initiator_check, &reflector_check);

	if (err == -ENOTSUP) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_UNSUPPORTED, CS_PROTOCOL_REASON_NONE);
	}
	return err ? HOST_LINK_RESULT_OUT_OF_RANGE(err) : HOST_LINK_RESULT_OK;
}

static struct host_link_result apply(const struct host_link_config_set *set) {
	struct cs_initiator_config initiator_new;
	struct cs_reflector_config reflector_new;
	/* The initiator record also takes SET_PEER_DATA, checked against the IPT request. */
	int err = set->mode == CS_PROTOCOL_MODE_CS_INITIATOR
	                  ? host_link_config_set_to_initiator(set, &initiator_new)
	                  : convert(set->mode, set->config, set->config_len, &initiator_new, &reflector_new);

	if (err) {
		return HOST_LINK_RESULT_OUT_OF_RANGE(err);
	}
	char device_name[33] = CONFIG_BT_DEVICE_NAME;
	if (set->has_device_name) {
		memcpy(device_name, &set->device_name[1], set->device_name[0]);
		device_name[set->device_name[0]] = '\0';
	}
	err = bt_set_name(device_name);
	if (err) {
		return HOST_LINK_RESULT_FAILED(err);
	}
	if (set->mode == CS_PROTOCOL_MODE_CS_INITIATOR) {
		initiator = initiator_new;
	} else {
		reflector = reflector_new;
	}
	gap_role = host_link_config_gap_role(set->config);
	peer_discovery_configure(gap_role,
	                         set->mode,
	                         set->mode == CS_PROTOCOL_MODE_CS_INITIATOR ? &initiator.connection
	                                                                    : &reflector.connection);

	APP_LOG_INF("CS %s, GAP %s, config ID %u%s",
	            set->mode == CS_PROTOCOL_MODE_CS_INITIATOR ? "initiator" : "reflector",
	            gap_role == CS_PROTOCOL_GAP_CENTRAL ? "central" : "peripheral",
	            set->mode == CS_PROTOCOL_MODE_CS_INITIATOR ? initiator.config_id : reflector.config_id,
	            set->has_patterns ? ", with peripheral patterns" : "");
	if (set->mode == CS_PROTOCOL_MODE_CS_INITIATOR) {
		APP_LOG_INF("Reflector data: %s, preferred T_PM %u us",
		            peer_data_name(initiator.peer_data),
		            initiator.t_pm_us);
	}
	client_state_set_mode(set->mode);
	client_state_set(CS_PROTOCOL_CLIENT_STATE_CONFIGURED, CS_PROTOCOL_REASON_NONE, 0U, 0);
	return HOST_LINK_RESULT_OK;
}

static struct host_link_result start(const struct host_link_config_set *set) {
	ARG_UNUSED(set);
	int err = client_state_mode() == CS_PROTOCOL_MODE_CS_INITIATOR ? cs_role_start_initiator(&initiator)
	                                                               : cs_role_start_reflector(&reflector);
	if (err == -ENOTCONN) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_CONNECT_FAILED);
	}
	return err ? HOST_LINK_RESULT_FAILED(err) : HOST_LINK_RESULT_OK;
}

/* STOP disables procedures and keeps the link. The initiator also waits for the
 * reflector's data of the last procedure: when it does not arrive, RAS_DATA_LOST
 * has been sent and the response is OK with CS_PROTOCOL_REASON_STOP_TIMEOUT.
 * The host link also calls this at session end: it cancels discovery or a CS
 * setup, and does nothing on an idle link. The role and event threads run above
 * the host link thread, so the STOPPED report of a cancelled setup has been
 * attempted, and kept for the next session, by the time cs_role_stop() returns.
 */
static struct host_link_result stop(void) {
	if (client_state_get() == CS_PROTOCOL_CLIENT_STATE_SCANNING ||
	    client_state_get() == CS_PROTOCOL_CLIENT_STATE_ADVERTISING ||
	    client_state_get() == CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTING) {
		return peer_discovery_stop();
	}
	int err = cs_role_stop();
	if (err == -ETIMEDOUT) {
		return (struct host_link_result){ CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_STOP_TIMEOUT, err };
	}
	return err ? HOST_LINK_RESULT_FAILED(err) : HOST_LINK_RESULT_OK;
}

static void interrupt(int error) {
	cs_role_interrupt(error);
}

/* Also called while RUNNING: procedures are stopped first, reported as a STOP. */
static struct host_link_result link_disconnect(void) {
	int err = cs_role_stop();
	if (err && err != -ETIMEDOUT && err != -ENOTCONN) {
		return HOST_LINK_RESULT_FAILED(err);
	}
	return peer_discovery_stop();
}

static uint8_t failure_reason(enum cs_role_failure_stage stage) {
	switch (stage) {
	case CS_ROLE_FAILURE_CONNECT:
		return CS_PROTOCOL_REASON_CONNECT_FAILED;
	case CS_ROLE_FAILURE_LINK_SECURITY:
		return CS_PROTOCOL_REASON_SECURITY_FAILED;
	case CS_ROLE_FAILURE_RAS_DISCOVERY:
		return CS_PROTOCOL_REASON_RAS_DISCOVERY_FAILED;
	case CS_ROLE_FAILURE_RAS_NO_REALTIME:
		return CS_PROTOCOL_REASON_RAS_NO_REALTIME;
	case CS_ROLE_FAILURE_SECURITY:
		return CS_PROTOCOL_REASON_CS_SECURITY_FAILED;
	case CS_ROLE_FAILURE_CAPABILITIES:
	case CS_ROLE_FAILURE_CONFIG:
	case CS_ROLE_FAILURE_PROCEDURE:
	case CS_ROLE_FAILURE_PEER_ANTENNA:
		return CS_PROTOCOL_REASON_CS_CONFIG_FAILED;
	case CS_ROLE_FAILURE_PEER_IPT:
		return CS_PROTOCOL_REASON_PEER_IPT_UNSUPPORTED;
	default:
		return CS_PROTOCOL_REASON_NONE;
	}
}

static void role_state(enum cs_role_state state,
                       enum cs_role_failure_stage stage,
                       enum cs_role_stop_reason stop_reason,
                       uint8_t hci_status,
                       int error) {
	switch (state) {
	case CS_ROLE_STATE_LINK_CONNECTED:
		client_state_set(CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTED, CS_PROTOCOL_REASON_NONE, 0, 0);
		break;
	case CS_ROLE_STATE_LINK_ENCRYPTED:
		APP_LOG_INF("Peer link encrypted");
		break;
	case CS_ROLE_STATE_LINK_LOST:
		K_SPINLOCK(&connection_params_lock) {
			connection_params_valid = false;
		}
		client_state_set(CS_PROTOCOL_CLIENT_STATE_LINK_LOST,
		                 CS_PROTOCOL_REASON_INTERRUPTED,
		                 hci_status,
		                 error);
		break;
	case CS_ROLE_STATE_LINK_DISCONNECTED:
		K_SPINLOCK(&connection_params_lock) {
			connection_params_valid = false;
		}
		/* peer_discovery.c reports the protocol state for this transition. */
		break;
	case CS_ROLE_STATE_RAS_READY:
		client_state_set(CS_PROTOCOL_CLIENT_STATE_RAS_READY, CS_PROTOCOL_REASON_NONE, 0, 0);
		break;
	case CS_ROLE_STATE_RUNNING:
		client_state_set(CS_PROTOCOL_CLIENT_STATE_RUNNING, CS_PROTOCOL_REASON_NONE, 0, 0);
		break;
	case CS_ROLE_STATE_STOPPED:
		if (stop_reason == CS_ROLE_STOP_COMPLETE) {
			client_state_set(CS_PROTOCOL_CLIENT_STATE_STOPPED,
			                 CS_PROTOCOL_REASON_TEST_COMPLETE,
			                 hci_status,
			                 0);
		} else {
			/* HOST: -ECANCELED. PEER: the initiator stopped this reflector,
			 * reported as -ECONNABORTED. INTERRUPTED and LINK_LOST carry their error.
			 */
			client_state_set(CS_PROTOCOL_CLIENT_STATE_STOPPED,
			                 CS_PROTOCOL_REASON_INTERRUPTED,
			                 hci_status,
			                 stop_reason == CS_ROLE_STOP_PEER ? -ECONNABORTED
			                 : error                          ? error
			                                                  : -ECANCELED);
		}
		break;
	case CS_ROLE_STATE_ERROR:
		client_state_set(CS_PROTOCOL_CLIENT_STATE_ERROR, failure_reason(stage), hci_status, error);
		break;
	default:
		/* SCANNING, ADVERTISING, LINK_CONNECTING and LINK_DISCONNECTED follow
		 * host commands; peer_discovery.c reports them with the response. */
		break;
	}
}

static void role_capabilities(const struct cs_capabilities *record) {
	(void)host_link_report_cs_capabilities(record);
}
/* The initiator follows the configuration with its reflector data setting,
 * before the first subevent: the controller's report does not carry it.
 */
static void role_configuration(const struct cs_config_complete *record) {
	(void)host_link_report_cs_configuration(record);
	if (client_state_mode() == CS_PROTOCOL_MODE_CS_INITIATOR && record->status == 0U) {
		(void)host_link_report_peer_data(initiator.peer_data);
	}
}
static void role_procedure(const struct cs_procedure_enable_complete *record) {
	(void)host_link_report_cs_procedure(record);
}
/* Subevents are encoded straight into the transmit buffer (Bluetooth context). */
static int role_subevent_begin(const struct cs_subevent *header,
                               uint16_t num_tones) {
	return host_link_report_cs_subevent_begin(header, num_tones);
}
static void role_subevent_step(const struct cs_step_header *step) {
	host_link_report_cs_subevent_step(step);
}
static void role_subevent_end(bool complete) {
	ARG_UNUSED(complete);
	(void)host_link_report_cs_subevent_end();
}
static void role_fae(uint8_t status,
                     uint8_t lsb_denominator,
                     const int8_t *entries) {
	(void)host_link_report_fae_table(status, entries, lsb_denominator);
}
static void role_ras_lost(uint16_t counter,
                          int error) {
	(void)host_link_report_ras_data_lost(counter, error);
}
/* Precedes STOPPED(COMPLETE), which reports CLIENT_STATE(STOPPED, TEST_COMPLETE). */
static void role_procedures_complete(uint16_t procedures_completed) {
	(void)host_link_report_cs_procedures_complete(procedures_completed);
}

static const struct cs_role_callbacks role_callbacks = {
	.state = role_state,
	.connection_params = role_connection_params,
	.scan_result = peer_discovery_scan_result,
	.capabilities = role_capabilities,
	.configuration = role_configuration,
	.procedure = role_procedure,
	.subevent_begin = role_subevent_begin,
	.subevent_step = role_subevent_step,
	.subevent_end = role_subevent_end,
	.fae_table = role_fae,
	.ras_data_lost = role_ras_lost,
	.procedures_complete = role_procedures_complete,
};

/* Applied configuration and an established Bluetooth link span host sessions. */
static void session_changed(bool active) {
	client_state_session_changed(active);
	if (active) {
		/* Runs after CONNECT_RESPONSE, so the report follows the handshake. */
		(void)k_work_submit(&connection_params_report_work);
	}
}

static const struct host_link_handlers handlers = {
	.supported_modes = CS_PROTOCOL_MODE_BIT(CS_PROTOCOL_MODE_CS_INITIATOR) |
	                   CS_PROTOCOL_MODE_BIT(CS_PROTOCOL_MODE_CS_REFLECTOR),
	.firmware_version = APPVERSION,
	.client_state = get_state,
	.link_active = link_active,
	.discovery = peer_discovery_command,
	.validate_config = validate_config,
	.apply = apply,
	.start = start,
	.stop = stop,
	.interrupt = interrupt,
	.link_disconnect = link_disconnect,
	.session_changed = session_changed,
};

int session_init(void) {
	/* Enabling the stack starts no scanning or advertising. */
	int err = bt_enable(NULL);
	if (!err) {
		err = cs_role_init(&role_callbacks);
	}
	return err;
}

const struct host_link_handlers *session_handlers(void) {
	return &handlers;
}

const char *session_build_name(void) {
	return "Bluetooth";
}
