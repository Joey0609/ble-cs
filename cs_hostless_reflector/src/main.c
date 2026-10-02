/* SPDX-License-Identifier: MIT */
/* CS reflector without a host: planner configuration -> advertise -> reflector
 * role, restarted by cs_roles after a lost link. Output is log messages only.
 */
#include <errno.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>

#include <app_log/app_log.h>
#include <cs_generated_config/cs_generated_config.h>
#include <cs_roles/cs_role.h>

APP_LOG_MODULE(cs_hostless_reflector);

static struct cs_reflector_config config;

/* Base name without spaces, then the identity address as 12 uppercase hex digits. */
#define NAME_ADDR_LEN (2U * sizeof(((bt_addr_t *)0)->val))
BUILD_ASSERT(sizeof(CONFIG_BT_DEVICE_NAME) - 1U + NAME_ADDR_LEN <= CONFIG_BT_DEVICE_NAME_MAX,
             "CONFIG_BT_DEVICE_NAME leaves no room for the address");

enum status_led {
	STATUS_LED_CONNECTION,
	STATUS_LED_CS,
};

/* Board LED 1 and LED 2, with polarity supplied by devicetree. */
static const struct gpio_dt_spec status_leds[] = {
	[STATUS_LED_CONNECTION] = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios),
	[STATUS_LED_CS] = GPIO_DT_SPEC_GET(DT_ALIAS(led1), gpios),
};
static bool status_led_ready[ARRAY_SIZE(status_leds)];
static atomic_t link_connected;

static void status_leds_init(void) {
	for (size_t i = 0; i < ARRAY_SIZE(status_leds); i++) {
		int err = gpio_is_ready_dt(&status_leds[i])
		                  ? gpio_pin_configure_dt(&status_leds[i], GPIO_OUTPUT_INACTIVE)
		                  : -ENODEV;

		status_led_ready[i] = err == 0;
		if (err) {
			APP_LOG_WRN("LED %u init failed: %d", (unsigned int)i + 1, err);
		}
	}
}

static void status_led_set(enum status_led led,
                           bool on) {
	if (status_led_ready[led]) {
		int err = gpio_pin_set_dt(&status_leds[led], on);

		if (err) {
			APP_LOG_WRN("LED %u update failed: %d", (unsigned int)led + 1, err);
		}
	}
}

static void on_connected(struct bt_conn *conn,
                         uint8_t err) {
	ARG_UNUSED(conn);
	if (!err) {
		atomic_set(&link_connected, 1);
		status_led_set(STATUS_LED_CONNECTION, true);
	}
}

static void on_disconnected(struct bt_conn *conn,
                            uint8_t reason) {
	ARG_UNUSED(conn);
	ARG_UNUSED(reason);
	/* A setup failure can disconnect without a LINK_LOST role event. */
	atomic_clear(&link_connected);
	status_led_set(STATUS_LED_CONNECTION, false);
	status_led_set(STATUS_LED_CS, false);
}

BT_CONN_CB_DEFINE(status_led_callbacks) = {
	.connected = on_connected,
	.disconnected = on_disconnected,
};

static atomic_t procedures;
static atomic_t subevents;
static atomic_t steps;
static atomic_t aborted_subevents;
static atomic_t partial_subevents;

/* Application fallback procedure parameters: the TEST_* values of
 * cs_reflector_tag/src/test_cfg.c with one local antenna (A1:B1 instead of
 * A1:B2). Procedure length in 0.625 ms units, intervals in ACL events,
 * subevent length in microseconds. */
static const struct cs_config_procedure app_procedure = {
	.max_procedure_len = 10, /* 6.25 ms */
	.min_procedure_interval = 1,
	.max_procedure_interval = 10,
	.max_procedure_count = 0,
	.min_subevent_len = 6000,
	.max_subevent_len = 60000,
	.tone_antenna_config_selection = CS_CONFIG_TONE_ANTENNA_A1_B1,
	.phy = CS_CONFIG_PROCEDURE_PHY_2M,
	.tx_power_delta = CS_CONFIG_TX_POWER_DELTA_NONE,
	.preferred_peer_antenna = CS_CONFIG_PEER_ANTENNA_1,
	.snr_control_initiator = CS_CONFIG_SNR_CONTROL_NOT_USED,
	.snr_control_reflector = CS_CONFIG_SNR_CONTROL_NOT_USED,
};

