/* SPDX-License-Identifier: MIT */
/* Role state machine of cs_roles (cs_role_core.c, cs_role_initiator.c,
 * cs_role_reflector.c) against logged Bluetooth commands. The core is included
 * so the test can run the role thread's message handler and deadline check;
 * completions go through the real Bluetooth callbacks and the role queue. The
 * link layer and the event thread are replaced: the test brings the link up
 * and down, and records the events.
 */
#undef NDEBUG
#include <assert.h>
#include <stdio.h>

#include "cs_roles/cs_role_core.c"

#include "bt_stubs.h"
#include "cs_roles/cs_ras.h"

/* Events. */

struct state_event {
	enum cs_role_state state;
	enum cs_role_failure_stage failure;
	enum cs_role_stop_reason stop_reason;
	uint8_t hci_status;
	int error;
};

static struct state_event states[32];
static size_t state_count;
static size_t ras_lost_count;
static uint16_t ras_lost_counter;
static int ras_lost_error;
static size_t complete_count;
static uint16_t completed_procedures;
/* The procedures_complete event arrived before this many state events. */
static size_t complete_before_state;
static size_t streamed_subevents;
static uint8_t streamed_antenna_paths;

void cs_role_events_init(const struct cs_role_callbacks *new_callbacks) {
	ARG_UNUSED(new_callbacks);
}

bool cs_role_is_event_thread(void) { return false; }

void cs_role_notify(enum cs_role_state state, enum cs_role_failure_stage failure,
                    enum cs_role_stop_reason stop_reason, uint8_t hci_status, int error) {
	assert(state_count < ARRAY_SIZE(states));
	states[state_count++] = (struct state_event){state, failure, stop_reason, hci_status, error};
}

void cs_role_event_capabilities(const struct cs_capabilities *record) { ARG_UNUSED(record); }

void cs_role_event_configuration(const struct cs_config_complete *record) { ARG_UNUSED(record); }

void cs_role_event_procedure(const struct cs_procedure_enable_complete *record) {
	ARG_UNUSED(record);
}

void cs_role_event_fae(uint8_t hci_status, const int8_t *entries) {
	ARG_UNUSED(hci_status);
	ARG_UNUSED(entries);
}

void cs_role_event_ras_lost(uint16_t procedure_counter, int error) {
	ras_lost_count++;
	ras_lost_counter = procedure_counter;
	ras_lost_error = error;
}

void cs_role_event_procedures_complete(uint16_t procedures_completed) {
	complete_count++;
	completed_procedures = procedures_completed;
	complete_before_state = state_count;
}

void cs_role_stream_hci(const struct bt_conn_le_cs_subevent_result *result,
                        enum bt_conn_le_cs_role role) {
	ARG_UNUSED(result);
	ARG_UNUSED(role);
}

int cs_role_stream_begin(const struct cs_subevent *header, uint16_t num_tones) {
	ARG_UNUSED(num_tones);
	streamed_subevents++;
	streamed_antenna_paths = header->num_antenna_paths;
	return 0;
}

void cs_role_stream_step(const struct cs_step_header *step) { ARG_UNUSED(step); }

void cs_role_stream_end(bool complete) { ARG_UNUSED(complete); }

/* Link layer: the test sets the link state itself. */

static size_t restarts;

int cs_role_link_init(void) { return 0; }
int cs_role_link_scan(void) { return 0; }
int cs_role_link_begin(const struct cs_role_msg *msg) {
	ARG_UNUSED(msg);
	return 0;
}
void cs_role_link_disconnect_request(const struct cs_role_msg *msg) { ARG_UNUSED(msg); }
void cs_role_link_connected(const struct cs_role_msg *msg) { ARG_UNUSED(msg); }
void cs_role_link_disconnected(const struct cs_role_msg *msg) { ARG_UNUSED(msg); }
void cs_role_link_security(const struct cs_role_msg *msg) { ARG_UNUSED(msg); }
void cs_role_link_scan_match(const struct cs_role_msg *msg) { ARG_UNUSED(msg); }
void cs_role_link_timers(void) {}
k_timepoint_t cs_role_link_next_timer(void) { return sys_timepoint_calc(K_FOREVER); }
void cs_role_link_schedule_restart(void) { restarts++; }

/* Harness. */

static void reset(void) {
	memset(&cs_role, 0, sizeof(cs_role));
	memset(&cs_role_data, 0, sizeof(cs_role_data));
	atomic_ptr_clear(&cs_role_conn_ptr);
	atomic_clear(&running);
	k_msgq_purge(&role_msgs);
	cs_role_initiator_data_reset();
	memset(test_cmd_err, 0, sizeof(test_cmd_err));
	test_t_pm_us = 0U;
	test_t_pm_status = 0U;
	test_rrsp_alloc_result = 0;
	test_ras_data_cb = NULL;
	test_ras_antenna_paths_mask = 0x01U;
	test_cmds_clear();
	test_conn.refs = 0;
	test_now_ms = 0;
	test_current_thread = NULL;
	state_count = 0U;
	ras_lost_count = 0U;
	complete_count = 0U;
	streamed_subevents = 0U;
	restarts = 0U;
}

static void link_up(void) {
	cs_role.conn = bt_conn_ref(&test_conn);
	cs_role.encrypted = true;
	cs_role.link = CS_ROLE_LINK_CONNECTED;
	atomic_ptr_set(&cs_role_conn_ptr, &test_conn);
}

