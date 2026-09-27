/* SPDX-License-Identifier: MIT */
/* Command rules of host_link.c (cs_protocol/README.md): session, frame sizes,
 * BUSY / LINK_ACTIVE, staging and apply, GET_CONFIG replay and START. The file
 * is included so the test can feed the host link thread's parser directly and
 * reset its state; the transport, app_log and the application are stubs.
 */
#undef NDEBUG
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "host_link/host_link.c"

#include "config_fixture.h"

/* Transport: every queued frame is kept for the test to read. */

#define SENT_MAX 16

struct sent_frame {
	uint16_t type;
	size_t len;
	uint8_t bytes[CONFIG_APP_HOST_LINK_MAX_FRAME_SIZE];
};

static struct sent_frame sent[SENT_MAX];
static size_t sent_count;
static int transport_send_error;

int host_link_transport_init(struct k_sem *ready) {
	ARG_UNUSED(ready);
	return 0;
}

bool host_link_transport_host_ready(void) { return true; }

size_t host_link_transport_read(uint8_t *data, size_t len) {
	ARG_UNUSED(data);
	ARG_UNUSED(len);
	return 0U;
}

void host_link_transport_discard(void) {}

int host_link_transport_send(const uint8_t *frame, size_t len, enum host_link_transport_wait wait) {
	ARG_UNUSED(wait);
	if (transport_send_error) {
		return transport_send_error;
	}
	assert(sent_count < SENT_MAX && len <= sizeof(sent[0].bytes));
	sent[sent_count].type = sys_get_le16(&frame[4]);
	sent[sent_count].len = len;
	memcpy(sent[sent_count].bytes, frame, len);
	sent_count++;
	return 0;
}

int host_link_transport_frame_begin(size_t len) {
	ARG_UNUSED(len);
	return -EAGAIN;
}

void host_link_transport_frame_write(const uint8_t *data, size_t len) {
	ARG_UNUSED(data);
	ARG_UNUSED(len);
}

int host_link_transport_frame_end(void) { return -EIO; }

void host_link_transport_stats_get(struct host_link_transport_stats *stats) {
	memset(stats, 0, sizeof(*stats));
}

/* app_log: messages are not formatted; configuration and sink calls are recorded. */

static struct app_log_config log_applied;
static int log_configure_calls;
static app_log_write_t protocol_sink;

bool app_log_enabled(uint8_t level) {
	ARG_UNUSED(level);
	return false;
}

void app_log_printf(const char *module, uint8_t level, const char *fmt, ...) {
	ARG_UNUSED(module);
	ARG_UNUSED(level);
	ARG_UNUSED(fmt);
}

int app_log_configure(const struct app_log_config *config) {
	log_applied = *config;
	log_configure_calls++;
	return 0;
}

int app_log_sink_register(enum app_log_sink sink, app_log_write_t write) {
	assert(sink == APP_LOG_SINK_PROTOCOL);
	protocol_sink = write;
	return 0;
}

/* Application handlers. */

#define SUPPORTED_MODES \
	(CS_PROTOCOL_MODE_BIT(CS_PROTOCOL_MODE_CS_INITIATOR) | CS_PROTOCOL_MODE_BIT(CS_PROTOCOL_MODE_CS_REFLECTOR))

static struct {
	uint8_t client_state;
	bool link_active;
	struct host_link_result validate_result;
	struct host_link_result apply_result;
	struct host_link_result start_result;
	struct host_link_result stop_result;
	struct host_link_result discovery_result;
	int validate_calls;
	int apply_calls;
	int start_calls;
	int stop_calls;
	int discovery_calls;
	int disconnect_calls;
	int interrupt_calls;
	int interrupt_error;
	uint32_t start_crc32;
	/* Session callbacks, with the number of frames sent at the time of the call. */
	int session_opened;
	int session_closed;
	size_t sent_at_session_opened;
	uint16_t response_sent_type;
	struct host_link_result response_sent_result;
	size_t sent_at_response_sent;
} app;

static uint8_t app_client_state(void) { return app.client_state; }

static bool app_link_active(void) { return app.link_active; }

static struct host_link_result app_validate(uint8_t mode, const uint8_t *payload, size_t len) {
	ARG_UNUSED(mode);
	ARG_UNUSED(payload);
	ARG_UNUSED(len);
	app.validate_calls++;
	return app.validate_result;
}

static struct host_link_result app_apply(const struct host_link_config_set *config) {
	ARG_UNUSED(config);
	app.apply_calls++;
	return app.apply_result;
}

