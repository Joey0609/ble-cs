/* SPDX-License-Identifier: MIT */
/* Radio test build: host link handlers -> radio_test_utils. */
#include <app_version.h>
#include <errno.h>
#include <zephyr/kernel.h>

#include "app_log/app_log.h"
#include "client_state.h"
#include "host_link/host_link_config.h"
#include "host_link/host_link_reports.h"
#include "radio_test_utils/radio_test_mode.h"
#include "session.h"

APP_LOG_MODULE(radio_session);

/* The radio test driver drives RADIO, TIMER10 and EGU10 directly. MPSL claims
 * the same peripherals on the nRF54L series, so this build has no Bluetooth.
 */
BUILD_ASSERT(!IS_ENABLED(CONFIG_BT),
             "The radio test driver cannot share the radio with the Bluetooth stack");

/* The applied test ends on its own after a finite packet count. */
static bool finite_test;
/* The applied test receives (RX or RX sweep) and reports RADIO_TEST_STATS. */
static bool rx_test;

/* RADIO_TEST_STATS: a baseline after the START response, periodic reports,
 * and a final report before the test's STOPPED state. stats_active is set
 * from START until the final report, so a STOP racing a completion reports
 * once.
 */
static K_MUTEX_DEFINE(stats_lock);
static bool stats_active;

static void stats_work_handler(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(stats_work, stats_work_handler);

/* Called with stats_lock held. */
static void stats_send(void) {
	struct radio_test_mode_rx_stats stats;

	if (radio_test_mode_rx_stats_get(&stats) == 0) {
		(void)host_link_report_radio_test_stats(stats.packets_received, stats.crc_errors,
		                                        stats.rssi_dbm, stats.channel);
	}
}

static void stats_work_handler(struct k_work *work) {
	ARG_UNUSED(work);
	k_mutex_lock(&stats_lock, K_FOREVER);
	if (stats_active) {
		stats_send();
		(void)k_work_schedule(&stats_work, K_MSEC(CONFIG_CS_CLIENT_RADIO_TEST_STATS_INTERVAL_MS));
	}
	k_mutex_unlock(&stats_lock);
}

/* Final report of an RX test; call once the radio has stopped. */
static void stats_finish(void) {
	k_mutex_lock(&stats_lock, K_FOREVER);
	if (stats_active) {
		stats_active = false;
		stats_send();
	}
	k_mutex_unlock(&stats_lock);
	/* A handler already running finds stats_active cleared. */
	(void)k_work_cancel_delayable(&stats_work);
}

static void test_complete_work_handler(struct k_work *work) {
	ARG_UNUSED(work);
	stats_finish();
	/* A STOP that raced the completion has already reported STOPPED. */
	if (client_state_change(CS_PROTOCOL_CLIENT_STATE_RUNNING, CS_PROTOCOL_CLIENT_STATE_STOPPED,
	                        CS_PROTOCOL_REASON_TEST_COMPLETE, 0)) {
		APP_LOG_INF("Radio test complete");
	}
}

static K_WORK_DEFINE(test_complete_work, test_complete_work_handler);

/* Interrupt or system work queue context: hand over to a thread. */
static void test_done(void) {
	(void)k_work_submit(&test_complete_work);
}

static uint8_t get_state(void) {
	return client_state_get();
}

static bool link_active(void) {
	return false;
}

static struct host_link_result validate_config(uint8_t mode, const uint8_t *payload, size_t len) {
	struct radio_test_mode_config config;
	int err;

	if (mode != CS_PROTOCOL_MODE_RADIO_TX_TEST) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_UNSUPPORTED, CS_PROTOCOL_REASON_NONE);
	}
	err = host_link_config_to_radio_test(payload, len, &config);
	return err ? HOST_LINK_RESULT_OUT_OF_RANGE(err) : HOST_LINK_RESULT_OK;
}

static struct host_link_result apply(const struct host_link_config_set *set) {
	struct radio_test_mode_config config;
	int err;

