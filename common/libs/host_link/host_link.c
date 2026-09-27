/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/byteorder.h>

#include "app_log/app_log.h"
#include "host_link.h"
#include "host_link_config_store.h"
#include "host_link_internal.h"
#include "host_link_names.h"
#include "host_link_reports.h"
#include "host_link_transport.h"

APP_LOG_MODULE(host_link);

BUILD_ASSERT(CONFIG_APP_HOST_LINK_MAX_FRAME_SIZE >= sizeof(struct cs_protocol_peripheral_patterns_frame_t),
             "The largest host command must fit the receive frame buffer");
BUILD_ASSERT(CONFIG_APP_HOST_LINK_MAX_FRAME_SIZE <= UINT16_MAX);
BUILD_ASSERT((int)CS_PROTOCOL_LOG_CONSOLE_LEVEL_DEFAULT == (int)APP_LOG_CONSOLE_LEVEL_DEFAULT &&
                     (int)CS_PROTOCOL_LOG_PROTOCOL_LEVEL_DEFAULT == (int)APP_LOG_PROTOCOL_LEVEL_DEFAULT,
             "SET_LOG_CONFIG defaults are the app_log defaults");
BUILD_ASSERT((int)CS_PROTOCOL_LOG_LEVEL_DEBUG == (int)APP_LOG_LEVEL_MAX);

static const struct host_link_handlers *handlers;
static struct host_link_config_store store;
static atomic_t session_active;
static atomic_t reports_sent;
static atomic_t reports_dropped;
/* Reports lost for lack of transmit room in this session, not yet printed. */
static atomic_t reports_lost;

static K_SEM_DEFINE(rx_ready,
                    0,
                    1);
static uint8_t parser_buf[CONFIG_APP_HOST_LINK_MAX_FRAME_SIZE];
static uint8_t frame_buf[CONFIG_APP_HOST_LINK_MAX_FRAME_SIZE];
static struct cs_protocol_parser_t parser;

K_THREAD_STACK_DEFINE(host_link_stack,
                      CONFIG_APP_HOST_LINK_THREAD_STACK_SIZE);
static struct k_thread host_link_thread_data;

/* Expected frame size of every host command; 0 for other types. */
static size_t command_frame_size(uint16_t type) {
	switch (type) {
	case CS_PROTOCOL_PACKET_SCAN_START:
	case CS_PROTOCOL_PACKET_ADVERTISE_START:
		return CS_PROTOCOL_OVERHEAD;
	case CS_PROTOCOL_PACKET_PEER_CONNECT:
		return sizeof(struct cs_protocol_peer_connect_frame_t);
	case CS_PROTOCOL_PACKET_SET_OPERATION_MODE:
		return sizeof(struct cs_protocol_operation_mode_frame_t);
	case CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG:
		return sizeof(struct cs_protocol_cs_initiator_config_frame_t);
	case CS_PROTOCOL_PACKET_SET_CS_REFLECTOR_CONFIG:
		return sizeof(struct cs_protocol_cs_reflector_config_frame_t);
	case CS_PROTOCOL_PACKET_SET_RADIO_TX_TEST_CONFIG:
		return sizeof(struct cs_protocol_radio_tx_test_config_frame_t);
	case CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS:
		return sizeof(struct cs_protocol_peripheral_patterns_frame_t);
	case CS_PROTOCOL_PACKET_APPLY_CONFIG:
		return sizeof(struct cs_protocol_apply_config_frame_t);
	case CS_PROTOCOL_PACKET_CONNECT:
		return sizeof(struct cs_protocol_connect_frame_t);
	case CS_PROTOCOL_PACKET_START:
		return sizeof(struct cs_protocol_start_frame_t);
	case CS_PROTOCOL_PACKET_STOP:
		return sizeof(struct cs_protocol_stop_frame_t);
	case CS_PROTOCOL_PACKET_CLOSE_SESSION:
		return sizeof(struct cs_protocol_close_session_frame_t);
	case CS_PROTOCOL_PACKET_GET_CONFIG:
		return sizeof(struct cs_protocol_get_config_frame_t);
	case CS_PROTOCOL_PACKET_SET_DEVICE_NAME:
		return sizeof(struct cs_protocol_device_name_frame_t);
	case CS_PROTOCOL_PACKET_SET_PEER_DATA:
		return sizeof(struct cs_protocol_peer_data_frame_t);
	case CS_PROTOCOL_PACKET_SET_T_PM:
		return sizeof(struct cs_protocol_t_pm_frame_t);
	case CS_PROTOCOL_PACKET_SET_LOG_CONFIG:
		return sizeof(struct cs_protocol_log_config_frame_t);
	case CS_PROTOCOL_PACKET_LINK_DISCONNECT:
		return sizeof(struct cs_protocol_link_disconnect_frame_t);
	default:
		return 0U;
	}
}