static struct host_link_result app_start(const struct host_link_config_set *config) {
	app.start_calls++;
	app.start_crc32 = host_link_config_crc32(config);
	return app.start_result;
}

static struct host_link_result app_stop(void) {
	app.stop_calls++;
	return app.stop_result;
}

static void app_interrupt(int error) {
	app.interrupt_calls++;
	app.interrupt_error = error;
}

static struct host_link_result app_link_disconnect(void) {
	app.disconnect_calls++;
	return HOST_LINK_RESULT_OK;
}

static struct host_link_result app_discovery(uint16_t type, const uint8_t *payload) {
	ARG_UNUSED(type);
	ARG_UNUSED(payload);
	app.discovery_calls++;
	return app.discovery_result;
}

static void app_session_changed(bool active) {
	if (active) {
		app.session_opened++;
		app.sent_at_session_opened = sent_count;
	} else {
		app.session_closed++;
	}
}

static void app_response_sent(uint16_t request_type, struct host_link_result result) {
	app.response_sent_type = request_type;
	app.response_sent_result = result;
	app.sent_at_response_sent = sent_count;
}

static struct host_link_handlers table = {
	.supported_modes = SUPPORTED_MODES,
	.firmware_version = 0x01020304U,
	.client_state = app_client_state,
	.link_active = app_link_active,
	.validate_config = app_validate,
	.apply = app_apply,
	.start = app_start,
	.stop = app_stop,
	.interrupt = app_interrupt,
	.link_disconnect = app_link_disconnect,
	.discovery = app_discovery,
	.session_changed = app_session_changed,
	.response_sent = app_response_sent,
};

/* Boot state: no session, no configuration, the host link initialized again. */
static void reset(void) {
	handlers = NULL;
	atomic_clear(&session_active);
	atomic_clear(&reports_sent);
	atomic_clear(&reports_dropped);
	atomic_clear(&reports_lost);
	memset(&app, 0, sizeof(app));
	app.client_state = CS_PROTOCOL_CLIENT_STATE_IDLE;
	table.discovery = app_discovery;
	sent_count = 0U;
	transport_send_error = 0;
	log_configure_calls = 0;
	protocol_sink = NULL;
	assert(host_link_init(&table) == 0);
}

/* Host side. */

static void feed_frame(uint16_t type, const void *payload, size_t len) {
	uint8_t frame[CONFIG_APP_HOST_LINK_MAX_FRAME_SIZE];
	int frame_len = cs_protocol_encode(frame, sizeof(frame), type, payload, len);

	assert(frame_len > 0);
	sent_count = 0U;
	feed(frame, (size_t)frame_len);
}

static struct cs_protocol_command_response_frame_t response_at(size_t index) {
	struct cs_protocol_command_response_frame_t response;

	assert(index < sent_count);
	assert(sent[index].type == CS_PROTOCOL_PACKET_COMMAND_RESPONSE);
	assert(sent[index].len == sizeof(response));
	memcpy(&response, sent[index].bytes, sizeof(response));
	return response;
}

/* Send @p type with @p payload (the frame's payload size) and return its only response. */
static struct cs_protocol_command_response_frame_t command(uint16_t type, const void *payload) {
	static const uint8_t zeros[CONFIG_APP_HOST_LINK_MAX_FRAME_SIZE];
	size_t size = command_frame_size(type);
	struct cs_protocol_command_response_frame_t response;

	assert(size >= CS_PROTOCOL_OVERHEAD);
	feed_frame(type, payload ? payload : zeros, size - CS_PROTOCOL_OVERHEAD);
	assert(sent_count == 1U);
	response = response_at(0);
	assert(sys_le16_to_cpu(response.request_type) == type);
	return response;
}

static void expect(uint16_t type, const void *payload, uint8_t status, uint8_t reason) {
	struct cs_protocol_command_response_frame_t response = command(type, payload);

	assert(response.status == status);
	assert(response.reason == reason);
}

static struct cs_protocol_connect_response_frame_t connect_with(uint16_t version) {
	uint8_t payload[2];
	struct cs_protocol_connect_response_frame_t response;

	sys_put_le16(version, payload);
	feed_frame(CS_PROTOCOL_PACKET_CONNECT, payload, sizeof(payload));
	assert(sent_count == 1U);
	assert(sent[0].type == CS_PROTOCOL_PACKET_CONNECT_RESPONSE);
	assert(sent[0].len == sizeof(response));
	memcpy(&response, sent[0].bytes, sizeof(response));
	return response;
}

static void connect(void) {
	assert(connect_with(CS_PROTOCOL_VERSION).status == CS_PROTOCOL_STATUS_OK);
}

