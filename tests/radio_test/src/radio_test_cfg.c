/* SPDX-License-Identifier: MIT */
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>

#include "radio_test_cfg.h"

/* ======================================================================
 * Test configuration. Edit this block, rebuild, flash.
 * ====================================================================== */

/* One of the RADIO_TEST_MODE_* roles: UNMODULATED_TX, MODULATED_TX, RX,
 * TX_SWEEP, RX_SWEEP, MODULATED_TX_DUTY_CYCLE, TX_SWEEP_WITH_SLEEP,
 * TX_SWEEP_WITH_SLEEP_MODULATED.
 */
#define TEST_MODE RADIO_TEST_MODE_UNMODULATED_TX

/* PHY. RADIO_TEST_MODE_PHY_BLE_2M matches the PHY that Channel Sounding uses. */
#define TEST_PHY RADIO_TEST_MODE_PHY_BLE_1M

/* Radio frequency index, not a BLE channel index: f = 2400 + TEST_CHANNEL MHz.
 * 1 is 2401 MHz, near the lower edge of the band.
 */
#define TEST_CHANNEL 3

/* Requested output power in dBm. Values the SoC does not support fall back
 * to 0 dBm in the driver.
 */
#define TEST_TXPOWER_DBM 0

/* One of: RADIO_TEST_MODE_PATTERN_RANDOM, RADIO_TEST_MODE_PATTERN_11110000,
 * RADIO_TEST_MODE_PATTERN_11001100, RADIO_TEST_MODE_PATTERN_00000000 or
 * RADIO_TEST_MODE_PATTERN_11111111. Ignored by the unmodulated modes.
 */
#define TEST_PATTERN RADIO_TEST_MODE_PATTERN_RANDOM

/* Packets to send or receive before stopping. 0 runs until cancelled. */
#define TEST_PACKET_COUNT 0

/* Sweep modes only: inclusive channel range and dwell time per channel. */
#define TEST_SWEEP_START_CHANNEL 0
#define TEST_SWEEP_END_CHANNEL 80
#define TEST_SWEEP_DELAY_MS 10

/* MODULATED_TX_DUTY_CYCLE only: percent of the period spent transmitting. */
#define TEST_DUTY_CYCLE 50

/* TX_SWEEP_WITH_SLEEP[_MODULATED] only: per-channel on and off times. */
#define TEST_TX_TIME_US 100
#define TEST_SLEEP_TIME_US 100

/* ====================================================================== */

BUILD_ASSERT(TEST_CHANNEL <= 80,
             "Radio channel must be within 2400-2480 MHz");
BUILD_ASSERT(TEST_SWEEP_START_CHANNEL <= TEST_SWEEP_END_CHANNEL,
             "Sweep start channel must not exceed the end channel");
BUILD_ASSERT(TEST_SWEEP_END_CHANNEL <= 80,
             "Sweep end channel must be within 2400-2480 MHz");
BUILD_ASSERT(TEST_DUTY_CYCLE > 0 && TEST_DUTY_CYCLE < 100,
             "Duty cycle must be a percentage between 1 and 99");

static void test_done_cb(void) {
	printk("Radio test finished\n");
}

int radio_test_cfg_get(struct radio_test_mode_config *config) {
	struct radio_test_mode_config settings;
	int err = radio_test_mode_config_init(&settings, TEST_MODE);

	if (err) {
		return err;
	}

	settings.phy = TEST_PHY;
	settings.channel = TEST_CHANNEL;
	settings.txpower = TEST_TXPOWER_DBM;
	settings.pattern = TEST_PATTERN;
	settings.packet_count = TEST_PACKET_COUNT;
	settings.sweep_start_channel = TEST_SWEEP_START_CHANNEL;
	settings.sweep_end_channel = TEST_SWEEP_END_CHANNEL;
	settings.sweep_delay_ms = TEST_SWEEP_DELAY_MS;
	settings.duty_cycle = TEST_DUTY_CYCLE;
	settings.tx_time_us = TEST_TX_TIME_US;
	settings.sleep_time_us = TEST_SLEEP_TIME_US;
	settings.done_cb = test_done_cb;
	*config = settings;
	return 0;
}

void radio_test_cfg_print(const struct radio_test_mode_config *config) {
	static const char *const mode_name[] = {
		[RADIO_TEST_MODE_UNMODULATED_TX] = "unmodulated TX carrier",
		[RADIO_TEST_MODE_MODULATED_TX] = "modulated TX carrier",
		[RADIO_TEST_MODE_RX] = "RX",
		[RADIO_TEST_MODE_TX_SWEEP] = "TX sweep",
		[RADIO_TEST_MODE_RX_SWEEP] = "RX sweep",
		[RADIO_TEST_MODE_MODULATED_TX_DUTY_CYCLE] = "duty-cycled modulated TX",
		[RADIO_TEST_MODE_TX_SWEEP_WITH_SLEEP] = "TX sweep with sleep",
		[RADIO_TEST_MODE_TX_SWEEP_WITH_SLEEP_MODULATED] = "modulated TX sweep with sleep",
	};

	printk("Radio test: %s\n", mode_name[config->type]);

	switch (config->type) {
	case RADIO_TEST_MODE_TX_SWEEP:
	case RADIO_TEST_MODE_RX_SWEEP:
		printk("  channels %u-%u (%u-%u MHz)\n",
		       config->sweep_start_channel,
		       config->sweep_end_channel,
		       2400 + config->sweep_start_channel,
		       2400 + config->sweep_end_channel);
		printk("  dwell    %u ms\n", config->sweep_delay_ms);
		break;
	case RADIO_TEST_MODE_TX_SWEEP_WITH_SLEEP:
	case RADIO_TEST_MODE_TX_SWEEP_WITH_SLEEP_MODULATED:
		printk("  tx %u us, sleep %u us\n",
		       config->tx_time_us,
		       config->sleep_time_us);
		break;
	default:
		printk("  channel  %u (%u MHz)\n", config->channel, 2400 + config->channel);
		break;
	}

	if (config->type != RADIO_TEST_MODE_RX && config->type != RADIO_TEST_MODE_RX_SWEEP) {
		printk("  power    %d dBm\n", config->txpower);
	}
}