static bool changes_config(uint16_t type) {
	return type == CS_PROTOCOL_PACKET_SET_OPERATION_MODE || host_link_config_mode_of_type(type) >= 0 ||
	       type == CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS || type == CS_PROTOCOL_PACKET_SET_DEVICE_NAME ||
	       type == CS_PROTOCOL_PACKET_SET_PEER_DATA || type == CS_PROTOCOL_PACKET_SET_T_PM ||
	       type == CS_PROTOCOL_PACKET_SET_LOG_CONFIG || type == CS_PROTOCOL_PACKET_APPLY_CONFIG;
}

static int send_frame(const uint8_t *frame,
                      size_t len) {
	int err = host_link_transport_send(frame, len, HOST_LINK_TRANSPORT_WAIT_RESPONSE);

	if (err) {
		APP_LOG_WRN("Frame type 0x%04x not sent: %d", sys_get_le16(&frame[4]), err);
	}
	return err;
}

/* announce_loss: count a report lost for transmit room in reports_lost, which
 * report_losses() logs.
 */
static int send_report(const uint8_t *frame,
                       size_t len,
                       bool announce_loss) {
	int err;

	if (!atomic_get(&session_active)) {
		atomic_inc(&reports_dropped);
		return -ENOTCONN;
	}
	err = host_link_transport_send(frame, len, HOST_LINK_TRANSPORT_WAIT_REPORT);
	if (err) {
		atomic_inc(&reports_dropped);
		if (announce_loss) {
			atomic_inc(&reports_lost);
		}
	} else {
		atomic_inc(&reports_sent);
	}
	return err;
}

int host_link_send_report(const uint8_t *frame,
                          size_t len) {
	return send_report(frame, len, true);
}

/* app_log protocol consumer, on the log thread. A LOG_MESSAGE lost for
 * transmit room is counted but not announced: the announcement is itself a
 * log message and would be lost the same way.
 */
static void log_sink_write(uint8_t level,
                           uint32_t timestamp_ms,
                           const char *text,
                           size_t len) {
	static uint8_t frame[CS_PROTOCOL_OVERHEAD + CONFIG_APP_LOG_MESSAGE_MAX];
	int frame_len;

	ARG_UNUSED(level);
	ARG_UNUSED(timestamp_ms);
	frame_len = cs_protocol_encode(frame,
	                               sizeof(frame),
	                               CS_PROTOCOL_PACKET_LOG_MESSAGE,
	                               text,
	                               MIN(len, (size_t)CONFIG_APP_LOG_MESSAGE_MAX));
	if (frame_len > 0) {
		(void)send_report(frame, (size_t)frame_len, false);
	}
}

static int report_sink_begin(void *ctx,
                             size_t len) {
	int err;

	ARG_UNUSED(ctx);
	if (!atomic_get(&session_active)) {
		atomic_inc(&reports_dropped);
		return -ENOTCONN;
	}
	/* Never waits: streamed reports are written from Bluetooth callbacks. */
	err = host_link_transport_frame_begin(len);
	if (err) {
		atomic_inc(&reports_dropped);
		atomic_inc(&reports_lost);
	}
	return err;
}