static void set_mode(uint8_t mode) {
	expect(CS_PROTOCOL_PACKET_SET_OPERATION_MODE, &mode, CS_PROTOCOL_STATUS_OK,
	       CS_PROTOCOL_REASON_NONE);
}

/* Stage the fixture initiator configuration and its patterns. */
static void stage_initiator(const struct cs_protocol_cs_initiator_config_frame_t *config) {
	set_mode(CS_PROTOCOL_MODE_CS_INITIATOR);
	expect(CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG, PAYLOAD(*config), CS_PROTOCOL_STATUS_OK,
	       CS_PROTOCOL_REASON_NONE);
	expect(CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS, PAYLOAD(patterns), CS_PROTOCOL_STATUS_OK,
	       CS_PROTOCOL_REASON_NONE);
}

static uint32_t apply(void) {
	struct cs_protocol_command_response_frame_t response =
		command(CS_PROTOCOL_PACKET_APPLY_CONFIG, NULL);

	assert(response.status == CS_PROTOCOL_STATUS_OK);
	return sys_le32_to_cpu(response.config_crc32);
}

static const uint8_t log_debug_info[HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE] = {
	CS_PROTOCOL_LOG_LEVEL_DEBUG, CS_PROTOCOL_LOG_LEVEL_INFO};

/* Tests. */

static void test_connect(void) {
	struct cs_protocol_connect_response_frame_t response;
	uint8_t extra[3] = {0};

	reset();
	/* A CONNECT of the wrong size or version opens no session. */
	sys_put_le16(CS_PROTOCOL_VERSION, extra);
	feed_frame(CS_PROTOCOL_PACKET_CONNECT, extra, sizeof(extra));
	assert(sent_count == 1U && sent[0].bytes[CS_PROTOCOL_HEADER_SIZE] == CS_PROTOCOL_STATUS_INVALID_FRAME);
	response = connect_with(CS_PROTOCOL_VERSION - 1U);
	assert(response.status == CS_PROTOCOL_STATUS_VERSION);
	/* The response still says what the client is, so the host can explain the refusal. */
	assert(sys_le16_to_cpu(response.protocol_version) == CS_PROTOCOL_VERSION);
	assert(!host_link_session_active() && app.session_opened == 0 && !protocol_sink);

	response = connect_with(CS_PROTOCOL_VERSION);
	assert(response.status == CS_PROTOCOL_STATUS_OK);
	assert(response.supported_modes == SUPPORTED_MODES);
	assert(sys_le32_to_cpu(response.firmware_version) == 0x01020304U);
	assert(sys_le16_to_cpu(response.max_frame_size) == CONFIG_APP_HOST_LINK_MAX_FRAME_SIZE);
	assert(!response.config_valid && response.operation_mode == CS_PROTOCOL_MODE_NONE);
	assert(response.config_crc32 == 0U);
	assert(response.client_state == CS_PROTOCOL_CLIENT_STATE_IDLE);
	assert(response.num_antennas_supported == CONFIG_APP_HOST_LINK_NUM_ANTENNAS);
	/* Opened after the response, so reports from the callback follow it. */
	assert(host_link_session_active() && protocol_sink);
	assert(app.session_opened == 1 && app.sent_at_session_opened == 1U);

	/* A second CONNECT in the session answers again without reopening it. */
	connect();
	assert(app.session_opened == 1);
}

static void test_not_connected(void) {
	uint8_t mode = CS_PROTOCOL_MODE_CS_INITIATOR;

	reset();
	expect(CS_PROTOCOL_PACKET_SET_OPERATION_MODE, &mode, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_NOT_CONNECTED);
	expect(CS_PROTOCOL_PACKET_GET_CONFIG, NULL, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_NOT_CONNECTED);
	expect(CS_PROTOCOL_PACKET_STOP, NULL, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_NOT_CONNECTED);
	assert(app.stop_calls == 0 && app.response_sent_type == 0U);

	/* The frame checks come first: the host learns about a bad frame without a session. */
	feed_frame(CS_PROTOCOL_PACKET_START, &mode, 1U);
	assert(response_at(0).status == CS_PROTOCOL_STATUS_INVALID_FRAME);
	feed_frame(0x01FFU, NULL, 0U);
	assert(response_at(0).status == CS_PROTOCOL_STATUS_UNSUPPORTED);
}

