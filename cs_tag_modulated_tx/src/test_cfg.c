/* SPDX-License-Identifier: MIT */
#include <zephyr/sys/printk.h>
#include <zephyr/sys/util.h>

#include "test_cfg.h"

/* Rebuild after choosing one of the four deterministic packet patterns. */
#define TEST_PATTERN RADIO_TEST_MODE_PATTERN_11001100
// RADIO_TEST_MODE_PATTERN_11110000

/* BLE radio frequency index: 0-80 maps to 2400-2480 MHz. */
#define TEST_CHANNEL 3
#define TEST_PHY RADIO_TEST_MODE_PHY_BLE_1M
#define TEST_TXPOWER_DBM 0
/* Zero sends indefinitely; set a finite number to stop after that many packets.
 */
#define TEST_PACKET_COUNT 0

BUILD_ASSERT(TEST_PATTERN == RADIO_TEST_MODE_PATTERN_11110000 ||
                     TEST_PATTERN == RADIO_TEST_MODE_PATTERN_11001100 ||
                     TEST_PATTERN == RADIO_TEST_MODE_PATTERN_00000000 ||
                     TEST_PATTERN == RADIO_TEST_MODE_PATTERN_11111111,
             "Select one of the four deterministic payload patterns");
BUILD_ASSERT(TEST_CHANNEL <= 80,
             "BLE radio channel must be 0-80");

int test_cfg_get(struct radio_test_mode_config *config) {
	int err = radio_test_mode_config_init(config, RADIO_TEST_MODE_MODULATED_TX);

	if (err) {
		return err;
	}
	config->phy = TEST_PHY;
	config->channel = TEST_CHANNEL;
	config->txpower = TEST_TXPOWER_DBM;
	config->pattern = TEST_PATTERN;
	config->packet_count = TEST_PACKET_COUNT;
	return 0;
}

void test_cfg_print(const struct radio_test_mode_config *config) {
	static const char *const patterns[] = {
		[RADIO_TEST_MODE_PATTERN_11110000] = "repeated 11110000",
		[RADIO_TEST_MODE_PATTERN_11001100] = "repeated 11001100",
		[RADIO_TEST_MODE_PATTERN_00000000] = "repeated 00000000",
		[RADIO_TEST_MODE_PATTERN_11111111] = "repeated 11111111",
	};
	static const char *const phys[] = {
		[RADIO_TEST_MODE_PHY_BLE_1M] = "BLE 1M",
		[RADIO_TEST_MODE_PHY_BLE_2M] = "BLE 2M",
	};

	printk("nRF54L15 Radio TX Packet Test\n");
	printk("  pattern  %s\n", patterns[config->pattern]);
	printk("  PHY      %s\n", phys[config->phy]);
	printk("  channel  %u (%u MHz)\n", config->channel, 2400 + config->channel);
	printk("  power    %d dBm\n", config->txpower);
	printk("  packets  %u\n", config->packet_count);
}