static void report_sink_write(void *ctx,
                              const uint8_t *data,
                              size_t len) {
	ARG_UNUSED(ctx);
	host_link_transport_frame_write(data, len);
}

static int report_sink_end(void *ctx) {
	int err;

	ARG_UNUSED(ctx);
	err = host_link_transport_frame_end();
	if (err) {
		atomic_inc(&reports_dropped);
		atomic_inc(&reports_lost);
	} else {
		atomic_inc(&reports_sent);
	}
	return err;
}

const struct host_link_frame_sink host_link_report_sink = {
	.begin = report_sink_begin,
	.write = report_sink_write,
	.end = report_sink_end,
};

void host_link_report_counters(uint32_t *sent,
                               uint32_t *dropped) {
	*sent = (uint32_t)atomic_get(&reports_sent);
	*dropped = (uint32_t)atomic_get(&reports_dropped);
}

static void send_response(uint16_t request_type,
                          struct host_link_result result) {
	struct cs_protocol_command_response_frame_t frame = {
		.request_type = sys_cpu_to_le16(request_type),
		.status = result.status,
		.reason = result.reason,
		.error = (int32_t)sys_cpu_to_le32((uint32_t)result.error),
		.config_crc32 = sys_cpu_to_le32(store.applied_valid ? store.applied_crc32 : 0U),
	};

	if (result.status == CS_PROTOCOL_STATUS_FAILED) {
		APP_LOG_ERR("Command %s (0x%04x) failed: reason %s, error %d",
		            host_link_command_name(request_type),
		            request_type,
		            host_link_reason_name(result.reason),
		            (int)result.error);
	} else if (result.status != CS_PROTOCOL_STATUS_OK) {
		APP_LOG_WRN("Command %s (0x%04x) refused: status %s, reason %s, error %d",
		            host_link_command_name(request_type),
		            request_type,
		            host_link_status_name(result.status),
		            host_link_reason_name(result.reason),
		            (int)result.error);
	}
	(void)cs_protocol_finalize_frame(&frame, sizeof(frame), CS_PROTOCOL_PACKET_COMMAND_RESPONSE);
	(void)send_frame((const uint8_t *)&frame, sizeof(frame));
}

/* Returns true when the session state changed. */
static bool set_session(bool active) {
	if (atomic_set(&session_active, active) == (atomic_val_t)active) {
		return false;
	}
	/* A partly staged configuration never outlives its session. */
	memset(&store.staged, 0, sizeof(store.staged));
	atomic_clear(&reports_lost);
	/* Without a session, protocol log messages are not even formatted. */
	(void)app_log_sink_register(APP_LOG_SINK_PROTOCOL, active ? log_sink_write : NULL);
	APP_LOG_INF("Host session %s", active ? "opened" : "closed");
	return true;
}

/* A host session owns only its partially staged configuration. The applied
 * configuration and Bluetooth link live until reset or LINK_DISCONNECT. A
 * running operation is interrupted; discovery, a connection attempt and a CS
 * setup are stopped, since no host is left to receive their results. The
 * session is closed first, so a stop reported with an error is kept by the
 * application and delivered after the next CONNECT.
 */