static void test_invalid_frame_and_unsupported(void) {
	uint8_t payload[4] = {CS_PROTOCOL_MODE_CS_INITIATOR};
	struct cs_protocol_command_response_frame_t response;

	reset();
	connect();
	/* One byte too many or too few. */
	feed_frame(CS_PROTOCOL_PACKET_SET_OPERATION_MODE, payload, 2U);
	response = response_at(0);
	assert(response.status == CS_PROTOCOL_STATUS_INVALID_FRAME);
	assert(response.reason == CS_PROTOCOL_REASON_NONE);
	feed_frame(CS_PROTOCOL_PACKET_START, payload, 3U);
	assert(response_at(0).status == CS_PROTOCOL_STATUS_INVALID_FRAME);
	assert(app.start_calls == 0);

	/* Unknown types, reports sent to the client and modes this build lacks. */
	feed_frame(0x01FFU, NULL, 0U);
	assert(sys_le16_to_cpu(response_at(0).request_type) == 0x01FFU);
	assert(response_at(0).status == CS_PROTOCOL_STATUS_UNSUPPORTED);
	feed_frame(CS_PROTOCOL_PACKET_CLIENT_STATE, NULL, 0U);
	assert(response_at(0).status == CS_PROTOCOL_STATUS_UNSUPPORTED);
	payload[0] = CS_PROTOCOL_MODE_RADIO_TX_TEST;
	expect(CS_PROTOCOL_PACKET_SET_OPERATION_MODE, payload, CS_PROTOCOL_STATUS_UNSUPPORTED,
	       CS_PROTOCOL_REASON_NONE);
	payload[0] = CS_PROTOCOL_MODE_RADIO_TX_TEST + 1U;
	expect(CS_PROTOCOL_PACKET_SET_OPERATION_MODE, payload, CS_PROTOCOL_STATUS_UNSUPPORTED,
	       CS_PROTOCOL_REASON_NONE);

	/* A radio build has no discovery handler. */
	table.discovery = NULL;
	expect(CS_PROTOCOL_PACKET_SCAN_START, NULL, CS_PROTOCOL_STATUS_UNSUPPORTED,
	       CS_PROTOCOL_REASON_NONE);
	table.discovery = app_discovery;
}

