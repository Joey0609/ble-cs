/* SPDX-License-Identifier: MIT */
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

#include "radio_test_cfg.h"

/* The radio test driver drives RADIO, TIMER10 and EGU10 directly. MPSL claims
 * the same peripherals on the nRF54L series, so this application must not be
 * combined with a Bluetooth build.
 */
BUILD_ASSERT(!IS_ENABLED(CONFIG_BT),
	     "The radio test driver cannot share the radio with the Bluetooth stack");

int main(void)
{
	struct radio_test_mode_config config;
	int err;

	err = radio_test_mode_init();
	if (err) {
		printk("Radio test mode init failed: %d\n", err);
		return 0;
	}

	err = radio_test_cfg_get(&config);
	if (err) {
		printk("Radio test configuration failed: %d\n", err);
		return 0;
	}

	err = radio_test_mode_apply(&config);
	if (err) {
		printk("Radio test apply failed: %d\n", err);
		return 0;
	}

	radio_test_cfg_print(&config);
	err = radio_test_mode_start();
	if (err) {
		printk("Radio test start failed: %d\n", err);
		return 0;
	}
	printk("Running. Reset the board to stop.\n");

	return 0;
}