static void end_session(int error) {
	uint8_t state;

	if (!set_session(false)) {
		return;
	}
	if (error != -ECANCELED) {
		APP_LOG_WRN("Host link dropped: port closed without CLOSE_SESSION (%d)", error);
	}
	state = handlers->client_state();
	switch (state) {
	case CS_PROTOCOL_CLIENT_STATE_RUNNING:
		APP_LOG_WRN("Operation interrupted (%d)", error);
		handlers->interrupt(error);
		break;
	case CS_PROTOCOL_CLIENT_STATE_SCANNING:
	case CS_PROTOCOL_CLIENT_STATE_ADVERTISING:
	case CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTING:
	case CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTED:
	case CS_PROTOCOL_CLIENT_STATE_RAS_READY: {
		/* A CS setup runs while the state is LINK_CONNECTED or RAS_READY;
		 * stop() does nothing on an idle link.
		 */
		struct host_link_result result;

		APP_LOG_WRN("Stopping the client in %s (%d)", host_link_state_name(state), error);
		result = handlers->stop();
		if (result.status != CS_PROTOCOL_STATUS_OK) {
			APP_LOG_WRN("Stop at session end failed: reason %s, error %d",
			            host_link_reason_name(result.reason),
			            (int)result.error);
		}
		break;
	}
	default:
		break;
	}
	if (handlers->session_changed) {
		handlers->session_changed(false);
	}
	APP_LOG_INF("Waiting for the next host session; applied configuration retained");
}

static void handle_connect(const struct cs_protocol_packet_t *packet,
                           size_t frame_len) {
	struct cs_protocol_connect_response_frame_t frame = {
		.status = CS_PROTOCOL_STATUS_OK,
		.protocol_version = sys_cpu_to_le16(CS_PROTOCOL_VERSION),
		.supported_modes = handlers->supported_modes,
		.firmware_version = sys_cpu_to_le32(handlers->firmware_version),
		.max_frame_size = sys_cpu_to_le16(CONFIG_APP_HOST_LINK_MAX_FRAME_SIZE),
		.config_valid = store.applied_valid,
		.operation_mode = store.applied_valid ? store.applied.mode : CS_PROTOCOL_MODE_NONE,
		.config_crc32 = sys_cpu_to_le32(store.applied_valid ? store.applied_crc32 : 0U),
		.client_state = handlers->client_state(),
		.num_antennas_supported = CONFIG_APP_HOST_LINK_NUM_ANTENNAS,
	};

	if (frame_len != sizeof(struct cs_protocol_connect_frame_t)) {
		frame.status = CS_PROTOCOL_STATUS_INVALID_FRAME;
	} else if (sys_get_le16(packet->payload) != CS_PROTOCOL_VERSION) {
		frame.status = CS_PROTOCOL_STATUS_VERSION;
	}
	/* No session to carry a LOG_MESSAGE: CONNECT_RESPONSE.status tells the host. */
	if (frame.status != CS_PROTOCOL_STATUS_OK) {
		APP_LOG_WRN("CONNECT refused: status %s", host_link_status_name(frame.status));
	}
	bool opened = frame.status == CS_PROTOCOL_STATUS_OK && set_session(true);

	(void)cs_protocol_finalize_frame(&frame, sizeof(frame), CS_PROTOCOL_PACKET_CONNECT_RESPONSE);
	(void)send_frame((const uint8_t *)&frame, sizeof(frame));
	/* After the response, so reports raised by the callback (e.g. an undelivered
	 * interruption) follow CONNECT_RESPONSE in an open session.
	 */
	if (opened && handlers->session_changed) {
		handlers->session_changed(true);
	}
}

static struct host_link_result handle_config_frame(uint16_t type,
                                                   const uint8_t *payload,
                                                   size_t len) {
	struct host_link_result result = host_link_config_check_config(&store, type);

	if (result.status != CS_PROTOCOL_STATUS_OK) {
		return result;
	}
	result = handlers->validate_config(store.staged.mode, payload, len);
	if (result.status == CS_PROTOCOL_STATUS_OK) {
		host_link_config_stage_config(&store, payload, len);
	}
	return result;
}

/* The log levels of a configuration set; the defaults without SET_LOG_CONFIG. */
static void log_config_of(const struct host_link_config_set *set,
                          struct app_log_config *config) {
	app_log_defaults(config);
	if (set->has_log_config) {
		config->console_level = set->log_config[0];
		config->protocol_level = set->log_config[1];
	}
}

static struct host_link_result handle_apply(void) {
	struct host_link_result result = host_link_config_check_apply(&store);
	struct app_log_config log_config;