static void test_staging_and_apply(void) {
	struct cs_protocol_cs_reflector_config_frame_t reflector = {.gap_role = CS_PROTOCOL_GAP_PERIPHERAL};
	struct cs_protocol_command_response_frame_t response;
	uint32_t crc;

	reset();
	connect();
	/* Configuration payloads need a staged mode that matches them. */
	expect(CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG, PAYLOAD(initiator),
	       CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
	expect(CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS, PAYLOAD(patterns),
	       CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
	expect(CS_PROTOCOL_PACKET_APPLY_CONFIG, NULL, CS_PROTOCOL_STATUS_REJECTED,
	       CS_PROTOCOL_REASON_MISSING_CONFIG);
	set_mode(CS_PROTOCOL_MODE_CS_INITIATOR);
	expect(CS_PROTOCOL_PACKET_SET_CS_REFLECTOR_CONFIG, PAYLOAD(reflector),
	       CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MODE_MISMATCH);
	assert(app.validate_calls == 0);

	/* A payload the application refuses is not staged. */
	app.validate_result = HOST_LINK_RESULT_OUT_OF_RANGE(-EINVAL);
	response = command(CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG, PAYLOAD(initiator));
	assert(response.status == CS_PROTOCOL_STATUS_REJECTED);
	assert(response.reason == CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	assert((int32_t)sys_le32_to_cpu((uint32_t)response.error) == -EINVAL);
	expect(CS_PROTOCOL_PACKET_APPLY_CONFIG, NULL, CS_PROTOCOL_STATUS_REJECTED,
	       CS_PROTOCOL_REASON_MISSING_CONFIG);
	app.validate_result = HOST_LINK_RESULT_OK;

	/* A GAP central needs its patterns. */
	expect(CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG, PAYLOAD(initiator), CS_PROTOCOL_STATUS_OK,
	       CS_PROTOCOL_REASON_NONE);
	expect(CS_PROTOCOL_PACKET_APPLY_CONFIG, NULL, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_MISSING_PATTERNS);
	assert(app.apply_calls == 0);
	expect(CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS, PAYLOAD(patterns), CS_PROTOCOL_STATUS_OK,
	       CS_PROTOCOL_REASON_NONE);
	/* Responses carry the applied CRC, none yet. */
	assert(response_at(0).config_crc32 == 0U);

	crc = apply();
	assert(crc == CONFIG_CRC_VECTOR && app.apply_calls == 1);
	/* No SET_LOG_CONFIG: the default levels. */
	assert(log_configure_calls == 1);
	assert(log_applied.console_level == CS_PROTOCOL_LOG_CONSOLE_LEVEL_DEFAULT);
	assert(log_applied.protocol_level == CS_PROTOCOL_LOG_PROTOCOL_LEVEL_DEFAULT);
	/* The staging area was emptied by the apply. */
	expect(CS_PROTOCOL_PACKET_APPLY_CONFIG, NULL, CS_PROTOCOL_STATUS_REJECTED,
	       CS_PROTOCOL_REASON_MISSING_CONFIG);
	assert(sys_le32_to_cpu(response_at(0).config_crc32) == CONFIG_CRC_VECTOR);

	/* A failed apply keeps the previous configuration and levels, and the staging area. */
	stage_initiator(&initiator);
	expect(CS_PROTOCOL_PACKET_SET_LOG_CONFIG, log_debug_info, CS_PROTOCOL_STATUS_OK,
	       CS_PROTOCOL_REASON_NONE);
	app.apply_result = HOST_LINK_RESULT_FAILED(-EIO);
	response = command(CS_PROTOCOL_PACKET_APPLY_CONFIG, NULL);
	assert(response.status == CS_PROTOCOL_STATUS_FAILED);
	assert((int32_t)sys_le32_to_cpu((uint32_t)response.error) == -EIO);
	assert(sys_le32_to_cpu(response.config_crc32) == CONFIG_CRC_VECTOR);
	assert(log_configure_calls == 1);
	app.apply_result = HOST_LINK_RESULT_OK;
	assert(apply() == CONFIG_CRC_VECTOR_LOG_CONFIG);
	assert(log_configure_calls == 2);
	assert(log_applied.console_level == CS_PROTOCOL_LOG_LEVEL_DEBUG);
	assert(log_applied.protocol_level == CS_PROTOCOL_LOG_LEVEL_INFO);

	/* SET_OPERATION_MODE discards what was staged before it. */
	stage_initiator(&initiator);
	set_mode(CS_PROTOCOL_MODE_CS_REFLECTOR);
	expect(CS_PROTOCOL_PACKET_APPLY_CONFIG, NULL, CS_PROTOCOL_STATUS_REJECTED,
	       CS_PROTOCOL_REASON_MISSING_CONFIG);
}

/* Every command that changes the configuration, with a payload of its size. */
static const uint16_t config_commands[] = {
	CS_PROTOCOL_PACKET_SET_OPERATION_MODE,  CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG,
	CS_PROTOCOL_PACKET_SET_CS_REFLECTOR_CONFIG, CS_PROTOCOL_PACKET_SET_RADIO_TX_TEST_CONFIG,
	CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS, CS_PROTOCOL_PACKET_SET_DEVICE_NAME,
	CS_PROTOCOL_PACKET_SET_PEER_DATA,        CS_PROTOCOL_PACKET_SET_T_PM,
	CS_PROTOCOL_PACKET_SET_LOG_CONFIG,       CS_PROTOCOL_PACKET_APPLY_CONFIG,
};

static void test_busy_and_link_active(void) {
	uint32_t crc;

	reset();
	connect();
	stage_initiator(&initiator);
	crc = apply();
	assert(app.validate_calls == 1 && app.apply_calls == 1);

	/* RUNNING wins over an active link. */
	app.client_state = CS_PROTOCOL_CLIENT_STATE_RUNNING;
	app.link_active = true;
	for (size_t i = 0; i < ARRAY_SIZE(config_commands); i++) {
		expect(config_commands[i], NULL, CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_BUSY);
	}
	expect(CS_PROTOCOL_PACKET_SCAN_START, NULL, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_BUSY);
	assert(app.discovery_calls == 0);
	/* Reading the configuration and stopping are allowed while running. */
	feed_frame(CS_PROTOCOL_PACKET_GET_CONFIG, NULL, 0U);
	assert(response_at(sent_count - 1U).status == CS_PROTOCOL_STATUS_OK);
	expect(CS_PROTOCOL_PACKET_STOP, NULL, CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	assert(app.stop_calls == 1);
	/* So is LINK_DISCONNECT: its handler stops the run itself, no STOP first. */
	expect(CS_PROTOCOL_PACKET_LINK_DISCONNECT, NULL, CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	assert(app.disconnect_calls == 1 && app.stop_calls == 1);

	/* Not running, but a link, scan or advertising is active. */
	app.client_state = CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTED;
	for (size_t i = 0; i < ARRAY_SIZE(config_commands); i++) {
		expect(config_commands[i], NULL, CS_PROTOCOL_STATUS_BAD_STATE,
		       CS_PROTOCOL_REASON_LINK_ACTIVE);
	}
	/* None reached the application. */
	assert(app.validate_calls == 1 && app.apply_calls == 1);
	expect(CS_PROTOCOL_PACKET_LINK_DISCONNECT, NULL, CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	assert(app.disconnect_calls == 2);

	/* The applied configuration was not touched. */
	assert(sys_le32_to_cpu(response_at(0).config_crc32) == crc);
}

static void test_discovery(void) {
	struct cs_protocol_command_response_frame_t response;

	reset();
	connect();
	expect(CS_PROTOCOL_PACKET_SCAN_START, NULL, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_MISSING_CONFIG);
	stage_initiator(&initiator);
	(void)apply();
	app.discovery_result = HOST_LINK_RESULT_FAILED(-EBUSY);
	response = command(CS_PROTOCOL_PACKET_PEER_CONNECT, NULL);
	assert(response.status == CS_PROTOCOL_STATUS_FAILED);
	assert((int32_t)sys_le32_to_cpu((uint32_t)response.error) == -EBUSY);
	assert(app.discovery_calls == 1);
}

static void test_get_config_replay(void) {
	struct cs_protocol_cs_initiator_config_frame_t ipt = initiator;
	const uint8_t name[HOST_LINK_DEVICE_NAME_PAYLOAD_SIZE] = {5, 'B', 'o', 'a', 'r', 'd'};
	const uint8_t peer_data_none = CS_PROTOCOL_PEER_DATA_NONE;
	const uint8_t t_pm_40 = CS_PROTOCOL_T_PM_40_US;
	static const uint16_t order[] = {
		CS_PROTOCOL_PACKET_SET_OPERATION_MODE, CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG,
		CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS, CS_PROTOCOL_PACKET_SET_DEVICE_NAME,
		CS_PROTOCOL_PACKET_SET_PEER_DATA, CS_PROTOCOL_PACKET_SET_T_PM,
		CS_PROTOCOL_PACKET_SET_LOG_CONFIG,
	};
	struct sent_frame replay[ARRAY_SIZE(order)];
	uint32_t crc;

	reset();
	connect();
	expect(CS_PROTOCOL_PACKET_GET_CONFIG, NULL, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_MISSING_CONFIG);

	ipt.creation_cs_enhancements_1 = CS_PROTOCOL_CONFIG_ENHANCEMENTS_1_IPT;
	set_mode(CS_PROTOCOL_MODE_CS_INITIATOR);
	/* The name is staged after the configuration (cs_protocol/README.md). */
	expect(CS_PROTOCOL_PACKET_SET_DEVICE_NAME, name, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_MISSING_CONFIG);
	expect(CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG, PAYLOAD(ipt), CS_PROTOCOL_STATUS_OK,
	       CS_PROTOCOL_REASON_NONE);
	/* The optional frames in the reverse of the CRC order. */
	expect(CS_PROTOCOL_PACKET_SET_LOG_CONFIG, log_debug_info, CS_PROTOCOL_STATUS_OK,
	       CS_PROTOCOL_REASON_NONE);
	expect(CS_PROTOCOL_PACKET_SET_T_PM, &t_pm_40, CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	expect(CS_PROTOCOL_PACKET_SET_PEER_DATA, &peer_data_none, CS_PROTOCOL_STATUS_OK,
	       CS_PROTOCOL_REASON_NONE);
	expect(CS_PROTOCOL_PACKET_SET_DEVICE_NAME, name, CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	expect(CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS, PAYLOAD(patterns), CS_PROTOCOL_STATUS_OK,
	       CS_PROTOCOL_REASON_NONE);
	crc = apply();

	/* Replayed in CRC order, then the response. */
	feed_frame(CS_PROTOCOL_PACKET_GET_CONFIG, NULL, 0U);
	assert(sent_count == ARRAY_SIZE(order) + 1U);
	for (size_t i = 0; i < ARRAY_SIZE(order); i++) {
		assert(sent[i].type == order[i]);
		assert(sent[i].len == command_frame_size(order[i]));
	}
	assert(response_at(ARRAY_SIZE(order)).status == CS_PROTOCOL_STATUS_OK);
	assert(sys_le32_to_cpu(response_at(ARRAY_SIZE(order)).config_crc32) == crc);
	memcpy(replay, sent, sizeof(replay));

	/* The replayed frames, sent back as they are, give the same configuration. */
	reset();
	connect();
	for (size_t i = 0; i < ARRAY_SIZE(order); i++) {
		sent_count = 0U;
		feed(replay[i].bytes, replay[i].len);
		assert(response_at(0).status == CS_PROTOCOL_STATUS_OK);
	}
	assert(apply() == crc);

	/* Optional frames are replayed only when part of the configuration. */
	stage_initiator(&initiator);
	(void)apply();
	feed_frame(CS_PROTOCOL_PACKET_GET_CONFIG, NULL, 0U);
	assert(sent_count == 4U);
	assert(sent[2].type == CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS);

	/* A replay frame the transport cannot queue fails the command. */
	transport_send_error = -EAGAIN;
	sent_count = 0U;
	assert(handle_get_config().status == CS_PROTOCOL_STATUS_FAILED);
	transport_send_error = 0;
}

static void test_start(void) {
	uint8_t crc_payload[4];
	struct cs_protocol_command_response_frame_t response;
	uint32_t crc;

	reset();
	connect();
	sys_put_le32(CONFIG_CRC_VECTOR, crc_payload);
	expect(CS_PROTOCOL_PACKET_START, crc_payload, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_MISSING_CONFIG);
	stage_initiator(&initiator);
	crc = apply();

	/* The host must confirm the applied configuration. */
	sys_put_le32(crc ^ 1U, crc_payload);
	response = command(CS_PROTOCOL_PACKET_START, crc_payload);
	assert(response.status == CS_PROTOCOL_STATUS_CONFIG_MISMATCH);
	assert(response.reason == CS_PROTOCOL_REASON_NONE);
	assert(sys_le32_to_cpu(response.config_crc32) == crc);
	assert(app.start_calls == 0);

	sys_put_le32(crc, crc_payload);
	app.client_state = CS_PROTOCOL_CLIENT_STATE_RUNNING;
	expect(CS_PROTOCOL_PACKET_START, crc_payload, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_BUSY);
	assert(app.start_calls == 0);

	/* START is allowed with a link: it is not a configuration change. */
	app.client_state = CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTED;
	app.link_active = true;
	expect(CS_PROTOCOL_PACKET_START, crc_payload, CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	assert(app.start_calls == 1 && app.start_crc32 == crc);
	/* Reports the application sends from response_sent follow the response. */
	assert(app.response_sent_type == CS_PROTOCOL_PACKET_START);
	assert(app.response_sent_result.status == CS_PROTOCOL_STATUS_OK && app.sent_at_response_sent == 1U);

	app.start_result = HOST_LINK_RESULT_FAILED(-ENOTCONN);
	response = command(CS_PROTOCOL_PACKET_START, crc_payload);
	assert(response.status == CS_PROTOCOL_STATUS_FAILED);
	assert((int32_t)sys_le32_to_cpu((uint32_t)response.error) == -ENOTCONN);
	assert(app.response_sent_result.status == CS_PROTOCOL_STATUS_FAILED);
}

static void test_session_end(void) {
	struct cs_protocol_connect_response_frame_t response;
	uint32_t crc;

	reset();
	connect();
	stage_initiator(&initiator);
	crc = apply();

	/* CLOSE_SESSION: answered, then the session ends and a run is interrupted. */
	set_mode(CS_PROTOCOL_MODE_CS_INITIATOR);
	app.client_state = CS_PROTOCOL_CLIENT_STATE_RUNNING;
	expect(CS_PROTOCOL_PACKET_CLOSE_SESSION, NULL, CS_PROTOCOL_STATUS_OK, CS_PROTOCOL_REASON_NONE);
	assert(!host_link_session_active() && !protocol_sink);
	assert(app.interrupt_calls == 1 && app.interrupt_error == -ECANCELED);
	assert(app.session_closed == 1);
	expect(CS_PROTOCOL_PACKET_STOP, NULL, CS_PROTOCOL_STATUS_BAD_STATE,
	       CS_PROTOCOL_REASON_NOT_CONNECTED);

	/* The applied configuration outlives the session; the staged mode does not. */
	app.client_state = CS_PROTOCOL_CLIENT_STATE_CONFIGURED;
	response = connect_with(CS_PROTOCOL_VERSION);
	assert(response.config_valid && response.operation_mode == CS_PROTOCOL_MODE_CS_INITIATOR);
	assert(sys_le32_to_cpu(response.config_crc32) == crc);
	assert(response.client_state == CS_PROTOCOL_CLIENT_STATE_CONFIGURED);
	expect(CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG, PAYLOAD(initiator),
	       CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);

	/* Host port lost while not running: the session ends without an interruption. */
	end_session(-ENOTCONN);
	assert(!host_link_session_active() && app.session_closed == 2 && app.interrupt_calls == 1);
	/* Ending a session that is not open does nothing. */
	end_session(-ENOTCONN);
	assert(app.session_closed == 2);

	/* Host port lost while running. */
	connect();
	app.client_state = CS_PROTOCOL_CLIENT_STATE_RUNNING;
	end_session(-ENOTCONN);
	assert(app.interrupt_calls == 2 && app.interrupt_error == -ENOTCONN);
	assert(app.stop_calls == 0);
}

static void test_session_end_stops(void) {
	/* Discovery, a connection attempt and a CS setup (LINK_CONNECTED, RAS_READY). */
	static const uint8_t busy[] = {
		CS_PROTOCOL_CLIENT_STATE_SCANNING,       CS_PROTOCOL_CLIENT_STATE_ADVERTISING,
		CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTING, CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTED,
		CS_PROTOCOL_CLIENT_STATE_RAS_READY,
	};
	static const uint8_t idle[] = {
		CS_PROTOCOL_CLIENT_STATE_IDLE,    CS_PROTOCOL_CLIENT_STATE_CONFIGURED,
		CS_PROTOCOL_CLIENT_STATE_STOPPED, CS_PROTOCOL_CLIENT_STATE_LINK_LOST,
		CS_PROTOCOL_CLIENT_STATE_LINK_DISCONNECTED, CS_PROTOCOL_CLIENT_STATE_ERROR,
	};

	reset();
	/* CLOSE_SESSION is answered first; the stop runs with the session closed. */
	for (size_t i = 0; i < ARRAY_SIZE(busy); i++) {
		connect();
		app.client_state = busy[i];
		expect(CS_PROTOCOL_PACKET_CLOSE_SESSION, NULL, CS_PROTOCOL_STATUS_OK,
		       CS_PROTOCOL_REASON_NONE);
		assert(app.stop_calls == (int)i + 1 && app.interrupt_calls == 0);
		assert(app.session_closed == (int)i + 1);
	}
	/* Host port lost while advertising; a failed stop still ends the session. */
	connect();
	app.client_state = CS_PROTOCOL_CLIENT_STATE_ADVERTISING;
	app.stop_result = HOST_LINK_RESULT_FAILED(-EIO);
	end_session(-ENOTCONN);
	assert(app.stop_calls == (int)ARRAY_SIZE(busy) + 1 && !host_link_session_active());
	app.stop_result = HOST_LINK_RESULT_OK;

	/* Nothing in progress: neither stopped nor interrupted. */
	for (size_t i = 0; i < ARRAY_SIZE(idle); i++) {
		connect();
		app.client_state = idle[i];
		expect(CS_PROTOCOL_PACKET_CLOSE_SESSION, NULL, CS_PROTOCOL_STATUS_OK,
		       CS_PROTOCOL_REASON_NONE);
	}
	assert(app.stop_calls == (int)ARRAY_SIZE(busy) + 1 && app.interrupt_calls == 0);
}

static void test_reports(void) {
	const uint8_t frame[CS_PROTOCOL_OVERHEAD] = {0};
	uint32_t sent_reports;
	uint32_t dropped;

	reset();
	/* Without a session, reports are dropped and not announced. */
	assert(host_link_send_report(frame, sizeof(frame)) == -ENOTCONN);
	host_link_report_counters(&sent_reports, &dropped);
	assert(sent_reports == 0U && dropped == 1U && atomic_get(&reports_lost) == 0);

	connect();
	assert(host_link_send_report(frame, sizeof(frame)) == 0);
	/* No room: counted and announced once by the host link thread. */
	transport_send_error = -EAGAIN;
	assert(host_link_send_report(frame, sizeof(frame)) == -EAGAIN);
	host_link_report_counters(&sent_reports, &dropped);
	assert(sent_reports == 1U && dropped == 2U && atomic_get(&reports_lost) == 1);
	/* A lost LOG_MESSAGE is counted but not announced: the announcement is a log message. */
	protocol_sink(APP_LOG_LEVEL_WRN, 0U, "x", 1U);
	host_link_report_counters(&sent_reports, &dropped);
	assert(dropped == 3U && atomic_get(&reports_lost) == 1);
	transport_send_error = 0;

	/* Streamed reports never wait: a failed begin counts as a lost report. */
	assert(host_link_report_sink.begin(NULL, 100U) == -EAGAIN);
	assert(atomic_get(&reports_lost) == 2);
	/* A new session starts without losses to announce. */
	end_session(-ENOTCONN);
	connect();
	assert(atomic_get(&reports_lost) == 0);
}

int main(void) {
	test_connect();
	test_not_connected();
	test_invalid_frame_and_unsupported();
	test_staging_and_apply();
	test_busy_and_link_active();
	test_discovery();
	test_get_config_replay();
	test_start();
	test_session_end();
	test_session_end_stops();
	test_reports();
	printf("host_link command rules: OK\n");
	return 0;
}