/* What cs_role_link_disconnected() does for the role. */
static void link_lost(void) {
	test_current_thread = &role_thread;
	cs_role_link_down();
	test_current_thread = NULL;
	bt_conn_unref(cs_role.conn);
	cs_role.conn = NULL;
	cs_role.encrypted = false;
	atomic_ptr_clear(&cs_role_conn_ptr);
}

/* Handle every queued message on the role thread, as role_loop() does. */
static void pump(void) {
	struct cs_role_msg msg;

	test_current_thread = &role_thread;
	while (k_msgq_get(&role_msgs, &msg, K_NO_WAIT) == 0) {
		handle(&msg);
	}
	test_current_thread = NULL;
}

/* Let time pass, then check the stage deadline as role_loop() does. */
static void advance(int64_t ms) {
	test_now_ms += ms;
	test_current_thread = &role_thread;
	if (cs_role.deadline_set && sys_timepoint_expired(cs_role.deadline)) {
		handle_timeout();
	}
	test_current_thread = NULL;
}

/* A request as the API posts it. Returns its result, or 1 while it is still pending. */
struct pending {
	struct k_sem done;
	int result;
};

static int request_start(struct pending *pending, struct cs_role_msg msg) {
	k_sem_init(&pending->done, 0, 1);
	pending->result = 1;
	msg.done = &pending->done;
	msg.result = &pending->result;
	assert(k_msgq_put(&role_msgs, &msg, K_NO_WAIT) == 0);
	pump();
	return pending->done.count ? pending->result : 1;
}

static int answered(struct pending *pending) {
	return pending->done.count ? pending->result : 1;
}

static int request_now(struct cs_role_msg msg) {
	struct pending pending;
	int result = request_start(&pending, msg);

	assert(result != 1);
	return result;
}

static int start_initiator(const struct cs_initiator_config *config) {
	return request_now((struct cs_role_msg){.type = CS_ROLE_MSG_START_INITIATOR,
	                                        .initiator = *config});
}

static int start_reflector(const struct cs_reflector_config *config) {
	return request_now((struct cs_role_msg){.type = CS_ROLE_MSG_START_REFLECTOR,
	                                        .reflector = *config});
}

/* Bluetooth completions, through the callbacks. */

static void remote_capabilities_antennas(uint8_t status, bool ipt, bool fae_needed, uint8_t num_antennas) {
	struct bt_conn_le_cs_capabilities caps = {
		.num_antennas_supported = num_antennas,
		.cs_ipt_reflector = ipt,
		.cs_without_fae_supported = !fae_needed,
	};

	remote_capabilities_cb(&test_conn, status, status ? NULL : &caps);
	pump();
}

static void remote_capabilities(uint8_t status, bool ipt, bool fae_needed) {
	remote_capabilities_antennas(status, ipt, fae_needed, 1U);
}

static void fae_table(uint8_t status) {
	struct bt_conn_le_cs_fae_table table = {0};

	fae_cb(&test_conn, status, &table);
	pump();
}

static void config_complete(uint8_t status, uint8_t id, bool ipt) {
	struct bt_conn_le_cs_config config = {
		.id = id,
		.rtt_type = BT_CONN_LE_CS_RTT_TYPE_AA_ONLY,
		.cs_enhancements_1 = ipt ? CS_CONFIG_ENHANCEMENTS_1_IPT : 0U,
	};

	config_cb(&test_conn, status, status ? NULL : &config);
	pump();
}

static void cs_security(uint8_t status) {
	security_cb(&test_conn, status);
	pump();
}

static void procedure_enable(uint8_t status, uint8_t id, bool enabled) {
	struct bt_conn_le_cs_procedure_enable_complete params = {
		.config_id = id,
		.state = enabled ? BT_CONN_LE_CS_PROCEDURES_ENABLED : BT_CONN_LE_CS_PROCEDURES_DISABLED,
	};

	procedure_cb(&test_conn, status, &params);
	pump();
}

static void ras_discovered(int err) {
	struct cs_role_msg msg = {.type = CS_ROLE_MSG_RAS_DISCOVERED, .err = err,
	                          .conn = bt_conn_ref(&test_conn)};

	cs_role_post(&msg);
	pump();
}

static void ras_features(uint32_t features) {
	struct cs_role_msg msg = {.type = CS_ROLE_MSG_RAS_FEATURES, .features = features,
	                          .conn = bt_conn_ref(&test_conn)};

	cs_role_post(&msg);
	pump();
}

/* The last subevent of local procedure @p counter, with (empty) step data. */
static void local_procedure_done(uint16_t counter) {
	NET_BUF_SIMPLE_DEFINE(steps, 8);
	struct bt_conn_le_cs_subevent_result result = {
		.header = {
			.config_id = 0,
			.num_antenna_paths = 1,
			.procedure_counter = counter,
			.procedure_done_status = BT_CONN_LE_CS_PROCEDURE_COMPLETE,
			.subevent_done_status = BT_CONN_LE_CS_SUBEVENT_COMPLETE,
		},
		.step_data_buf = &steps,
	};

	subevent_cb(&test_conn, &result);
}