	if (result.status != CS_PROTOCOL_STATUS_OK) {
		return result;
	}
	result = handlers->apply(&store.staged);
	if (result.status == CS_PROTOCOL_STATUS_OK) {
		/* Checked when staged: the levels are valid. */
		log_config_of(&store.staged, &log_config);
		(void)app_log_configure(&log_config);
		host_link_config_commit(&store);
		APP_LOG_INF("Applied mode %u, CRC 0x%08x, log levels console %u, host %u",
		            store.applied.mode,
		            store.applied_crc32,
		            log_config.console_level,
		            log_config.protocol_level);
	}
	return result;
}

static struct host_link_result handle_get_config(void) {
	const struct host_link_config_set *applied = &store.applied;
	size_t config_len;
	uint16_t config_type;
	int len;

	if (!store.applied_valid) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
	}
	config_type = host_link_config_type_of_mode(applied->mode, &config_len);

	len = cs_protocol_encode(frame_buf,
	                         sizeof(frame_buf),
	                         CS_PROTOCOL_PACKET_SET_OPERATION_MODE,
	                         &applied->mode,
	                         HOST_LINK_MODE_PAYLOAD_SIZE);
	if (len < 0 || send_frame(frame_buf, len)) {
		return HOST_LINK_RESULT_FAILED(-EIO);
	}
	len = cs_protocol_encode(frame_buf, sizeof(frame_buf), config_type, applied->config, applied->config_len);
	if (len < 0 || send_frame(frame_buf, len)) {
		return HOST_LINK_RESULT_FAILED(-EIO);
	}
	if (applied->has_patterns) {
		len = cs_protocol_encode(frame_buf,
		                         sizeof(frame_buf),
		                         CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS,
		                         applied->patterns,
		                         HOST_LINK_PATTERNS_PAYLOAD_SIZE);
		if (len < 0 || send_frame(frame_buf, len)) {
			return HOST_LINK_RESULT_FAILED(-EIO);
		}
	}
	if (applied->has_device_name) {
		len = cs_protocol_encode(frame_buf,
		                         sizeof(frame_buf),
		                         CS_PROTOCOL_PACKET_SET_DEVICE_NAME,
		                         applied->device_name,
		                         HOST_LINK_DEVICE_NAME_PAYLOAD_SIZE);
		if (len < 0 || send_frame(frame_buf, len)) {
			return HOST_LINK_RESULT_FAILED(-EIO);
		}
	}
	if (applied->has_peer_data) {
		len = cs_protocol_encode(frame_buf,
		                         sizeof(frame_buf),
		                         CS_PROTOCOL_PACKET_SET_PEER_DATA,
		                         &applied->peer_data,
		                         HOST_LINK_PEER_DATA_PAYLOAD_SIZE);
		if (len < 0 || send_frame(frame_buf, len)) {
			return HOST_LINK_RESULT_FAILED(-EIO);
		}
	}
	if (applied->has_t_pm) {
		len = cs_protocol_encode(frame_buf,
		                         sizeof(frame_buf),
		                         CS_PROTOCOL_PACKET_SET_T_PM,
		                         &applied->t_pm_us,
		                         HOST_LINK_T_PM_PAYLOAD_SIZE);
		if (len < 0 || send_frame(frame_buf, len)) {
			return HOST_LINK_RESULT_FAILED(-EIO);
		}
	}
	if (applied->has_log_config) {
		len = cs_protocol_encode(frame_buf,
		                         sizeof(frame_buf),
		                         CS_PROTOCOL_PACKET_SET_LOG_CONFIG,
		                         applied->log_config,
		                         HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE);
		if (len < 0 || send_frame(frame_buf, len)) {
			return HOST_LINK_RESULT_FAILED(-EIO);
		}
	}
	return HOST_LINK_RESULT_OK;
}

