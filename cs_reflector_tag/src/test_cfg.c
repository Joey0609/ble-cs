/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <zephyr/sys/util.h>

#include "test_cfg.h"
#include <cs_generated_config/cs_generated_config.h>

/* ======================================================================
 * Test configuration. Edit this block, rebuild, flash. Not used when a
 * planner export is linked (-DCS_CONFIG_SOURCE).
 * The initiator creates the shared CS configuration (mode, RTT type,
 * channel map); these are the reflector's local settings only.
 * ====================================================================== */

/* ACL connection. Interval in 1.25 ms units, timeout in 10 ms units. */
#define TEST_CONN_INTERVAL_MIN 6  /* 7.5 ms */
#define TEST_CONN_INTERVAL_MAX 40 /* 50 ms */
#define TEST_CONN_LATENCY 0
#define TEST_CONN_TIMEOUT 400 /* 4 s */

/* CS configuration ID the initiator creates, 0-3. */
#define TEST_CONFIG_ID 0

/* CS default settings. One of CS_CONFIG_SYNC_ANTENNA_*; power in dBm, -127..20.
 */
#define TEST_SYNC_ANTENNA CS_CONFIG_SYNC_ANTENNA_REPETITIVE
#define TEST_MAX_TX_POWER_DBM 20

/* Procedure. Duration in 0.625 ms units, intervals in ACL events,
 * subevent length in microseconds. A count of 0 runs until disabled.
 */
#define TEST_MAX_PROCEDURE_LEN 10 /* 6.25 ms */
#define TEST_PROCEDURE_INTERVAL_MIN 1
#define TEST_PROCEDURE_INTERVAL_MAX 10
#define TEST_MAX_PROCEDURE_COUNT 0
#define TEST_SUBEVENT_LEN_MIN_US 6000
#define TEST_SUBEVENT_LEN_MAX_US 60000

/* A = initiator, B = reflector: one peer antenna and both Tag antennas.
 * The initiator must also request A1:B2 (or A2:B2 with a two-antenna peer).
 */
#define TEST_TONE_ANTENNA CS_CONFIG_TONE_ANTENNA_A1_B2
#define TEST_PHY CS_CONFIG_PROCEDURE_PHY_2M

/* TX power delta in dB, or CS_CONFIG_TX_POWER_DELTA_NONE. */
#define TEST_TX_POWER_DELTA CS_CONFIG_TX_POWER_DELTA_NONE

/* Bitmask of CS_CONFIG_PEER_ANTENNA_*. */
#define TEST_PEER_ANTENNA CS_CONFIG_PEER_ANTENNA_1

/* One of CS_CONFIG_SNR_CONTROL_*. */
#define TEST_SNR_CONTROL_INITIATOR CS_CONFIG_SNR_CONTROL_NOT_USED
#define TEST_SNR_CONTROL_REFLECTOR CS_CONFIG_SNR_CONTROL_NOT_USED

/* ====================================================================== */

BUILD_ASSERT(TEST_CONFIG_ID <= CS_CONFIG_ID_MAX,
             "CS configuration ID must be 0-3");
BUILD_ASSERT(TEST_SUBEVENT_LEN_MIN_US <= TEST_SUBEVENT_LEN_MAX_US,
             "Minimum subevent length must not exceed the maximum");
BUILD_ASSERT(TEST_PROCEDURE_INTERVAL_MIN <= TEST_PROCEDURE_INTERVAL_MAX,
             "Minimum procedure interval must not exceed the maximum");

int test_cfg_get(struct cs_reflector_config *config,
                 bool *generated) {
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
	int err;

	/* A linked planner export supplies the complete record. Without one the
	 * weak default loads cs_reflector_config_get_default() and returns
	 * -ENOENT, and the TEST_* values are applied on top.
	 */
	err = cs_generated_config_reflector(config);
	*generated = err == 0;
	if (err != -ENOENT) {
		return err;
	}
	err = cs_reflector_config_set_connection(config, &connection);
	if (err) {
		return err;
	}
	err = cs_reflector_config_set_default_settings(config, &settings);
	if (err) {
		return err;
	}
	err = cs_reflector_config_set_procedure(config, &procedure);
	if (err) {
		return err;
	}
	return cs_reflector_config_set_config_id(config, TEST_CONFIG_ID);
}