	err = host_link_config_to_radio_test(set->config, set->config_len, &config);
	if (err) {
		return HOST_LINK_RESULT_OUT_OF_RANGE(err);
	}
	config.done_cb = test_done;
	err = radio_test_mode_apply(&config);
	if (err) {
		return HOST_LINK_RESULT_FAILED(err);
	}
	finite_test = config.packet_count != 0U;
	rx_test = config.type == RADIO_TEST_MODE_RX || config.type == RADIO_TEST_MODE_RX_SWEEP;
	client_state_set_mode(set->mode);
	client_state_set(CS_PROTOCOL_CLIENT_STATE_CONFIGURED, CS_PROTOCOL_REASON_NONE, 0U, 0);
	return HOST_LINK_RESULT_OK;
}

static struct host_link_result start(const struct host_link_config_set *set) {
	int err;

	ARG_UNUSED(set);
	err = radio_test_mode_start();
	if (err) {
		return HOST_LINK_RESULT_FAILED(err);
	}
	k_mutex_lock(&stats_lock, K_FOREVER);
	stats_active = rx_test;
	k_mutex_unlock(&stats_lock);
	client_state_set(CS_PROTOCOL_CLIENT_STATE_RUNNING, CS_PROTOCOL_REASON_NONE, 0U, 0);
	return HOST_LINK_RESULT_OK;
}

/* The RX statistics baseline follows the START response. */
static void response_sent(uint16_t request_type, struct host_link_result result) {
	if (request_type != CS_PROTOCOL_PACKET_START || result.status != CS_PROTOCOL_STATUS_OK) {
		return;
	}
	k_mutex_lock(&stats_lock, K_FOREVER);
	/* Not active when a short finite test already completed. */
	if (stats_active) {
		stats_send();
		(void)k_work_schedule(&stats_work, K_MSEC(CONFIG_CS_CLIENT_RADIO_TEST_STATS_INTERVAL_MS));
	}
	k_mutex_unlock(&stats_lock);
}

/* Stop the test and report why it ended. @p error is the interruption, or 0
 * for a host STOP: a continuous test only ends by STOP, so only a finite test
 * that is still running counts as interrupted (-ECANCELED). A failed stop
 * leaves the test in an unknown state and is reported as ERROR.
 */
static int stop_test(int error) {
	/* A completion racing this check is reported as interrupted; its work item
	 * then finds the state already STOPPED.
	 */
	bool cut_short = finite_test && radio_test_mode_is_running();
	int err = radio_test_mode_stop();

	stats_finish();
	if (err) {
		(void)client_state_change(CS_PROTOCOL_CLIENT_STATE_RUNNING, CS_PROTOCOL_CLIENT_STATE_ERROR,
		                          CS_PROTOCOL_REASON_INTERRUPTED, err);
		return err;
	}
	if (error == 0 && cut_short) {
		error = -ECANCELED;
	}
	(void)client_state_change(CS_PROTOCOL_CLIENT_STATE_RUNNING, CS_PROTOCOL_CLIENT_STATE_STOPPED,
	                          error ? CS_PROTOCOL_REASON_INTERRUPTED : CS_PROTOCOL_REASON_NONE,
	                          error);
	return 0;
}

static struct host_link_result stop(void) {
	int err = stop_test(0);

	return err ? HOST_LINK_RESULT_FAILED(err) : HOST_LINK_RESULT_OK;
}

static void interrupt(int error) {
	(void)stop_test(error);
}

/* No Bluetooth link in this build. A running test is left to STOP or
 * CLOSE_SESSION; the host sends no LINK_DISCONNECT in radio test mode.
 */
static struct host_link_result link_disconnect(void) {
	return HOST_LINK_RESULT_OK;
}

/* The applied test configuration spans host sessions; interrupt() has already
 * stopped a running test.
 */
static void session_changed(bool active) {
	client_state_session_changed(active);
}

static const struct host_link_handlers handlers = {
	.supported_modes = CS_PROTOCOL_MODE_BIT(CS_PROTOCOL_MODE_RADIO_TX_TEST),
	.firmware_version = APPVERSION,
	.client_state = get_state,
	.link_active = link_active,
	.validate_config = validate_config,
	.apply = apply,
	.start = start,
	.stop = stop,
	.interrupt = interrupt,
	.link_disconnect = link_disconnect,
	.session_changed = session_changed,
	.response_sent = response_sent,
};

int session_init(void) {
	return radio_test_mode_init();
}

const struct host_link_handlers *session_handlers(void) {
	return &handlers;
}

const char *session_build_name(void) {
	return "radio test";
}
