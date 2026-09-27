/* SPDX-License-Identifier: MIT */
#include <zephyr/toolchain.h>

#include "test_cfg.h"

/* ======================================================================
 * Test configuration. Edit this block, rebuild, flash.
 * The initiator owns the shared CS configuration (mode, RTT type, channel
 * map) as well as its local settings.
 * ====================================================================== */

/* Peer selection. Any connectable advertiser listing the Ranging Service
 * UUID matches; a non-empty name must also equal its advertised name.
 */
#define TEST_PEER_NAME "CS Reflector Test"

/* ACL connection. Interval in 1.25 ms units, timeout in 10 ms units. */
#define TEST_CONN_INTERVAL_MIN 6 /* 7.5 ms */
#define TEST_CONN_INTERVAL_MAX 6
#define TEST_CONN_LATENCY 0
#define TEST_CONN_TIMEOUT 400 /* 4 s */

/* CS configuration ID created on both controllers, 0-3. */
#define TEST_CONFIG_ID 0

/* CS default settings. One of CS_CONFIG_SYNC_ANTENNA_*; power in dBm, -127..20. */
#define TEST_SYNC_ANTENNA CS_CONFIG_SYNC_ANTENNA_REPETITIVE
#define TEST_MAX_TX_POWER_DBM 20

/* Procedure. Duration in 0.625 ms units, intervals in ACL events,
 * subevent length in microseconds. A count of 0 runs until disabled.
 */
#define TEST_MAX_PROCEDURE_LEN 10 /* 6.25 ms */
#define TEST_PROCEDURE_INTERVAL_MIN 1
#define TEST_PROCEDURE_INTERVAL_MAX 4
#define TEST_MAX_PROCEDURE_COUNT 0
#define TEST_SUBEVENT_LEN_MIN_US 6000
#define TEST_SUBEVENT_LEN_MAX_US 6000

/* One of CS_CONFIG_TONE_ANTENNA_*, CS_CONFIG_PROCEDURE_PHY_*. */
#define TEST_TONE_ANTENNA CS_CONFIG_TONE_ANTENNA_A1_B1
#define TEST_PHY CS_CONFIG_PROCEDURE_PHY_1M

/* TX power delta in dB, or CS_CONFIG_TX_POWER_DELTA_NONE. */
#define TEST_TX_POWER_DELTA CS_CONFIG_TX_POWER_DELTA_NONE

/* Bitmask of CS_CONFIG_PEER_ANTENNA_*. */
#define TEST_PEER_ANTENNA CS_CONFIG_PEER_ANTENNA_1

/* One of CS_CONFIG_SNR_CONTROL_*. */
#define TEST_SNR_CONTROL_INITIATOR CS_CONFIG_SNR_CONTROL_NOT_USED
#define TEST_SNR_CONTROL_REFLECTOR CS_CONFIG_SNR_CONTROL_NOT_USED

/* Shared configuration. One of CS_CONFIG_MODE_*, CS_CONFIG_RTT_TYPE_*,
 * CS_CONFIG_SYNC_PHY_*.
 */
#define TEST_MODE CS_CONFIG_MODE_2_SUB_MODE_1
#define TEST_MIN_MAIN_MODE_STEPS 2
#define TEST_MAX_MAIN_MODE_STEPS 10
#define TEST_MAIN_MODE_REPETITION 0
#define TEST_MODE_0_STEPS 1
#define TEST_RTT_TYPE CS_CONFIG_RTT_TYPE_AA_ONLY
#define TEST_SYNC_PHY CS_CONFIG_SYNC_PHY_1M

/* CS channel map, byte 0 first; bit n is 2402 + n MHz. At least 15 channels;
 * bits 0, 1, 23-25 and 77-79 must be clear. Default: channels 26-61.
 */
#define TEST_CHANNEL_MAP {0x00, 0x00, 0x00, 0xFC, 0xFF, 0xFF, 0xFF, 0x3F, 0x00, 0x00}
#define TEST_CHANNEL_MAP_REPETITION 1

/* One of CS_CONFIG_CHSEL_TYPE_*; shape and jump apply to 3c only. */
#define TEST_CHSEL_TYPE CS_CONFIG_CHSEL_TYPE_3B
#define TEST_CH3C_SHAPE CS_CONFIG_CH3C_SHAPE_HAT
#define TEST_CH3C_JUMP 2

/* Bitmask of CS_CONFIG_ENHANCEMENTS_1_*. IPT needs peer support and
 * CONFIG_BT_CTLR_EXTENDED_FEAT_SET=y.
 */