static struct host_link_result handle_start(const uint8_t *payload) {
	if (!store.applied_valid) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
	}
	if (sys_get_le32(payload) != store.applied_crc32) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_CONFIG_MISMATCH, CS_PROTOCOL_REASON_NONE);
	}
	if (handlers->client_state() == CS_PROTOCOL_CLIENT_STATE_RUNNING) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_BUSY);
	}
	return handlers->start(&store.applied);
}

static struct host_link_result handle_command(uint16_t type,
                                              const uint8_t *payload,
                                              size_t len) {
	if (changes_config(type)) {
		if (handlers->client_state() == CS_PROTOCOL_CLIENT_STATE_RUNNING) {
			return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_BUSY);
		}
		if (handlers->link_active()) {
			return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_LINK_ACTIVE);
		}
	}

	switch (type) {
	case CS_PROTOCOL_PACKET_SCAN_START:
	case CS_PROTOCOL_PACKET_ADVERTISE_START:
	case CS_PROTOCOL_PACKET_PEER_CONNECT:
		if (!handlers->discovery) {
			return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_UNSUPPORTED, CS_PROTOCOL_REASON_NONE);
		}
		if (!store.applied_valid) {
			return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
		}
		if (handlers->client_state() == CS_PROTOCOL_CLIENT_STATE_RUNNING) {
			return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_BUSY);
		}
		return handlers->discovery(type, payload);
	case CS_PROTOCOL_PACKET_SET_OPERATION_MODE:
		if (payload[0] > CS_PROTOCOL_MODE_RADIO_TX_TEST ||
		    !(handlers->supported_modes & CS_PROTOCOL_MODE_BIT(payload[0]))) {
			return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_UNSUPPORTED, CS_PROTOCOL_REASON_NONE);
		}
		host_link_config_stage_mode(&store, payload[0]);
		return HOST_LINK_RESULT_OK;

	case CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG:
	case CS_PROTOCOL_PACKET_SET_CS_REFLECTOR_CONFIG:
	case CS_PROTOCOL_PACKET_SET_RADIO_TX_TEST_CONFIG:
		return handle_config_frame(type, payload, len);

	case CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS: {
		struct host_link_result result = host_link_config_check_patterns(&store, payload);

		if (result.status == CS_PROTOCOL_STATUS_OK) {
			host_link_config_stage_patterns(&store, payload);
		}
		return result;
	}

	case CS_PROTOCOL_PACKET_SET_DEVICE_NAME: {
		struct host_link_result result = host_link_config_check_device_name(&store, payload);
		if (result.status == CS_PROTOCOL_STATUS_OK) {
			memcpy(store.staged.device_name, payload, HOST_LINK_DEVICE_NAME_PAYLOAD_SIZE);
			store.staged.has_device_name = true;
		}
		return result;
	}

	case CS_PROTOCOL_PACKET_SET_PEER_DATA: {
		struct host_link_result result = host_link_config_check_peer_data(&store, payload);

		if (result.status == CS_PROTOCOL_STATUS_OK) {
			host_link_config_stage_peer_data(&store, payload);
		}
		return result;
	}

	case CS_PROTOCOL_PACKET_SET_T_PM: {
		struct host_link_result result = host_link_config_check_t_pm(&store, payload);

		if (result.status == CS_PROTOCOL_STATUS_OK) {
			host_link_config_stage_t_pm(&store, payload);
		}
		return result;
	}

	case CS_PROTOCOL_PACKET_SET_LOG_CONFIG: {
		struct host_link_result result = host_link_config_check_log_config(&store, payload);

		if (result.status == CS_PROTOCOL_STATUS_OK) {
			host_link_config_stage_log_config(&store, payload);
		}
		return result;
	}

	case CS_PROTOCOL_PACKET_APPLY_CONFIG:
		return handle_apply();

	case CS_PROTOCOL_PACKET_GET_CONFIG:
		return handle_get_config();

	case CS_PROTOCOL_PACKET_START:
		return handle_start(payload);

	case CS_PROTOCOL_PACKET_STOP:
		return handlers->stop();

	case CS_PROTOCOL_PACKET_LINK_DISCONNECT:
		/* Allowed while RUNNING: the handler stops the operation first. */
		return handlers->link_disconnect();

	case CS_PROTOCOL_PACKET_CLOSE_SESSION:
		return HOST_LINK_RESULT_OK;

	default:
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_UNSUPPORTED, CS_PROTOCOL_REASON_NONE);
	}
}