static const char *const state_names[] = {
	[CS_ROLE_STATE_SCANNING] = "scanning",
	[CS_ROLE_STATE_ADVERTISING] = "advertising",
	[CS_ROLE_STATE_LINK_CONNECTING] = "connecting",
	[CS_ROLE_STATE_LINK_CONNECTED] = "connected",
	[CS_ROLE_STATE_LINK_ENCRYPTED] = "encrypted",
	[CS_ROLE_STATE_RAS_READY] = "waiting for the initiator",
	[CS_ROLE_STATE_RUNNING] = "running",
	[CS_ROLE_STATE_STOPPED] = "stopped",
	[CS_ROLE_STATE_LINK_LOST] = "link lost",
	[CS_ROLE_STATE_LINK_DISCONNECTED] = "disconnected",
	[CS_ROLE_STATE_ERROR] = "error",
};

static void on_state(enum cs_role_state state,
                     enum cs_role_failure_stage failure,
                     enum cs_role_stop_reason stop_reason,
                     uint8_t hci_status,
                     int error) {
	const char *name = state < ARRAY_SIZE(state_names) ? state_names[state] : "?";

	switch (state) {
	case CS_ROLE_STATE_RUNNING:
		status_led_set(STATUS_LED_CS, atomic_get(&link_connected) != 0);
		break;
	case CS_ROLE_STATE_STOPPED:
	case CS_ROLE_STATE_ERROR:
		status_led_set(STATUS_LED_CS, false);
		break;
	case CS_ROLE_STATE_ADVERTISING:
	case CS_ROLE_STATE_LINK_LOST:
	case CS_ROLE_STATE_LINK_DISCONNECTED:
		status_led_set(STATUS_LED_CS, false);
		break;
	default:
		break;
	}

	if (state == CS_ROLE_STATE_ERROR || state == CS_ROLE_STATE_LINK_LOST || error) {
		APP_LOG_WRN("State %s: failure %u, stop reason %u, HCI status 0x%02x, error %d",
		            name,
		            failure,
		            stop_reason,
		            hci_status,
		            error);
	} else {
		APP_LOG_INF("State %s", name);
	}
	if (state == CS_ROLE_STATE_LINK_ENCRYPTED) {
		/* Called from the event thread: the request does not wait. */
		(void)cs_role_start_reflector(&config);
	}
}

static void on_configuration(const struct cs_config_complete *record) {
	APP_LOG_INF("CS configuration %u from the initiator: status 0x%02x, mode 0x%02x, RTT type %u",
	            record->config_id,
	            record->status,
	            record->mode,
	            record->rtt_type);
}

static void on_procedure(const struct cs_procedure_enable_complete *record) {
	APP_LOG_INF("Procedures %s: status 0x%02x, interval %u, count %u",
	            record->state ? "on" : "off",
	            record->status,
	            record->procedure_interval,
	            record->procedure_count);
}

/* Bluetooth context: count only; returning nonzero skips decoding the steps. */
static int on_subevent_begin(const struct cs_subevent *header,
                             uint16_t num_tones) {
	ARG_UNUSED(num_tones);
	atomic_inc(&subevents);
	atomic_add(&steps, header->num_steps);
	if (header->subevent_done_status == BT_CONN_LE_CS_SUBEVENT_ABORTED) {
		atomic_inc(&aborted_subevents);
	}
	if (header->procedure_done_status != BT_CONN_LE_CS_PROCEDURE_INCOMPLETE) {
		atomic_inc(&procedures);
	}
	return -ECANCELED;
}

static void on_subevent_end(bool complete) {
	if (!complete) {
		atomic_inc(&partial_subevents);
	}
}

