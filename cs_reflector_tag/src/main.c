/* SPDX-License-Identifier: MIT */
/* nRF54L15 Tag CS reflector on cs_roles: planner (or TEST_*) configuration ->
 * unique name -> advertise -> reflector role, restarted by cs_roles after a
 * lost link. Output is log messages (RTT) and LED 1: blue while connected,
 * green while CS procedures run.
 */
#include <app_log/app_log.h>
#include <cs_generated_config/cs_generated_config.h>
#include <cs_roles/cs_role.h>
#include <cs_utils/cs_capabilities.h>
#include <cs_utils/cs_config.h>
#include <errno.h>
#include <hal/nrf_gpio.h>
#include <string.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log_ctrl.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/reboot.h>

#include "test_cfg.h"

APP_LOG_MODULE(cs_reflector_tag);

BUILD_ASSERT(CONFIG_BT_MAX_CONN == 1,
             "This application supports one connection");

static struct cs_reflector_config config;
static atomic_t procedures_complete;
static atomic_t procedures_aborted;
static atomic_t two_path_subevents;
static atomic_t four_path_subevents;

/* cs_roles retries a failed advertising start every
 * CONFIG_APP_CS_ROLES_LINK_RESTART_DELAY_MS. The Tag has no button and no USB:
 * after this many consecutive failures, come back through a clean boot rather
 * than retrying a stack that no longer advertises.
 */
#define LINK_FAILURES_BEFORE_REBOOT 5U
static uint8_t link_failures;

/* Name length cap, kept from the legacy advertising payload: flags (3 bytes)
 * and the RAS UUID (4 bytes) left 24 of 31 bytes for a complete name.
 * Extended advertising now carries more, but a short name keeps the Tag
 * within CONFIG_BT_DEVICE_NAME_MAX and readable in scan output.
 */
#define ADV_NAME_MAX 22U

/* Tags built from one image get unique names: the base name without spaces,
 * followed by the identity address as 12 upper-case hex digits, most
 * significant byte first (CSTagC3A1B2D4E5F6).
 */
#define NAME_ADDR_LEN (2U * sizeof(((bt_addr_t *)0)->val))
BUILD_ASSERT(sizeof(CONFIG_BT_DEVICE_NAME) - 1U + NAME_ADDR_LEN <= ADV_NAME_MAX,
             "CONFIG_BT_DEVICE_NAME leaves no room for the address");
BUILD_ASSERT(ADV_NAME_MAX <= CONFIG_BT_DEVICE_NAME_MAX);

/* Local antennas needed by each CS_CONFIG_TONE_ANTENNA_* value (B), and the
 * antenna paths it produces (A x B).
 */
static const uint8_t tone_reflector_antennas[] = { 1, 1, 1, 1, 2, 3, 4, 2 };
static const uint8_t tone_antenna_paths[] = { 1, 2, 3, 4, 2, 3, 4, 4 };
static const char *const tone_antenna_names[] = {
	"A1:B1", "A2:B1", "A3:B1", "A4:B1", "A1:B2", "A1:B3", "A1:B4", "A2:B2",
};

enum status_led {
	STATUS_LED_CONNECTED,
	STATUS_LED_CS,
	STATUS_LED_RED,
};

/* RGB LED 1: blue P2.09, green P2.10, red P2.08, all active-low.
 * gpio_pin_set_dt() takes a logical value: true drives the pin low (on).
 * Configure red inactive too so every channel has a defined off state.
 * Blue and green lit together read as cyan.
 */
static const struct gpio_dt_spec status_leds[] = {
	[STATUS_LED_CONNECTED] = GPIO_DT_SPEC_GET(DT_NODELABEL(led1_blue), gpios),
	[STATUS_LED_CS] = GPIO_DT_SPEC_GET(DT_NODELABEL(led1_green), gpios),
	[STATUS_LED_RED] = GPIO_DT_SPEC_GET(DT_NODELABEL(led1_red), gpios),
};
static const char *const status_led_names[] = {
	[STATUS_LED_CONNECTED] = "blue",
	[STATUS_LED_CS] = "green",
	[STATUS_LED_RED] = "red",
};
static bool status_led_ready[ARRAY_SIZE(status_leds)];
static atomic_t link_connected;