static void handle_frame(const uint8_t *frame,
                         size_t frame_len) {
	struct cs_protocol_packet_t packet;
	size_t expected;

	int err = cs_protocol_decode(frame, frame_len, &packet);

	if (err != CS_PROTOCOL_OK) {
		APP_LOG_WRN("Received frame not decoded (%u bytes): %d", (unsigned int)frame_len, err);
		return;
	}
	APP_LOG_DBG("Command 0x%04x, %u bytes", packet.type, (unsigned int)frame_len);

	if (packet.type == CS_PROTOCOL_PACKET_CONNECT) {
		handle_connect(&packet, frame_len);
		return;
	}

	expected = command_frame_size(packet.type);
	if (expected == 0U) {
		send_response(packet.type, HOST_LINK_RESULT(CS_PROTOCOL_STATUS_UNSUPPORTED, CS_PROTOCOL_REASON_NONE));
	} else if (frame_len != expected) {
		send_response(packet.type,
		              HOST_LINK_RESULT(CS_PROTOCOL_STATUS_INVALID_FRAME, CS_PROTOCOL_REASON_NONE));
	} else if (!atomic_get(&session_active)) {
		send_response(packet.type,
		              HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_NOT_CONNECTED));
	} else {
		struct host_link_result result = handle_command(packet.type, packet.payload, packet.payload_len);

		send_response(packet.type, result);
		if (handlers->response_sent) {
			handlers->response_sent(packet.type, result);
		}
		if (packet.type == CS_PROTOCOL_PACKET_CLOSE_SESSION) {
			end_session(-ECANCELED);
		}
	}
}

static void feed(const uint8_t *data,
                 size_t len) {
	while (len > 0U) {
		size_t consumed;
		int state = cs_protocol_parser_feed(&parser, data, len, &consumed);

		if (state < 0) {
			APP_LOG_WRN("Invalid received frame skipped: %d", state);
		}
		data += consumed;
		len -= consumed;
		while (parser.state == CS_PROTOCOL_PARSER_FRAME_READY) {
			size_t frame_len = sizeof(frame_buf);

			if (cs_protocol_parser_get_frame(&parser, frame_buf, &frame_len) != CS_PROTOCOL_OK) {
				APP_LOG_WRN("Received frame not read, parser reset");
				cs_protocol_parser_reset(&parser);
				break;
			}
			handle_frame(frame_buf, frame_len);
		}
	}
}

/* Losses the host cannot see in the frame stream, reported once they happen. */
static void report_losses(uint32_t *rx_overruns) {
	struct host_link_transport_stats stats;
	atomic_val_t lost;

	host_link_transport_stats_get(&stats);
	if (!atomic_get(&session_active)) {
		/* Overruns outside a session belong to no host. */
		*rx_overruns = stats.rx_overruns;
		return;
	}
	if (stats.rx_overruns != *rx_overruns) {
		APP_LOG_WRN("Receive buffer overrun: %u bytes from the host lost",
		            (unsigned int)(stats.rx_overruns - *rx_overruns));
		*rx_overruns = stats.rx_overruns;
	}
	lost = atomic_clear(&reports_lost);
	if (lost > 0) {
		/* Subevent results are streamed from Bluetooth callbacks and never wait. */
		APP_LOG_WRN("%u reports dropped: transmit buffer full (reports wait %d ms, "
		            "subevent results none)",
		            (unsigned int)lost,
		            CONFIG_APP_HOST_LINK_REPORT_TIMEOUT_MS);
	}
}

