/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <cs_utils/cs_capabilities.h>
#include <cs_utils/cs_config.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <zephyr/settings/settings.h>

#include <bluetooth/services/ras.h>

#include "cdc_out.h"
#include "cs_events.h"
#include "record_queue.h"
#include "report_printer.h"
#include "test_cfg.h"

LOG_MODULE_REGISTER(main, LOG_LEVEL_INF);

BUILD_ASSERT(CONFIG_BT_MAX_CONN == 1, "This test supports one connection");
BUILD_ASSERT(IS_ENABLED(CONFIG_BT_RAS_RRSP_AUTO_ALLOC_INSTANCE),
             "The test requires automatic RAS instance allocation");

enum test_event_type {
	TEST_CONNECTED,
	TEST_DISCONNECTED,
	TEST_RECYCLED,
};

struct test_event {
	enum test_event_type type;
	struct bt_conn *conn;
};

/* With one connection, recycling cannot occur until main releases its ref.
 * Thus at most connected, disconnected, and recycled events can be pending.
 */
K_MSGQ_DEFINE(events, sizeof(struct test_event), 4, sizeof(void *));

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

static const struct bt_data advertising_data[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR),
	BT_DATA_BYTES(BT_DATA_UUID16_ALL, BT_UUID_16_ENCODE(BT_UUID_RANGING_SERVICE_VAL)),
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME, sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

static void connected_cb(struct bt_conn *conn, uint8_t err) {
	if (err) {
		LOG_ERR("Connection failed (HCI status 0x%02x)", err);
		return;
	}
	queue_current_connection_params(conn);

	/* Transfer one owned reference to main; callbacks never release it. */
	struct test_event event = {
		.type = TEST_CONNECTED,
		.conn = bt_conn_ref(conn),
	};
	int ret = k_msgq_put(&events, &event, K_NO_WAIT);

	__ASSERT_NO_MSG(ret == 0);
	if (ret) {
		(void)bt_conn_disconnect(conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
		bt_conn_unref(event.conn);
	}
}

static void disconnected_cb(struct bt_conn *conn, uint8_t reason) {
	ARG_UNUSED(conn);
	const struct test_event event = {.type = TEST_DISCONNECTED};

	LOG_INF("Disconnected (reason 0x%02x)", reason);
	(void)record_queue_put(RECORD_CONNECTION_PARAMETERS, &(struct cs_config_connection){0},
	                       sizeof(struct cs_config_connection));
	int err = k_msgq_put(&events, &event, K_NO_WAIT);

	__ASSERT_NO_MSG(err == 0);
	ARG_UNUSED(err);
}

static void recycled_cb(void) {
	const struct test_event event = {.type = TEST_RECYCLED};
	int err = k_msgq_put(&events, &event, K_NO_WAIT);

	__ASSERT_NO_MSG(err == 0);
	ARG_UNUSED(err);
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
	.le_param_updated = le_param_updated_cb,
};

static int start_advertising(void) {
	int err = bt_le_adv_start(BT_LE_ADV_CONN_FAST_2, advertising_data,
	                          ARRAY_SIZE(advertising_data), NULL, 0);

	if (err) {
		LOG_ERR("TEST FAIL advertising (err %d)", err);
	} else {
		LOG_INF("Advertising as \"%s\"", CONFIG_BT_DEVICE_NAME);
	}
	return err;
}

/* Local settings only; the initiator creates the configuration, enables CS
 * security and starts procedures.
 */
static int apply_config(const struct cs_reflector_config *config, struct bt_conn *conn) {
	int err = cs_reflector_config_apply_connection(config, conn);

	/* Asynchronous and negotiable: a rejected request is not fatal. */
	if (err && err != -EALREADY) {
		LOG_WRN("ACL parameter request failed (err %d)", err);
	}

	err = cs_reflector_config_apply_default_settings(config, conn);
	if (err) {
		LOG_ERR("TEST FAIL CS default settings (err %d)", err);
		return err;
	}
	err = cs_reflector_config_apply_procedure(config, conn);
	if (err) {
		LOG_ERR("TEST FAIL CS procedure parameters (err %d)", err);
		return err;
	}
	LOG_INF("CS reflector settings applied; waiting for the initiator");
	return 0;
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

int main(void) {
	struct cs_reflector_config config;
	struct cs_capabilities local;
	struct bt_conn *conn = NULL;
	int err;

	LOG_INF("CS reflector test");

	err = test_cfg_get(&config);
	if (err) {
		LOG_ERR("TEST FAIL configuration rejected (err %d)", err);
		return 0;
	}
	(void)record_queue_put(RECORD_REFLECTOR_CONFIG, &config, config.size);

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

	if (start_advertising()) {
		return 0;
	}

	for (;;) {
		struct test_event event;

		if (k_msgq_get(&events, &event, K_MSEC(CONFIG_CS_REFLECTOR_TEST_STATS_INTERVAL_MS))) {
			log_stats();
			check_verdict();
			continue;
		}

		switch (event.type) {
		case TEST_CONNECTED:
			conn = event.conn;
			LOG_INF("Connected");
			if (apply_config(&config, conn)) {
				/* Recover through the normal disconnect/recycle path. */
				err = bt_conn_disconnect(conn, BT_HCI_ERR_REMOTE_USER_TERM_CONN);
				if (err) {
					LOG_ERR("Disconnect request failed (err %d)", err);
				}
			}
			break;
		case TEST_DISCONNECTED:
			if (conn) {
				bt_conn_unref(conn);
				conn = NULL;
			}
			break;
		case TEST_RECYCLED:
			/* Wait for a free connection object before advertising again. */
			if (start_advertising()) {
				return 0;
			}
			break;
		}
	}
}