static void status_led_report(enum status_led led, bool on) {
	const struct gpio_dt_spec *spec = &status_leds[led];
	uint32_t pin = NRF_GPIO_PIN_MAP(DT_PROP(DT_NODELABEL(gpio2), port), spec->pin);
	int level;

	/* Allow the pad/input sampler to settle after configuration or a write. */
	k_busy_wait(5);
	level = gpio_pin_get_raw(spec->port, spec->pin);

	/* OUT is the output latch; IN samples the pad with its input buffer
	 * enabled. Neither measurement proves that current flows through the LED.
	 */
	APP_LOG_INF("LED 1 %s P2.%02u %s: OUT=%u IN=%d PIN_CNF=0x%08x",
	            status_led_names[led], (unsigned int)spec->pin, on ? "on" : "off",
	            (unsigned int)nrf_gpio_pin_out_read(pin), level,
	            (unsigned int)NRF_P2->PIN_CNF[spec->pin]);
	if (level < 0) {
		APP_LOG_WRN("LED 1 %s readback failed: %d", status_led_names[led], level);
	} else if (level != (on ? 0 : 1)) {
		APP_LOG_WRN("LED 1 %s pad level differs from requested output", status_led_names[led]);
	}
}

static void status_leds_init(void) {
	for (size_t i = 0; i < ARRAY_SIZE(status_leds); i++) {
		int err = gpio_is_ready_dt(&status_leds[i])
		                  ? gpio_pin_configure_dt(&status_leds[i],
		                                          GPIO_OUTPUT_INACTIVE | GPIO_INPUT)
		                  : -ENODEV;

		status_led_ready[i] = err == 0;
		if (err) {
			APP_LOG_WRN("LED 1 %s init failed: %d", status_led_names[i], err);
		} else {
			status_led_report(i, false);
		}
	}
}

static void status_led_set(enum status_led led, bool on) {
	if (status_led_ready[led]) {
		int err = gpio_pin_set_dt(&status_leds[led], on);

		if (err) {
			APP_LOG_WRN("LED 1 %s update failed: %d", status_led_names[led], err);
		} else {
			status_led_report(led, on);
		}
	}
}

static void status_leds_boot_check(void) {
	/* Exercise all RGB channels before Bluetooth setup: an idle Tag would
	 * otherwise give no visible indication that the LEDs work.
	 */
	APP_LOG_INF("LED 1 boot check: blue, green, red (500 ms each)");
	for (size_t i = 0; i < ARRAY_SIZE(status_leds); i++) {
		if (!status_led_ready[i]) {
			continue;
		}
		status_led_set(i, true);
		k_msleep(500);
		status_led_set(i, false);
	}
}

static void on_connected(struct bt_conn *conn, uint8_t err) {
	ARG_UNUSED(conn);
	if (!err) {
		atomic_set(&link_connected, 1);
		status_led_set(STATUS_LED_CONNECTED, true);
	}
}

static void on_disconnected(struct bt_conn *conn, uint8_t reason) {
	ARG_UNUSED(conn);
	ARG_UNUSED(reason);
	/* A setup failure can disconnect without a LINK_LOST role event. */
	atomic_clear(&link_connected);
	status_led_set(STATUS_LED_CONNECTED, false);
	status_led_set(STATUS_LED_CS, false);
}