static void host_link_thread(void *p1,
                             void *p2,
                             void *p3) {
	uint8_t chunk[64];
	bool host_ready = false;
	uint32_t rx_overruns = 0U;

	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	for (;;) {
		size_t len;

		(void)k_sem_take(&rx_ready, K_MSEC(CONFIG_APP_HOST_LINK_DTR_POLL_MS));

		if (host_link_transport_host_ready() != host_ready) {
			host_ready = !host_ready;
			APP_LOG_INF("Host port %s", host_ready ? "opened" : "closed");
			/* A lost host ends the session and interrupts a running operation. */
			cs_protocol_parser_reset(&parser);
			/* Only on close: the host sends CONNECT as soon as it opens the
			 * port, and those bytes may already wait in the receive buffer.
			 * Bytes received while closed were read and dropped below.
			 */
			if (!host_ready) {
				host_link_transport_discard();
			}
			end_session(-ENOTCONN);
		}

		while ((len = host_link_transport_read(chunk, sizeof(chunk))) > 0U) {
			if (host_ready) {
				feed(chunk, len);
			}
		}
		report_losses(&rx_overruns);
	}
}

int host_link_init(const struct host_link_handlers *table) {
	int err;

	if (handlers) {
		return -EALREADY;
	}
	if (!table || !table->client_state || !table->link_active || !table->validate_config || !table->apply ||
	    !table->start || !table->stop || !table->interrupt || !table->link_disconnect) {
		return -EINVAL;
	}

	host_link_config_store_init(&store);
	cs_protocol_parser_init(&parser, parser_buf, sizeof(parser_buf));
	err = host_link_transport_init(&rx_ready);
	if (err) {
		return err;
	}
	handlers = table;

	k_thread_create(&host_link_thread_data,
	                host_link_stack,
	                K_THREAD_STACK_SIZEOF(host_link_stack),
	                host_link_thread,
	                NULL,
	                NULL,
	                NULL,
	                CONFIG_APP_HOST_LINK_THREAD_PRIORITY,
	                0,
	                K_NO_WAIT);
	k_thread_name_set(&host_link_thread_data, "host_link");
	return 0;
}

static host_link_port_opened_t report_only_port_opened;

static void report_only_poll(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(report_only_poll_work,
                               report_only_poll);

/* Report-only DTR tracking: no host link thread polls the port. */
static void report_only_poll(struct k_work *work) {
	static bool host_ready;

	ARG_UNUSED(work);
	if (host_link_transport_host_ready() != host_ready) {
		host_ready = !host_ready;
		APP_LOG_INF("Host port %s", host_ready ? "opened" : "closed");
		/* Bytes left from the previous port session are not a whole frame. */
		host_link_transport_discard();
		if (host_ready) {
			report_only_port_opened();
		}
	}
	(void)k_work_schedule(&report_only_poll_work, K_MSEC(CONFIG_APP_HOST_LINK_DTR_POLL_MS));
}

int host_link_report_only_init(host_link_port_opened_t port_opened) {
	int err;

	if (handlers || atomic_get(&session_active)) {
		return -EALREADY;
	}
	err = host_link_transport_init(&rx_ready);
	if (err) {
		return err;
	}
	/* Report encoders use session_active as their transport-open gate. No
	 * parser, command handlers, or host-link thread is started. */
	atomic_set(&session_active, 1);
	/* The log levels are the application's: no SET_LOG_CONFIG arrives here. */
	(void)app_log_sink_register(APP_LOG_SINK_PROTOCOL, log_sink_write);
	if (port_opened && IS_ENABLED(CONFIG_APP_HOST_LINK_DTR)) {
		report_only_port_opened = port_opened;
		(void)k_work_schedule(&report_only_poll_work, K_NO_WAIT);
	}
	return 0;
}

bool host_link_session_active(void) {
	return atomic_get(&session_active);
}