/* STOP a running role; answered at the disable event, with no RAS data pending. */
static void stop_run(uint8_t config_id) {
	struct pending stop;

	assert(request_start(&stop, (struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 1);
	procedure_enable(0U, config_id, false);
	assert(answered(&stop) == 0 && cs_role.stage == CS_ROLE_STAGE_IDLE);
}

static const struct state_event *last_state(void) {
	assert(state_count > 0U);
	return &states[state_count - 1U];
}

static void assert_last_state(enum cs_role_state state, enum cs_role_failure_stage failure,
                              enum cs_role_stop_reason stop_reason) {
	const struct state_event *event = last_state();

	assert(event->state == state);
	assert(event->failure == failure);
	assert(event->stop_reason == stop_reason);
}

static bool state_seen(enum cs_role_state state) {
	for (size_t i = 0; i < state_count; i++) {
		if (states[i].state == state) {
			return true;
		}
	}
	return false;
}

static struct cs_initiator_config initiator_config(enum cs_config_peer_data peer_data) {
	struct cs_initiator_config config;

	assert(cs_initiator_config_get_default(&config) == 0);
	if (peer_data == CS_CONFIG_PEER_DATA_NONE) {
		config.creation.cs_enhancements_1 = CS_CONFIG_ENHANCEMENTS_1_IPT;
		assert(cs_initiator_config_set_peer_data(&config, peer_data) == 0);
	}
	return config;
}

static struct cs_reflector_config reflector_config(void) {
	struct cs_reflector_config config;

	assert(cs_reflector_config_get_default(&config) == 0);
	return config;
}

#define CMDS(...) ((const enum test_cmd[]){__VA_ARGS__})
#define ASSERT_CMDS(...)                                                               \
	assert(test_cmds_equal(CMDS(__VA_ARGS__), sizeof(CMDS(__VA_ARGS__)) / sizeof(enum test_cmd)))

/* Initiator with RAS, from START to RUNNING. */
static void run_initiator(void) {
	struct cs_initiator_config config = initiator_config(CS_CONFIG_PEER_DATA_RAS_REALTIME);

	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	remote_capabilities(0U, false, true);
	fae_table(0U);
	config_complete(0U, config.config_id, false);
	cs_security(0U);
	procedure_enable(0U, config.config_id, true);
	assert(cs_role.stage == CS_ROLE_STAGE_RUNNING && cs_role_running());
}

/* Initiator with reflector data none, from START to RUNNING. */
static void run_initiator_only(void) {
	struct cs_initiator_config config = initiator_config(CS_CONFIG_PEER_DATA_NONE);

	assert(start_initiator(&config) == 0);
	remote_capabilities(0U, true, false);
	config_complete(0U, config.config_id, true);
	cs_security(0U);
	procedure_enable(0U, config.config_id, true);
	assert(cs_role.stage == CS_ROLE_STAGE_RUNNING);
}

static void run_reflector(uint8_t peer_config_id) {
	struct cs_reflector_config config = reflector_config();

	assert(start_reflector(&config) == 0);
	remote_capabilities(0U, false, true);
	config_complete(0U, peer_config_id, false);
	procedure_enable(0U, peer_config_id, true);
	assert(cs_role.stage == CS_ROLE_STAGE_RUNNING);
}

/* Tests. */

static void test_start_rules(void) {
	struct cs_initiator_config config = initiator_config(CS_CONFIG_PEER_DATA_RAS_REALTIME);
	struct cs_reflector_config reflector = reflector_config();

	reset();
	assert(start_initiator(&config) == -ENOTCONN);
	assert(start_reflector(&reflector) == -ENOTCONN);
	assert(test_cmd_count == 0U);
	/* STOP without a link or role has nothing to do. */
	assert(request_now((struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 0);

	link_up();
	assert(start_initiator(&config) == 0);
	assert(start_initiator(&config) == -EBUSY);
	assert(start_reflector(&reflector) == -EBUSY);

	/* Not encrypted yet: the setup waits, with a deadline. */
	reset();
	link_up();
	cs_role.encrypted = false;
	assert(start_initiator(&config) == 0);
	assert(cs_role.stage == CS_ROLE_STAGE_WAIT_ENCRYPTION && test_cmd_count == 0U);
	advance(CONFIG_APP_CS_ROLES_SETUP_TIMEOUT_MS);
	assert_last_state(CS_ROLE_STATE_ERROR, CS_ROLE_FAILURE_LINK_SECURITY, CS_ROLE_STOP_NONE);
}

static void test_initiator_setup_order(void) {
	struct cs_initiator_config config = initiator_config(CS_CONFIG_PEER_DATA_RAS_REALTIME);

	reset();
	link_up();
	config.config_id = 2;
	assert(start_initiator(&config) == 0);
	ASSERT_CMDS(CMD_GATT_DM_START);
	ras_discovered(0);
	ASSERT_CMDS(CMD_GATT_DM_START, CMD_RREQ_FEATURES);
	ras_features(RAS_FEAT_REALTIME_RD);
	assert_last_state(CS_ROLE_STATE_RAS_READY, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE);
	ASSERT_CMDS(CMD_GATT_DM_START, CMD_RREQ_FEATURES, CMD_RREQ_SUBSCRIBE, CMD_DEFAULT_SETTINGS,
	            CMD_REMOTE_CAPABILITIES);
	remote_capabilities(0U, false, true);
	fae_table(0U);
	/* A configuration with another ID is not ours. */
	config_complete(0U, 1, false);
	assert(cs_role.stage == CS_ROLE_STAGE_CONFIG && !cs_role.config_created);
	config_complete(0U, 2, false);
	cs_security(0U);
	ASSERT_CMDS(CMD_GATT_DM_START, CMD_RREQ_FEATURES, CMD_RREQ_SUBSCRIBE, CMD_DEFAULT_SETTINGS,
	            CMD_REMOTE_CAPABILITIES, CMD_REMOTE_FAE, CMD_T_PM, CMD_CREATE_CONFIG,
	            CMD_CS_SECURITY, CMD_PROCEDURE_PARAMETERS, CMD_PROCEDURE_ENABLE);
	assert(test_created.id == 2 && test_created.role == BT_CONN_LE_CS_ROLE_INITIATOR);
	/* The default record prefers 10 us, and the controller is told so every time. */
	assert(test_t_pm_us == CS_CONFIG_T_PM_10_US);
	assert(!cs_role_running());
	procedure_enable(0U, 2, true);
	assert_last_state(CS_ROLE_STATE_RUNNING, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE);
	assert(cs_role_running());

	/* Without FAE the table is not read. */
	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	remote_capabilities(0U, false, false);
	assert(test_cmd_calls(CMD_REMOTE_FAE) == 0U && test_cmd_calls(CMD_CREATE_CONFIG) == 1U);

	/* The record's T_PM goes to the controller before the creation. */
	reset();
	link_up();
	assert(cs_initiator_config_set_t_pm(&config, CS_CONFIG_T_PM_40_US) == 0);
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	remote_capabilities(0U, false, false);
	assert(test_t_pm_us == CS_CONFIG_T_PM_40_US);
	assert(test_cmd_calls(CMD_T_PM) == 1U && test_cmd_calls(CMD_CREATE_CONFIG) == 1U);
	assert(cs_initiator_config_set_t_pm(&config, CS_CONFIG_T_PM_10_US) == 0);
	/* A failed FAE read is not a failed setup. */
	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	remote_capabilities(0U, false, true);
	fae_table(BT_HCI_ERR_UNSUPP_REMOTE_FEATURE);
	assert(cs_role.stage == CS_ROLE_STAGE_CONFIG);
}

static void test_restart_skips_done_steps(void) {
	struct cs_initiator_config config = initiator_config(CS_CONFIG_PEER_DATA_RAS_REALTIME);

	reset();
	link_up();
	run_initiator();
	stop_run(config.config_id);
	assert(cs_role.stage == CS_ROLE_STAGE_IDLE);

	/* START after STOP on the same link only re-enables procedures. */
	test_cmds_clear();
	assert(start_initiator(&config) == 0);
	ASSERT_CMDS(CMD_PROCEDURE_PARAMETERS, CMD_PROCEDURE_ENABLE);
	procedure_enable(0U, config.config_id, true);
	assert(cs_role.stage == CS_ROLE_STAGE_RUNNING);
	assert(test_conn.refs == 1);
}

static void test_reflector_setup_order(void) {
	struct cs_reflector_config config = reflector_config();

	reset();
	link_up();
	assert(start_reflector(&config) == 0);
	ASSERT_CMDS(CMD_RRSP_ALLOC, CMD_DEFAULT_SETTINGS, CMD_REMOTE_CAPABILITIES);
	remote_capabilities(0U, false, true);
	/* Waits for the initiator without a deadline. */
	assert_last_state(CS_ROLE_STATE_RAS_READY, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE);
	assert(cs_role.stage == CS_ROLE_STAGE_WAIT_PEER_CONFIG && !cs_role.deadline_set);
	advance(10 * CONFIG_APP_CS_ROLES_SETUP_TIMEOUT_MS);
	assert(cs_role.stage == CS_ROLE_STAGE_WAIT_PEER_CONFIG);
	/* The initiator's configuration ID is the one used. */
	config_complete(0U, 3, false);
	ASSERT_CMDS(CMD_RRSP_ALLOC, CMD_DEFAULT_SETTINGS, CMD_REMOTE_CAPABILITIES,
	            CMD_PROCEDURE_PARAMETERS);
	assert(cs_role.reflector.config_id == 3);
	assert(cs_role.stage == CS_ROLE_STAGE_ENABLE && !cs_role.deadline_set);
	procedure_enable(0U, 3, true);
	assert_last_state(CS_ROLE_STATE_RUNNING, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE);

	/* A configuration the initiator created before START is applied at START. */
	reset();
	link_up();
	config_complete(0U, 1, false);
	assert(cs_role.peer_config && cs_role.peer_config_id == 1);
	assert(start_reflector(&config) == 0);
	remote_capabilities(0U, false, true);
	ASSERT_CMDS(CMD_RRSP_ALLOC, CMD_DEFAULT_SETTINGS, CMD_REMOTE_CAPABILITIES,
	            CMD_PROCEDURE_PARAMETERS);
	assert(cs_role.stage == CS_ROLE_STAGE_ENABLE);

	/* An instance allocated automatically is not freed by the role. */
	reset();
	link_up();
	test_rrsp_alloc_result = -EALREADY;
	assert(start_reflector(&config) == 0);
	assert(!cs_role.rrsp_allocated && cs_role.stage == CS_ROLE_STAGE_REMOTE_CAPABILITIES);
	link_lost();
	assert(test_cmd_calls(CMD_RRSP_FREE) == 0U);
}

/* An initiator failure: ERROR with @p failure, the role released and the link kept. */
static void assert_failed(enum cs_role_failure_stage failure, int error) {
	assert_last_state(CS_ROLE_STATE_ERROR, failure, CS_ROLE_STOP_NONE);
	assert(last_state()->error == error);
	assert(cs_role.stage == CS_ROLE_STAGE_IDLE && !cs_role.deadline_set);
	assert(!cs_role.capabilities_read && !cs_role.config_created && !cs_role.security_enabled);
	assert(!cs_role.rreq_allocated && !cs_role.rreq_subscribed);
	assert(cs_role.conn == &test_conn && test_cmd_calls(CMD_DISCONNECT) == 0U);
}

static void test_initiator_failures(void) {
	struct cs_initiator_config config = initiator_config(CS_CONFIG_PEER_DATA_RAS_REALTIME);

	/* RAS discovery. */
	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	ras_discovered(-ENOENT);
	assert_failed(CS_ROLE_FAILURE_RAS_DISCOVERY, -ENOENT);

	/* No real-time ranging data: the discovered instance is freed. */
	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(0U);
	assert_failed(CS_ROLE_FAILURE_RAS_NO_REALTIME, -ENOTSUP);
	assert(test_cmd_calls(CMD_RREQ_FREE) == 1U);

	/* Remote capabilities. */
	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	remote_capabilities(BT_HCI_ERR_UNSUPP_REMOTE_FEATURE, false, false);
	assert_failed(CS_ROLE_FAILURE_CAPABILITIES, -EIO);
	assert(last_state()->hci_status == BT_HCI_ERR_UNSUPP_REMOTE_FEATURE);
	/* The unsubscribe and free happen before the next START repeats the setup. */
	assert(test_cmd_calls(CMD_RREQ_UNSUBSCRIBE) == 1U && test_cmd_calls(CMD_RREQ_FREE) == 1U);
	test_cmds_clear();
	assert(start_initiator(&config) == 0);
	ASSERT_CMDS(CMD_GATT_DM_START);

	/* Configuration: a refused T_PM, a refused command and a failed completion. */
	reset();
	link_up();
	test_t_pm_status = BT_HCI_ERR_INVALID_PARAM;
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	remote_capabilities(0U, false, false);
	assert_failed(CS_ROLE_FAILURE_CONFIG, -EIO);
	assert(last_state()->hci_status == BT_HCI_ERR_INVALID_PARAM);
	assert(test_cmd_calls(CMD_CREATE_CONFIG) == 0U);
	reset();
	link_up();
	test_cmd_err[CMD_CREATE_CONFIG] = -EIO;
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	remote_capabilities(0U, false, false);
	assert_failed(CS_ROLE_FAILURE_CONFIG, -EIO);
	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	remote_capabilities(0U, false, false);
	config_complete(BT_HCI_ERR_INSUFFICIENT_RESOURCES, 0, false);
	assert_failed(CS_ROLE_FAILURE_CONFIG, -EIO);

	/* CS security. */
	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	remote_capabilities(0U, false, false);
	config_complete(0U, 0, false);
	cs_security(BT_HCI_ERR_AUTH_FAIL);
	assert_failed(CS_ROLE_FAILURE_SECURITY, -EACCES);

	/* Procedure enable. */
	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	remote_capabilities(0U, false, false);
	config_complete(0U, 0, false);
	cs_security(0U);
	procedure_enable(BT_HCI_ERR_UNSPECIFIED, 0, false);
	assert_failed(CS_ROLE_FAILURE_PROCEDURE, -EIO);
	assert(!cs_role_running());

	/* With auto_restart the link is dropped so it can be brought up again. */
	reset();
	link_up();
	cs_role.params.auto_restart = true;
	assert(start_initiator(&config) == 0);
	ras_discovered(-EIO);
	assert(test_cmd_calls(CMD_DISCONNECT) == 1U && cs_role.link_failed);
}

static void test_reflector_failures(void) {
	struct cs_reflector_config config = reflector_config();

	reset();
	link_up();
	test_cmd_err[CMD_RRSP_ALLOC] = -ENOMEM;
	assert(start_reflector(&config) == 0);
	assert_last_state(CS_ROLE_STATE_ERROR, CS_ROLE_FAILURE_RAS_DISCOVERY, CS_ROLE_STOP_NONE);

	reset();
	link_up();
	assert(start_reflector(&config) == 0);
	remote_capabilities(0U, false, false);
	config_complete(BT_HCI_ERR_UNSPECIFIED, 0, false);
	assert_last_state(CS_ROLE_STATE_ERROR, CS_ROLE_FAILURE_CONFIG, CS_ROLE_STOP_NONE);
	assert(cs_role.stage == CS_ROLE_STAGE_IDLE && test_cmd_calls(CMD_RRSP_FREE) == 1U);

	/* CS security is the initiator's; only its failure reaches the reflector. */
	reset();
	link_up();
	assert(start_reflector(&config) == 0);
	remote_capabilities(0U, false, false);
	config_complete(0U, 0, false);
	cs_security(0U);
	assert(cs_role.stage == CS_ROLE_STAGE_ENABLE);
	cs_security(BT_HCI_ERR_AUTH_FAIL);
	assert_last_state(CS_ROLE_STATE_ERROR, CS_ROLE_FAILURE_SECURITY, CS_ROLE_STOP_NONE);
}

static void test_setup_timeout(void) {
	struct cs_initiator_config config = initiator_config(CS_CONFIG_PEER_DATA_RAS_REALTIME);

	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	ras_discovered(0);
	ras_features(RAS_FEAT_REALTIME_RD);
	advance(CONFIG_APP_CS_ROLES_SETUP_TIMEOUT_MS - 1);
	assert(cs_role.stage == CS_ROLE_STAGE_REMOTE_CAPABILITIES);
	advance(1);
	assert_failed(CS_ROLE_FAILURE_CAPABILITIES, -ETIMEDOUT);
	/* A completion after the timeout is ignored. */
	remote_capabilities(0U, false, false);
	assert(cs_role.stage == CS_ROLE_STAGE_IDLE && test_cmd_calls(CMD_CREATE_CONFIG) == 0U);

	/* Each stage restarts the deadline. */
	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	advance(CONFIG_APP_CS_ROLES_SETUP_TIMEOUT_MS - 1);
	ras_discovered(0);
	advance(CONFIG_APP_CS_ROLES_SETUP_TIMEOUT_MS - 1);
	assert(cs_role.stage == CS_ROLE_STAGE_RAS_FEATURES);
	advance(1);
	assert_failed(CS_ROLE_FAILURE_RAS_DISCOVERY, -ETIMEDOUT);

	/* The controller never confirms the disable. */
	reset();
	link_up();
	run_initiator();
	struct pending stop;

	assert(request_start(&stop, (struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 1);
	advance(CONFIG_APP_CS_ROLES_STOP_TIMEOUT_MS);
	assert(answered(&stop) == -ETIME);
	assert_last_state(CS_ROLE_STATE_ERROR, CS_ROLE_FAILURE_PROCEDURE, CS_ROLE_STOP_NONE);
	assert(last_state()->error == -ETIMEDOUT && !cs_role_running());
}

static void test_stop_ras(void) {
	struct pending stop;

	/* The last procedure's RAS data arrives: STOP returns 0. */
	reset();
	link_up();
	run_initiator();
	local_procedure_done(5);
	assert(request_start(&stop, (struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 1);
	assert(test_cmd_calls(CMD_PROCEDURE_DISABLE) == 1U && cs_role.stage == CS_ROLE_STAGE_STOPPING);
	procedure_enable(0U, 0, false);
	assert(cs_role.stage == CS_ROLE_STAGE_STOP_RAS && answered(&stop) == 1);
	test_ras_data_cb(&test_conn, cs_ras_ranging_counter(5), 0);
	pump();
	assert(answered(&stop) == 0 && ras_lost_count == 0U && streamed_subevents == 1U);
	assert_last_state(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_HOST);
	assert(cs_role.stage == CS_ROLE_STAGE_IDLE && !cs_role_running());

	/* It does not arrive: reported lost, STOP returns -ETIMEDOUT. */
	reset();
	link_up();
	run_initiator();
	local_procedure_done(6);
	assert(request_start(&stop, (struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 1);
	procedure_enable(0U, 0, false);
	advance(CONFIG_APP_CS_ROLES_STOP_RAS_TIMEOUT_MS - 1);
	assert(answered(&stop) == 1);
	advance(1);
	assert(answered(&stop) == -ETIMEDOUT);
	assert(ras_lost_count == 1U && ras_lost_counter == 6 && ras_lost_error == -ETIMEDOUT);
	assert_last_state(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_HOST);
	/* Data arriving after that is not streamed, and not reported again. */
	test_ras_data_cb(&test_conn, cs_ras_ranging_counter(6), 0);
	pump();
	assert(ras_lost_count == 1U && streamed_subevents == 0U);

	/* Nothing pending: STOP ends at the disable event. */
	reset();
	link_up();
	run_initiator();
	assert(request_start(&stop, (struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 1);
	procedure_enable(0U, 0, false);
	assert(answered(&stop) == 0 && cs_role.stage == CS_ROLE_STAGE_IDLE);

	/* STOP during the setup cancels it at once. */
	reset();
	link_up();
	struct cs_initiator_config config = initiator_config(CS_CONFIG_PEER_DATA_RAS_REALTIME);

	assert(start_initiator(&config) == 0);
	assert(request_now((struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 0);
	assert_last_state(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_HOST);
	assert(last_state()->error == -ECANCELED && cs_role.stage == CS_ROLE_STAGE_IDLE);
	/* Procedures a late completion enables are disabled again. */
	test_cmds_clear();
	procedure_enable(0U, 0, true);
	ASSERT_CMDS(CMD_PROCEDURE_DISABLE);

	/* An interruption stops a run, and does not cancel a setup. */
	reset();
	link_up();
	assert(start_initiator(&config) == 0);
	assert(request_now((struct cs_role_msg){.type = CS_ROLE_MSG_INTERRUPT, .error = -ENOTCONN}) == 0);
	assert(cs_role.stage == CS_ROLE_STAGE_RAS_DISCOVERY);
	reset();
	link_up();
	run_initiator();
	assert(request_start(&stop, (struct cs_role_msg){.type = CS_ROLE_MSG_INTERRUPT,
	                                                 .error = -ENOTCONN}) == 1);
	procedure_enable(0U, 0, false);
	assert(answered(&stop) == 0);
	assert_last_state(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_INTERRUPTED);
	assert(last_state()->error == -ENOTCONN);
}

static void test_late_ras_data(void) {
	/* The next procedure starts before the RAS data: reported lost once. */
	reset();
	link_up();
	run_initiator();
	local_procedure_done(7);
	local_procedure_done(8);
	assert(ras_lost_count == 1U && ras_lost_counter == 7 && ras_lost_error == -ENOBUFS);
	/* Its late data is dropped without a second report. */
	test_ras_data_cb(&test_conn, cs_ras_ranging_counter(7), 0);
	assert(ras_lost_count == 1U && streamed_subevents == 0U);
	/* The next procedure still pairs with its data. */
	test_ras_data_cb(&test_conn, cs_ras_ranging_counter(8), 0);
	assert(ras_lost_count == 1U && streamed_subevents == 1U);
	/* Data that matches no procedure is reported. */
	test_ras_data_cb(&test_conn, cs_ras_ranging_counter(20), 0);
	assert(ras_lost_count == 2U && ras_lost_counter == 20 && ras_lost_error == -ENOENT);
}

static void test_ras_without_antenna_paths(void) {
	/* Mode 1 only: the reflector reports no antenna paths, and its data is streamed. */
	reset();
	link_up();
	run_initiator();
	test_ras_antenna_paths_mask = 0x00U;
	local_procedure_done(3);
	test_ras_data_cb(&test_conn, cs_ras_ranging_counter(3), 0);
	assert(ras_lost_count == 0U && streamed_subevents == 1U && streamed_antenna_paths == 0U);
}

static void test_finite_count(void) {
	/* The controller ends the run: COMPLETE after the last RAS data. */
	reset();
	link_up();
	run_initiator();
	local_procedure_done(1);
	test_ras_data_cb(&test_conn, 1, 0);
	local_procedure_done(2);
	procedure_enable(0U, 0, false);
	assert(cs_role.stage == CS_ROLE_STAGE_STOP_RAS && complete_count == 0U);
	test_ras_data_cb(&test_conn, 2, 0);
	pump();
	assert(complete_count == 1U && completed_procedures == 2U);
	assert_last_state(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_COMPLETE);
	/* Delivered right before STOPPED. */
	assert(complete_before_state == state_count - 1U);

	/* A new run counts from zero. */
	struct cs_initiator_config config = initiator_config(CS_CONFIG_PEER_DATA_RAS_REALTIME);

	assert(start_initiator(&config) == 0);
	procedure_enable(0U, 0, true);
	local_procedure_done(3);
	procedure_enable(0U, 0, false);
	advance(CONFIG_APP_CS_ROLES_STOP_RAS_TIMEOUT_MS);
	assert(complete_count == 2U && completed_procedures == 1U);
	/* A lost last procedure is reported, and the run is still complete. */
	assert(ras_lost_count == 1U && ras_lost_error == -ETIMEDOUT);
	assert_last_state(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_COMPLETE);
	assert(last_state()->error == 0);
}

static void test_reflector_peer_disable(void) {
	reset();
	link_up();
	run_reflector(1);
	procedure_enable(0U, 1, false);
	/* STOPPED(PEER), then waiting for the initiator's next run. */
	assert(state_count >= 2U);
	assert(states[state_count - 2U].state == CS_ROLE_STATE_STOPPED);
	assert(states[state_count - 2U].stop_reason == CS_ROLE_STOP_PEER);
	assert_last_state(CS_ROLE_STATE_RAS_READY, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE);
	assert(cs_role.stage == CS_ROLE_STAGE_ENABLE && !cs_role_running());
	procedure_enable(0U, 1, true);
	assert_last_state(CS_ROLE_STATE_RUNNING, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE);

	/* A local STOP on the reflector disables and stays stopped. */
	struct pending stop;

	assert(request_start(&stop, (struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 1);
	assert(test_disable_config_id == 1);
	procedure_enable(0U, 1, false);
	assert(answered(&stop) == 0 && cs_role.stage == CS_ROLE_STAGE_IDLE);
	assert_last_state(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_HOST);
}

static void test_link_lost(void) {
	struct pending stop;

	/* During STOP: the waiter is released with -ENOTCONN. */
	reset();
	link_up();
	run_initiator();
	assert(request_start(&stop, (struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 1);
	link_lost();
	assert(answered(&stop) == -ENOTCONN);
	assert_last_state(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_LINK_LOST);
	assert(cs_role.stage == CS_ROLE_STAGE_IDLE && !cs_role_running() && !cs_role.deadline_set);

	/* While waiting for the last RAS data. */
	reset();
	link_up();
	run_initiator();
	local_procedure_done(9);
	assert(request_start(&stop, (struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 1);
	procedure_enable(0U, 0, false);
	assert(cs_role.stage == CS_ROLE_STAGE_STOP_RAS);
	link_lost();
	assert(answered(&stop) == -ENOTCONN);
	assert(!atomic_get(&cs_role_data.ras_waiter));
	/* The RAS module freed the instance with the link: no unsubscribe on a dead link. */
	assert(test_cmd_calls(CMD_RREQ_UNSUBSCRIBE) == 0U);
	assert(!cs_role.rreq_allocated && !cs_role.capabilities_read && !cs_role.config_created);

	/* During setup nothing is reported as stopped; the reflector forgets the peer's configuration. */
	reset();
	link_up();
	struct cs_reflector_config config = reflector_config();

	assert(start_reflector(&config) == 0);
	remote_capabilities(0U, false, false);
	config_complete(0U, 2, false);
	state_count = 0U;
	link_lost();
	assert(state_count == 0U && !cs_role.peer_config && cs_role.stage == CS_ROLE_STAGE_IDLE);
	assert(test_conn.refs == 0);
}

static void test_role_change(void) {
	struct cs_initiator_config initiator = initiator_config(CS_CONFIG_PEER_DATA_RAS_REALTIME);
	struct cs_reflector_config reflector = reflector_config();

	/* Reflector, then initiator: the responder instance is freed first. */
	reset();
	link_up();
	assert(start_reflector(&reflector) == 0);
	remote_capabilities(0U, false, false);
	assert(request_now((struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 0);
	test_cmds_clear();
	assert(start_initiator(&initiator) == 0);
	ASSERT_CMDS(CMD_RRSP_FREE, CMD_GATT_DM_START);
	assert(!cs_role.rrsp_allocated && !cs_role.capabilities_read);

	/* Initiator, then reflector: the requestor is unsubscribed and freed. */
	reset();
	link_up();
	run_initiator();
	stop_run(0);
	test_cmds_clear();
	assert(start_reflector(&reflector) == 0);
	ASSERT_CMDS(CMD_RREQ_UNSUBSCRIBE, CMD_RREQ_FREE, CMD_RRSP_ALLOC, CMD_DEFAULT_SETTINGS,
	            CMD_REMOTE_CAPABILITIES);
}

/* Reflector data none (implementation_plan.md §1.7). */
static void test_initiator_only(void) {
	struct cs_initiator_config config = initiator_config(CS_CONFIG_PEER_DATA_NONE);
	struct pending stop;

	/* No RAS calls and no RAS_READY. */
	reset();
	link_up();
	run_initiator_only();
	ASSERT_CMDS(CMD_DEFAULT_SETTINGS, CMD_REMOTE_CAPABILITIES, CMD_T_PM, CMD_CREATE_CONFIG,
	            CMD_CS_SECURITY, CMD_PROCEDURE_PARAMETERS, CMD_PROCEDURE_ENABLE);
	assert(!state_seen(CS_ROLE_STATE_RAS_READY));
	assert(test_created.cs_enhancements_1 & CS_CONFIG_ENHANCEMENTS_1_IPT);

	/* STOP ends at the disable event, without waiting for RAS data. */
	local_procedure_done(4);
	assert(request_start(&stop, (struct cs_role_msg){.type = CS_ROLE_MSG_STOP}) == 1);
	procedure_enable(0U, 0, false);
	assert(answered(&stop) == 0 && cs_role.stage == CS_ROLE_STAGE_IDLE);
	assert(ras_lost_count == 0U);

	/* A completed count too. */
	assert(start_initiator(&config) == 0);
	procedure_enable(0U, 0, true);
	local_procedure_done(5);
	procedure_enable(0U, 0, false);
	assert(complete_count == 1U && completed_procedures == 1U);
	assert_last_state(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_COMPLETE);

	/* The peer has no IPT: PEER_IPT at remote capabilities, and no restart. */
	reset();
	link_up();
	cs_role.params.auto_restart = true;
	assert(start_initiator(&config) == 0);
	remote_capabilities(0U, false, false);
	assert_last_state(CS_ROLE_STATE_ERROR, CS_ROLE_FAILURE_PEER_IPT, CS_ROLE_STOP_NONE);
	assert(last_state()->error == -ENOTSUP);
	assert(test_cmd_calls(CMD_CREATE_CONFIG) == 0U && test_cmd_calls(CMD_DISCONNECT) == 0U);

	/* Preferred peer antennas beyond the peer's: PEER_ANTENNA at remote capabilities, and no
	 * restart. The same antennas on a peer that has them run.
	 */
	config.procedure.preferred_peer_antenna = CS_CONFIG_PEER_ANTENNA_3;
	reset();
	link_up();
	cs_role.params.auto_restart = true;
	assert(start_initiator(&config) == 0);
	remote_capabilities_antennas(0U, true, false, 2U);
	assert_last_state(CS_ROLE_STATE_ERROR, CS_ROLE_FAILURE_PEER_ANTENNA, CS_ROLE_STOP_NONE);
	assert(last_state()->error == -ERANGE);
	assert(test_cmd_calls(CMD_CREATE_CONFIG) == 0U && test_cmd_calls(CMD_DISCONNECT) == 0U);
	assert(start_initiator(&config) == 0);
	remote_capabilities_antennas(0U, true, false, 3U);
	assert(test_cmd_calls(CMD_CREATE_CONFIG) == 1U);
	config.procedure.preferred_peer_antenna = CS_CONFIG_PEER_ANTENNA_1;

	/* The created configuration does not enable IPT: PEER_IPT at configuration complete. */
	reset();
	link_up();
	cs_role.params.auto_restart = true;
	assert(start_initiator(&config) == 0);
	remote_capabilities(0U, true, false);
	config_complete(0U, 0, false);
	assert_last_state(CS_ROLE_STATE_ERROR, CS_ROLE_FAILURE_PEER_IPT, CS_ROLE_STOP_NONE);
	assert(test_cmd_calls(CMD_CS_SECURITY) == 0U && test_cmd_calls(CMD_DISCONNECT) == 0U);

	/* Switching from a RAS run drops the subscription of the earlier run. */
	reset();
	link_up();
	run_initiator();
	stop_run(0);
	test_cmds_clear();
	assert(start_initiator(&config) == 0);
	ASSERT_CMDS(CMD_RREQ_UNSUBSCRIBE, CMD_RREQ_FREE, CMD_PROCEDURE_PARAMETERS,
	            CMD_PROCEDURE_ENABLE);
	assert(!atomic_get(&cs_role_data.ras));

	/* The API refuses none without the IPT request. */
	config.creation.cs_enhancements_1 = 0U;
	assert(cs_initiator_config_check_peer_data(&config) != 0);
}

int main(void) {
	test_start_rules();
	test_initiator_setup_order();
	test_restart_skips_done_steps();
	test_reflector_setup_order();
	test_initiator_failures();
	test_reflector_failures();
	test_setup_timeout();
	test_stop_ras();
	test_late_ras_data();
	test_ras_without_antenna_paths();
	test_finite_count();
	test_reflector_peer_disable();
	test_link_lost();
	test_role_change();
	test_initiator_only();
	printf("cs_roles state machine: OK\n");
	return 0;
}