BT_CONN_CB_DEFINE(status_led_callbacks) = {
	.connected = on_connected,
	.disconnected = on_disconnected,
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

static void on_state(enum cs_role_state state, enum cs_role_failure_stage failure,
                     enum cs_role_stop_reason stop_reason, uint8_t hci_status, int error) {
	const char *name = state < ARRAY_SIZE(state_names) ? state_names[state] : "?";

	if (state == CS_ROLE_STATE_ERROR || state == CS_ROLE_STATE_LINK_LOST || error) {
		APP_LOG_WRN("State %s: failure %u, stop reason %u, HCI status 0x%02x, error %d", name,
		            failure, stop_reason, hci_status, error);
	} else {
		APP_LOG_INF("State %s", name);
	}
	switch (state) {
	case CS_ROLE_STATE_RUNNING:
		/* The role thread can report this after the link has gone. */
		status_led_set(STATUS_LED_CS, atomic_get(&link_connected) != 0);
		break;
	case CS_ROLE_STATE_STOPPED:
	case CS_ROLE_STATE_ERROR:
		status_led_set(STATUS_LED_CS, false);
		break;
	default:
		break;
	}
	if (state == CS_ROLE_STATE_LINK_CONNECTED) {
		link_failures = 0U;
	}
	if (state == CS_ROLE_STATE_ERROR && failure == CS_ROLE_FAILURE_CONNECT &&
	    ++link_failures >= LINK_FAILURES_BEFORE_REBOOT) {
		/* Flush the application and deferred logs first. */
		APP_LOG_ERR("Advertising failed %u times in a row: rebooting", link_failures);
		app_log_flush();
		LOG_PANIC();
		sys_reboot(SYS_REBOOT_COLD);
	}
	if (state == CS_ROLE_STATE_LINK_ENCRYPTED) {
		/* Called from the event thread: the request does not wait. */
		(void)cs_role_start_reflector(&config);
	}
}

static void on_configuration(const struct cs_config_complete *record) {
	APP_LOG_INF("CS configuration %u from the initiator: status 0x%02x, mode 0x%02x, RTT type %u",
	            record->config_id, record->status, record->mode, record->rtt_type);
}

static void on_procedure(const struct cs_procedure_enable_complete *record) {
	if (!record->state) {
		/* A disable report carries no procedure parameters. */
		APP_LOG_INF("CS config %u: procedures off, status 0x%02x", record->config_id,
		            record->status);
		return;
	}
	APP_LOG_INF("CS config %u: procedures on, status 0x%02x, negotiated antenna configuration %u",
	            record->config_id, record->status, record->tone_antenna_config_selection);
	/* The requested selection is set before advertising and never changes. */
	if (record->tone_antenna_config_selection != config.procedure.tone_antenna_config_selection) {
		APP_LOG_WRN("Peer selected antenna configuration %u, this reflector requested %u (%s)",
		            record->tone_antenna_config_selection,
		            config.procedure.tone_antenna_config_selection,
		            tone_antenna_names[config.procedure.tone_antenna_config_selection]);
	}
}

/* Bluetooth context: count only; returning nonzero skips decoding the steps. */
static int on_subevent_begin(const struct cs_subevent *header, uint16_t num_tones) {
	ARG_UNUSED(num_tones);
	if (header->num_antenna_paths == 2) {
		atomic_inc(&two_path_subevents);
	} else if (header->num_antenna_paths == 4) {
		atomic_inc(&four_path_subevents);
	}
	if (header->procedure_done_status == BT_CONN_LE_CS_PROCEDURE_COMPLETE) {
		atomic_inc(&procedures_complete);
	} else if (header->procedure_done_status == BT_CONN_LE_CS_PROCEDURE_ABORTED) {
		atomic_inc(&procedures_aborted);
	}
	return -ECANCELED;
}

static const struct cs_role_callbacks callbacks = {
	.state = on_state,
	.configuration = on_configuration,
	.procedure = on_procedure,
	.subevent_begin = on_subevent_begin,
};

static void log_counters(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(counters_work, log_counters);

static void log_counters(struct k_work *work) {
	ARG_UNUSED(work);
	APP_LOG_INF("CS procedures: %ld complete, %ld aborted; subevents: %ld two-path, %ld four-path",
	            (long)atomic_get(&procedures_complete), (long)atomic_get(&procedures_aborted),
	            (long)atomic_get(&two_path_subevents), (long)atomic_get(&four_path_subevents));
	(void)k_work_schedule(&counters_work, K_SECONDS(CONFIG_CS_REFLECTOR_TAG_STATS_INTERVAL_S));
}

static int set_unique_name(const char *base) {
	static const char hex[] = "0123456789ABCDEF";
	char name[ADV_NAME_MAX + 1];
	bt_addr_le_t addr;
	size_t count = 1U;
	size_t len = 0U;

	bt_id_get(&addr, &count);
	if (count == 0U) {
		APP_LOG_ERR("TEST FAIL no identity address");
		return -ENODATA;
	}
	for (; *base != '\0'; base++) {
		if (*base == ' ') {
			continue;
		}
		if (len == ADV_NAME_MAX - NAME_ADDR_LEN) {
			APP_LOG_ERR("TEST FAIL device name too long: at most %u bytes without spaces",
			            (unsigned int)(ADV_NAME_MAX - NAME_ADDR_LEN));
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
		APP_LOG_ERR("TEST FAIL device name \"%s\" (err %d)", name, err);
	}
	return err;
}

/* The loaded record must fit this controller, or every CS setup fails. */
static int check_antennas(const struct cs_capabilities *local,
                          const struct cs_reflector_config *config) {
	uint8_t tone = config->procedure.tone_antenna_config_selection;
	uint8_t sync = config->defaults.cs_sync_antenna_selection;

	if (tone >= ARRAY_SIZE(tone_antenna_paths)) {
		APP_LOG_ERR("Invalid tone antenna configuration %u", tone);
		return -EINVAL;
	}
	APP_LOG_INF("Requested antenna configuration %s: %u local antennas, %u paths",
	            tone_antenna_names[tone],
	            tone_reflector_antennas[tone],
	            tone_antenna_paths[tone]);
	if (tone_reflector_antennas[tone] > local->num_antennas_supported ||
	    tone_antenna_paths[tone] > local->max_antenna_paths_supported) {
		APP_LOG_ERR("Antenna configuration %s needs more than %u antennas, %u paths",
		            tone_antenna_names[tone],
		            local->num_antennas_supported,
		            local->max_antenna_paths_supported);
		return -ENOTSUP;
	}
	if (sync >= CS_CONFIG_SYNC_ANTENNA_ONE &&
	    sync <= CS_CONFIG_SYNC_ANTENNA_FOUR &&
	    sync > local->num_antennas_supported) {
		APP_LOG_ERR("CS_SYNC antenna %u exceeds %u antennas",
		            sync,
		            local->num_antennas_supported);
		return -ENOTSUP;
	}
	return 0;
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

int main(void) {
	struct cs_capabilities local;
	const char *name;
	bool generated;
	int err;

	apply_log_config();
	status_leds_init();
	status_leds_boot_check();
	APP_LOG_INF("nRF54L15 Tag CS reflector: %d antennas",
	            CONFIG_BT_CTLR_SDC_CS_NUM_ANTENNAS);

	err = test_cfg_get(&config, &generated);
	if (err) {
		APP_LOG_ERR("TEST FAIL configuration rejected (err %d)", err);
		return 0;
	}
	if (generated) {
		APP_LOG_INF("Planner configuration, CRC-32 0x%08x",
		            (unsigned int)cs_generated_config_crc32_reflector);
	} else {
		APP_LOG_INF("No planner configuration linked: TEST_* values");
	}
	static char config_text[CS_REFLECTOR_CONFIG_PRINT_SIZE];
	err = cs_reflector_config_print(config_text, sizeof(config_text), &config);
	if (err < 0) {
		APP_LOG_ERR("Configuration print failed (err %d)", err);
		return 0;
	}
	/* One message per line: the whole record is longer than a message. */
	for (const char *line = config_text; *line != '\0';) {
		const char *end = strchr(line, '\n');
		size_t len = end ? (size_t)(end - line) : strlen(line);

		APP_LOG_INF("%.*s", (int)len, line);
		line += end ? len + 1U : len;
	}

	err = bt_enable(NULL);
	if (err) {
		APP_LOG_ERR("TEST FAIL Bluetooth init (err %d)", err);
		return 0;
	}

	err = cs_capabilities_read_local(&local);
	if (err) {
		APP_LOG_ERR("TEST FAIL local CS capabilities (err %d)", err);
		return 0;
	}
	APP_LOG_INF("Controller: %u antennas, %u antenna paths",
	            local.num_antennas_supported,
	            local.max_antenna_paths_supported);
	if (local.num_antennas_supported != CONFIG_BT_CTLR_SDC_CS_NUM_ANTENNAS ||
	    local.max_antenna_paths_supported <
	            CONFIG_BT_CTLR_SDC_CS_MAX_ANTENNA_PATHS) {
		APP_LOG_ERR("Controller capabilities differ from the board configuration (%d antennas, %d paths)",
		            CONFIG_BT_CTLR_SDC_CS_NUM_ANTENNAS,
		            CONFIG_BT_CTLR_SDC_CS_MAX_ANTENNA_PATHS);
		return 0;
	}
	if (check_antennas(&local, &config)) {
		APP_LOG_ERR("TEST FAIL configuration does not fit the controller");
		return 0;
	}

	name = generated ? cs_generated_config_device_name() : NULL;
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
		APP_LOG_ERR("TEST FAIL CS role start (err %d)", err);
		return 0;
	}
	APP_LOG_INF("Advertising as \"%s\", config ID %u", bt_get_name(), config.config_id);
	(void)k_work_schedule(&counters_work, K_SECONDS(CONFIG_CS_REFLECTOR_TAG_STATS_INTERVAL_S));
	return 0;
}
