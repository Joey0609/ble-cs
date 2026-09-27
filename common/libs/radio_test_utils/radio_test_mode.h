/* SPDX-License-Identifier: MIT */
#ifndef RADIO_TEST_MODE_H_
#define RADIO_TEST_MODE_H_

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Radio role. Mirrors the eight NCS radio test modes. */
enum radio_test_mode_type {
	RADIO_TEST_MODE_UNMODULATED_TX,
	RADIO_TEST_MODE_MODULATED_TX,
	RADIO_TEST_MODE_RX,
	RADIO_TEST_MODE_TX_SWEEP,
	RADIO_TEST_MODE_RX_SWEEP,
	RADIO_TEST_MODE_MODULATED_TX_DUTY_CYCLE,
	RADIO_TEST_MODE_TX_SWEEP_WITH_SLEEP,
	RADIO_TEST_MODE_TX_SWEEP_WITH_SLEEP_MODULATED,
};

/** PHY. Availability depends on the SoC; apply rejects unsupported ones. */
enum radio_test_mode_phy {
	RADIO_TEST_MODE_PHY_BLE_1M,
	RADIO_TEST_MODE_PHY_BLE_2M,
	RADIO_TEST_MODE_PHY_BLE_LR125K,
	RADIO_TEST_MODE_PHY_BLE_LR500K,
	RADIO_TEST_MODE_PHY_NRF_1M,
	RADIO_TEST_MODE_PHY_NRF_2M,
	RADIO_TEST_MODE_PHY_IEEE802154_250K,
};

/** Transmit payload and address pattern. */
enum radio_test_mode_pattern {
	RADIO_TEST_MODE_PATTERN_RANDOM,
	RADIO_TEST_MODE_PATTERN_11110000,
	RADIO_TEST_MODE_PATTERN_11001100,
	RADIO_TEST_MODE_PATTERN_00000000,
	RADIO_TEST_MODE_PATTERN_11111111,
};

/** Front-end module settings. Ignored unless built with CONFIG_FEM. */
struct radio_test_mode_fem {
	/** Radio ramp-up time in microseconds. */
	uint32_t ramp_up_time_us;
	/** FEM-specific TX power control value; 0xFF keeps the default. */
	uint8_t tx_power_control;
};

/** Requested role settings. Only fields used by type are applied. */
struct radio_test_mode_config {
	enum radio_test_mode_type type;
	enum radio_test_mode_phy phy;
	/** 2400 + channel MHz (0-80); IEEE 802.15.4 channel (11-26) for that PHY. */
	uint8_t channel;
	/** Output power in dBm. Values the SoC does not support fall back to 0 dBm. */
	int8_t txpower;
	enum radio_test_mode_pattern pattern;
	/** Zero runs until stopped; otherwise invokes done_cb on completion. */
	uint32_t packet_count;
	/** Optional; invoked from interrupt or system work queue context. */
	void (*done_cb)(void);
	/** Inclusive sweep range (0-80) and per-channel dwell time. */
	uint8_t sweep_start_channel;
	uint8_t sweep_end_channel;
	uint32_t sweep_delay_ms;
	/** Percentage, 1-99, for MODULATED_TX_DUTY_CYCLE. */
	uint8_t duty_cycle;
	/** Per-channel transmit and sleep times for sleep sweep modes. */
	uint16_t tx_time_us;
	uint16_t sleep_time_us;
	struct radio_test_mode_fem fem;
};

/** Initialize settings for a role with defaults: BLE 1M, channel 3
 * (2403 MHz), 0 dBm, random pattern, unlimited packets, no callback,
 * sweep 0-80 with 10 ms dwell, 50 percent duty cycle, 100 us transmit/sleep
 * times and default FEM settings. Performs no hardware operations.
 * Returns 0, or -EINVAL for NULL config or unknown type (output unchanged).
 */
int radio_test_mode_config_init(struct radio_test_mode_config *config,
				enum radio_test_mode_type type);

/** Check settings with the same rules as radio_test_mode_apply(), without
 * storing them. Needs no init and performs no hardware operations.
 * Returns 0, -EINVAL for invalid settings or -ENOTSUP for a PHY the SoC lacks.
 */
int radio_test_mode_config_validate(const struct radio_test_mode_config *config);

/** Start the crystal oscillator and initialize the radio test driver.
 * Call once before any other function. Returns 0, -EALREADY if already
 * initialized, or a negative error from the clock or driver.
 */
int radio_test_mode_init(void);

/** Validate and store the settings as the active role. Stops a running role
 * first, so this is the switch point between roles. Does not start the radio.
 * Returns 0, -EACCES before init, -EINVAL for invalid settings or -ENOTSUP
 * for a PHY the SoC lacks. On error the current role is left untouched.
 */
int radio_test_mode_apply(const struct radio_test_mode_config *config);

/** Start the applied role. Returns 0, -EACCES before init, -ENODATA if no
 * role was applied, or -EBUSY if it is already running.
 */
int radio_test_mode_start(void);

/** Stop the running role immediately, truncating any packet in the air.
 * Safe to call when nothing runs. Returns 0 or -EACCES before init.
 */
int radio_test_mode_stop(void);

/** True from start until stop, apply or a finite test's completion. */
bool radio_test_mode_is_running(void);

/** rssi_dbm of radio_test_mode_rx_stats when no RSSI sample is available. */
#define RADIO_TEST_MODE_RSSI_UNAVAILABLE 127

/** Receive statistics of an RX or RX sweep role since its start. */
struct radio_test_mode_rx_stats {
	/** Packets with a valid CRC, across all sweep channels; wraps at 2^32. */
	uint32_t packets_received;
	/** Packets with a failed CRC; wraps at 2^32. */
	uint32_t crc_errors;
	/** RSSI in dBm of the latest packet (valid or failed CRC) since the
	 * previous call, sampled at its address, or
	 * RADIO_TEST_MODE_RSSI_UNAVAILABLE.
	 */
	int8_t rssi_dbm;
	/** Channel of that packet, numbered as radio_test_mode_config.channel;
	 * the tuned channel when no packet arrived since the previous call.
	 */
	uint8_t channel;
};

/** Read the receive statistics. Counters restart at start and keep their
 * values after stop or completion until the next start; other roles leave
 * them at zero. Each call consumes the latest-packet RSSI and channel.
 * Safe to call from any thread. Returns 0, -EACCES before init or -EINVAL.
 */
int radio_test_mode_rx_stats_get(struct radio_test_mode_rx_stats *stats);

#ifdef __cplusplus
}
#endif

#endif /* RADIO_TEST_MODE_H_ */