static const struct cs_role_callbacks callbacks = {
	.state = on_state,
	.configuration = on_configuration,
	.procedure = on_procedure,
	.subevent_begin = on_subevent_begin,
	.subevent_end = on_subevent_end,
};

static void log_counters(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(counters_work,
                               log_counters);

static void log_counters(struct k_work *work) {
	ARG_UNUSED(work);
	APP_LOG_INF("Procedures %ld, subevents %ld (aborted %ld, partial %ld), steps %ld",
	            (long)atomic_get(&procedures),
	            (long)atomic_get(&subevents),
	            (long)atomic_get(&aborted_subevents),
	            (long)atomic_get(&partial_subevents),
	            (long)atomic_get(&steps));
	(void)k_work_schedule(&counters_work, K_SECONDS(CONFIG_CS_HOSTLESS_STATS_INTERVAL_S));
}

/* Planner log levels, before Bluetooth starts; the app_log defaults without an export. */
static void apply_log_config(void) {
	struct app_log_config log_config;
	int err = cs_generated_config_log(&log_config);

	if (!err) {
		err = app_log_configure(&log_config);
	}
	if (err && err != -ENOENT) {
		APP_LOG_WRN("Planner log levels rejected (%d): defaults kept", err);
	}
}

static int set_unique_name(const char *base) {
	static const char hex[] = "0123456789ABCDEF";
	char name[CONFIG_BT_DEVICE_NAME_MAX + 1];
	bt_addr_le_t addr;
	size_t count = 1U;
	size_t len = 0U;

	bt_id_get(&addr, &count);
	if (count == 0U) {
		APP_LOG_ERR("No Bluetooth identity address");
		return -ENODATA;
	}
	for (; *base != '\0'; base++) {
		if (*base == ' ') {
			continue;
		}
		if (len == CONFIG_BT_DEVICE_NAME_MAX - NAME_ADDR_LEN) {
			APP_LOG_ERR("Device name too long: at most %u bytes without spaces",
			            (unsigned int)(CONFIG_BT_DEVICE_NAME_MAX - NAME_ADDR_LEN));
			return -EINVAL;
		}
		name[len++] = *base;
	}
	for (size_t i = sizeof(addr.a.val); i > 0U; i--) {
		name[len++] = hex[addr.a.val[i - 1U] >> 4];
		name[len++] = hex[addr.a.val[i - 1U] & 0x0F];
	}
	name[len] = '\0';

	int err = bt_set_name(name);

	if (err) {
		APP_LOG_ERR("Device name \"%s\" not applied: %d", name, err);
	}
	return err;
}

int main(void) {
	const char *name;
	int err;

	apply_log_config();
	status_leds_init();
	err = cs_generated_config_reflector(&config);
	if (err == -ENOENT) {
		APP_LOG_WRN("No planner configuration linked: applying hostless application defaults");
		err = cs_reflector_config_set_procedure(&config, &app_procedure);
	}
	if (err) {
		APP_LOG_ERR("Planner configuration rejected (%d): halted, no radio activity", err);
		return 0;
	} else {
		APP_LOG_INF("Planner configuration, CRC-32 0x%08x",
		            (unsigned int)cs_generated_config_crc32_reflector);
	}

	err = bt_enable(NULL);
	if (err) {
		APP_LOG_ERR("Bluetooth init failed: %d", err);
		return 0;
	}
	name = cs_generated_config_device_name();
	if (set_unique_name(name ? name : CONFIG_BT_DEVICE_NAME)) {
		return 0;
	}
	err = cs_role_init(&callbacks);
	if (!err) {
		const struct cs_role_link_params link = {
			.central = false,
			.connection = config.connection,
			.advertise_ras_uuid = true,
			.auto_restart = true,
		};

		err = cs_role_link_start(&link);
	}
	if (err) {
		APP_LOG_ERR("CS role start failed: %d", err);
		return 0;
	}
	APP_LOG_INF("Advertising as \"%s\", config ID %u", bt_get_name(), config.config_id);
	(void)k_work_schedule(&counters_work, K_SECONDS(CONFIG_CS_HOSTLESS_STATS_INTERVAL_S));
	return 0;
}