#define TEST_ENHANCEMENTS_1 0

/* Completed or aborted procedures after which TEST PASS/FAIL is logged on
 * the debug UART. PASS requires no aborted procedure. 0 disables the verdict.
 */
#define TEST_EXPECTED_PROCEDURES 100

/* ====================================================================== */

BUILD_ASSERT(TEST_CONFIG_ID <= CS_CONFIG_ID_MAX, "CS configuration ID must be 0-3");
BUILD_ASSERT(TEST_SUBEVENT_LEN_MIN_US <= TEST_SUBEVENT_LEN_MAX_US,
             "Minimum subevent length must not exceed the maximum");
BUILD_ASSERT(TEST_PROCEDURE_INTERVAL_MIN <= TEST_PROCEDURE_INTERVAL_MAX,
             "Minimum procedure interval must not exceed the maximum");
BUILD_ASSERT(TEST_MIN_MAIN_MODE_STEPS <= TEST_MAX_MAIN_MODE_STEPS,
             "Minimum main-mode steps must not exceed the maximum");

int test_cfg_get(struct cs_initiator_config *config) {
	const struct cs_config_connection connection = {
		.interval_min = TEST_CONN_INTERVAL_MIN,
		.interval_max = TEST_CONN_INTERVAL_MAX,
		.latency = TEST_CONN_LATENCY,
		.timeout = TEST_CONN_TIMEOUT,
	};
	const struct cs_config_default_settings settings = {
		.cs_sync_antenna_selection = TEST_SYNC_ANTENNA,
		.max_tx_power = TEST_MAX_TX_POWER_DBM,
	};
	const struct cs_config_procedure procedure = {
		.max_procedure_len = TEST_MAX_PROCEDURE_LEN,
		.min_procedure_interval = TEST_PROCEDURE_INTERVAL_MIN,
		.max_procedure_interval = TEST_PROCEDURE_INTERVAL_MAX,
		.max_procedure_count = TEST_MAX_PROCEDURE_COUNT,
		.min_subevent_len = TEST_SUBEVENT_LEN_MIN_US,
		.max_subevent_len = TEST_SUBEVENT_LEN_MAX_US,
		.tone_antenna_config_selection = TEST_TONE_ANTENNA,
		.phy = TEST_PHY,
		.tx_power_delta = TEST_TX_POWER_DELTA,
		.preferred_peer_antenna = TEST_PEER_ANTENNA,
		.snr_control_initiator = TEST_SNR_CONTROL_INITIATOR,
		.snr_control_reflector = TEST_SNR_CONTROL_REFLECTOR,
	};
	const struct cs_config_creation creation = {
		.mode = TEST_MODE,
		.min_main_mode_steps = TEST_MIN_MAIN_MODE_STEPS,
		.max_main_mode_steps = TEST_MAX_MAIN_MODE_STEPS,
		.main_mode_repetition = TEST_MAIN_MODE_REPETITION,
		.mode_0_steps = TEST_MODE_0_STEPS,
		.rtt_type = TEST_RTT_TYPE,
		.cs_sync_phy = TEST_SYNC_PHY,
		.channel_map = TEST_CHANNEL_MAP,
		.channel_map_repetition = TEST_CHANNEL_MAP_REPETITION,
		.channel_selection_type = TEST_CHSEL_TYPE,
		.ch3c_shape = TEST_CH3C_SHAPE,
		.ch3c_jump = TEST_CH3C_JUMP,
		.cs_enhancements_1 = TEST_ENHANCEMENTS_1,
		/* The reflector learns the configuration through the exchange. */
		.context = CS_CONFIG_CREATION_CONTEXT_LOCAL_AND_REMOTE,
	};
	int err;

	err = cs_initiator_config_get_default(config);
	if (err) {
		return err;
	}
	err = cs_initiator_config_set_connection(config, &connection);
	if (err) {
		return err;
	}
	err = cs_initiator_config_set_default_settings(config, &settings);
	if (err) {
		return err;
	}
	err = cs_initiator_config_set_procedure(config, &procedure);
	if (err) {
		return err;
	}
	err = cs_initiator_config_set_creation(config, &creation);
	if (err) {
		return err;
	}
	return cs_initiator_config_set_config_id(config, TEST_CONFIG_ID);
}

const char *test_cfg_peer_name(void) {
	return TEST_PEER_NAME;
}

unsigned int test_cfg_expected_procedures(void) {
	return TEST_EXPECTED_PROCEDURES;
}
