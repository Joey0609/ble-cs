/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <string.h>

#include <zephyr/drivers/clock_control.h>
#include <zephyr/drivers/clock_control/nrf_clock_control.h>
#include <zephyr/irq.h>
#include <zephyr/kernel.h>
#include <zephyr/sw_isr_table.h>

#include <hal/nrf_radio.h>
#include <nrfx.h>
#if NRF_ERRATA_STATIC_CHECK(54L, 20)
#include <hal/nrf_power.h>
#endif /* NRF_ERRATA_STATIC_CHECK(54L, 20) */
#if defined(NRF54LM20A_XXAA)
#include <hal/nrf_clock.h>
#endif /* defined(NRF54LM20A_XXAA) */

#include <radio_test.h>
#include "radio_test_mode.h"

#define CHANNEL_MAX 80

/* Interrupt lines radio_test.c connects; mirrors its RADIO_TEST_*_IRQn. */
#if defined(CONFIG_SOC_SERIES_NRF54H)
#define RADIO_IRQ_LINE RADIO_0_IRQn
#define TIMER_IRQ_LINE TIMER020_IRQn
#elif defined(CONFIG_SOC_SERIES_NRF54L) || defined(CONFIG_SOC_SERIES_NRF71)
#define RADIO_IRQ_LINE RADIO_0_IRQn
#define TIMER_IRQ_LINE TIMER10_IRQn
#else
#define RADIO_IRQ_LINE RADIO_IRQn
#define TIMER_IRQ_LINE TIMER0_IRQn
#endif

/* The RX statistics chain in front of the driver's interrupt handlers. */
BUILD_ASSERT(IS_ENABLED(CONFIG_DYNAMIC_INTERRUPTS) && IS_ENABLED(CONFIG_GEN_SW_ISR_TABLE_ARRAY) &&
		     !IS_ENABLED(CONFIG_MULTI_LEVEL_INTERRUPTS),
	     "radio_test_mode needs a writable, single-level software ISR table");

#if defined(RADIO_SHORTS_ADDRESS_RSSISTART_Msk) || defined(RADIO_SHORTS0_ADDRESS_RSSISTART_Msk)
#define HAS_RSSI 1
#else
#define HAS_RSSI 0
#endif

/* RSSISAMPLE reads 127 until a sample was taken. */
#define RSSI_SAMPLE_NONE 0x7FU

/* IEEE 802.15.4 channel 11 is 2405 MHz, 5 MHz apart (radio_test.c). */
#define IEEE_BASE_MHZ 2405U
#define IEEE_SPACING_MHZ 5U

/* radio_test_init() keeps pointers into this structure for its interrupt
 * handlers, so the driver configuration lives here for the program lifetime
 * and each role is copied into it while the driver is idle.
 */
static struct radio_test_config active;
static enum radio_test_mode_pattern requested_pattern = RADIO_TEST_MODE_PATTERN_RANDOM;
static uint8_t pattern_packet[RADIO_MAX_PAYLOAD_LEN] __aligned(4);
static void (*user_done_cb)(void);
static bool initialized;
static bool applied;
static volatile bool running;

/* Driver interrupt handlers the statistics handlers forward to. */
static struct _isr_table_entry radio_isr_next;
static struct _isr_table_entry timer_isr_next;

/* Written by the radio interrupt; read under irq_lock(). */
static struct {
	uint32_t received;
	uint32_t crc_errors;
	/* A packet arrived since the last radio_test_mode_rx_stats_get(). */
	bool packet_seen;
	uint8_t rssi_sample;
	uint8_t channel;
} rx;

static void done_handler(void) {
	running = false;
	if (user_done_cb) {
		user_done_cb();
	}
}

/* Channel number of the tuned frequency, as in radio_test_mode_config. */
static uint8_t tuned_channel(void) {
	uint16_t mhz = nrf_radio_frequency_get(NRF_RADIO);

#if CONFIG_HAS_HW_NRF_RADIO_IEEE802154
	if (nrf_radio_mode_get(NRF_RADIO) == NRF_RADIO_MODE_IEEE802154_250KBIT) {
		return (uint8_t)(IEEE_MIN_CHANNEL + (mhz - IEEE_BASE_MHZ) / IEEE_SPACING_MHZ);
	}
#endif
	return (uint8_t)(mhz - 2400U);
}

static void rx_packet_seen(void) {
	rx.packet_seen = true;
	rx.rssi_sample = HAS_RSSI ? nrf_radio_rssi_sample_get(NRF_RADIO) : RSSI_SAMPLE_NONE;
	rx.channel = tuned_channel();
}

/* The driver counts only CRC-valid packets, restarts that count on every
 * sweep channel and takes no RSSI. Once it has enabled RX (the CRCOK
 * interrupt), also interrupt on CRC errors and sample RSSI at each address.
 * Called after every place the driver may start RX: radio_test_start() and
 * the sweep timer interrupt. radio_disable() clears both again.
 */
static void rx_extend(void) {
	if (!nrf_radio_int_enable_check(NRF_RADIO, NRF_RADIO_INT_CRCOK_MASK) ||
	    nrf_radio_int_enable_check(NRF_RADIO, NRF_RADIO_INT_CRCERROR_MASK)) {
		return;
	}
	/* The driver never clears CRCERROR; drop one left from an earlier RX. */
	nrf_radio_event_clear(NRF_RADIO, NRF_RADIO_EVENT_CRCERROR);
	nrf_radio_int_enable(NRF_RADIO, NRF_RADIO_INT_CRCERROR_MASK);
#if HAS_RSSI
	nrf_radio_shorts_enable(NRF_RADIO, NRF_RADIO_SHORT_ADDRESS_RSSISTART_MASK);
#endif
}

/* The NCS sample currently exposes only three transmit patterns.  Keep its
 * setup path and replace the packet/address bytes for the two constant
 * patterns that the host protocol exposes.  This is reapplied after the
 * sample's sweep timer has configured the next channel. */
static void apply_pattern_override(void) {
	uint8_t value;
	uint16_t payload_length = RADIO_MAX_PAYLOAD_LEN - 1U;

	if (requested_pattern != RADIO_TEST_MODE_PATTERN_00000000 &&
	    requested_pattern != RADIO_TEST_MODE_PATTERN_11111111) {
		return;
	}

	value = requested_pattern == RADIO_TEST_MODE_PATTERN_11111111 ? 0xFFU : 0x00U;
#if CONFIG_HAS_HW_NRF_RADIO_IEEE802154
	if (active.mode == NRF_RADIO_MODE_IEEE802154_250KBIT) {
		payload_length = IEEE_MAX_PAYLOAD_LEN - 1U;
	}
#endif
	pattern_packet[0] = (uint8_t)payload_length;
	memset(&pattern_packet[1], value, payload_length);
	nrf_radio_prefix0_set(NRF_RADIO, value);
	nrf_radio_base0_set(NRF_RADIO, value ? UINT32_MAX : 0U);
	nrf_radio_packetptr_set(NRF_RADIO, pattern_packet);
}

static void radio_isr(const void *arg) {
	ARG_UNUSED(arg);

	if (nrf_radio_int_enable_check(NRF_RADIO, NRF_RADIO_INT_CRCERROR_MASK) &&
	    nrf_radio_event_check(NRF_RADIO, NRF_RADIO_EVENT_CRCERROR)) {
		nrf_radio_event_clear(NRF_RADIO, NRF_RADIO_EVENT_CRCERROR);
		rx.crc_errors++;
		rx_packet_seen();
	}
	/* The driver clears CRCOK and keeps its own count. */
	if (nrf_radio_int_enable_check(NRF_RADIO, NRF_RADIO_INT_CRCOK_MASK) &&
	    nrf_radio_event_check(NRF_RADIO, NRF_RADIO_EVENT_CRCOK)) {
		rx.received++;
		rx_packet_seen();
	}
	radio_isr_next.isr(radio_isr_next.arg);
}

/* The sweep timer interrupt retunes and restarts RX on the next channel. */
static void timer_isr(const void *arg) {
	ARG_UNUSED(arg);

	timer_isr_next.isr(timer_isr_next.arg);
	apply_pattern_override();
	rx_extend();
}

/* Put isr in front of the handler connected to irq. Both run at the lowest
 * priority, like the driver's handlers.
 */
static void isr_chain(unsigned int irq, struct _isr_table_entry *next, void (*isr)(const void *)) {
	unsigned int key = irq_lock();
	bool was_enabled = irq_is_enabled(irq);

	/* radio_test_init() already enables RADIO_0 after connecting its handler.
	 * Zephyr requires a dynamic vector to be replaced while its IRQ is disabled.
	 * Keep the timer's prior state too: it is normally disabled until a sweep.
	 */
	irq_disable(irq);
	*next = _sw_isr_table[irq - CONFIG_GEN_IRQ_START_VECTOR];
	(void)irq_connect_dynamic(irq, IRQ_PRIO_LOWEST, isr, NULL, 0);
	if (was_enabled) {
		irq_enable(irq);
	}
	irq_unlock(key);
}

/* Mirrors the NCS radio_test sample: the radio needs HFCLK running from the
 * crystal before any test is started.
 */
static int clock_init(void) {
	struct onoff_manager *clk_mgr;
	struct onoff_client clk_cli;
	int err;
	int res;

	clk_mgr = z_nrf_clock_control_get_onoff(CLOCK_CONTROL_NRF_SUBSYS_HF);
	if (!clk_mgr) {
		return -ENXIO;
	}

	sys_notify_init_spinwait(&clk_cli.notify);
	err = onoff_request(clk_mgr, &clk_cli);
	if (err < 0) {
		return err;
	}

	do {
		err = sys_notify_fetch_result(&clk_cli.notify, &res);
		if (!err && res) {
			return res;
		}
	} while (err);

#if NRF_ERRATA_STATIC_CHECK(54L, 20)
	if (NRF_ERRATA_DYNAMIC_CHECK(54L, 20)) {
		nrf_power_task_trigger(NRF_POWER, NRF_POWER_TASK_CONSTLAT);
	}
#endif /* NRF_ERRATA_STATIC_CHECK(54L, 20) */

#if defined(NRF54LM20A_XXAA)
	/* MLTPAN-39 */
	nrf_clock_task_trigger(NRF_CLOCK, NRF_CLOCK_TASK_PLLSTART);
#endif /* defined(NRF54LM20A_XXAA) */

	return 0;
}

/* PHYs the SoC lacks compile to -ENOTSUP rather than a missing case. */
static int phy_convert(enum radio_test_mode_phy phy, nrf_radio_mode_t *mode) {
	switch (phy) {
	case RADIO_TEST_MODE_PHY_BLE_1M:
		*mode = NRF_RADIO_MODE_BLE_1MBIT;
		return 0;
	case RADIO_TEST_MODE_PHY_BLE_2M:
#if defined(RADIO_MODE_MODE_Ble_2Mbit)
		*mode = NRF_RADIO_MODE_BLE_2MBIT;
		return 0;
#else
		return -ENOTSUP;
#endif
	case RADIO_TEST_MODE_PHY_BLE_LR125K:
#if defined(RADIO_MODE_MODE_Ble_LR125Kbit)
		*mode = NRF_RADIO_MODE_BLE_LR125KBIT;
		return 0;
#else
		return -ENOTSUP;
#endif
	case RADIO_TEST_MODE_PHY_BLE_LR500K:
#if defined(RADIO_MODE_MODE_Ble_LR500Kbit)
		*mode = NRF_RADIO_MODE_BLE_LR500KBIT;
		return 0;
#else
		return -ENOTSUP;
#endif
	case RADIO_TEST_MODE_PHY_NRF_1M:
		*mode = NRF_RADIO_MODE_NRF_1MBIT;
		return 0;
	case RADIO_TEST_MODE_PHY_NRF_2M:
		*mode = NRF_RADIO_MODE_NRF_2MBIT;
		return 0;
	case RADIO_TEST_MODE_PHY_IEEE802154_250K:
		/* The driver only maps IEEE channels when this is enabled. */
#if CONFIG_HAS_HW_NRF_RADIO_IEEE802154
		*mode = NRF_RADIO_MODE_IEEE802154_250KBIT;
		return 0;
#else
		return -ENOTSUP;
#endif
	default:
		return -EINVAL;
	}
}

static int pattern_convert(enum radio_test_mode_pattern pattern,
			   enum transmit_pattern *out) {
	switch (pattern) {
	case RADIO_TEST_MODE_PATTERN_RANDOM:
		*out = TRANSMIT_PATTERN_RANDOM;
		return 0;
	case RADIO_TEST_MODE_PATTERN_11110000:
		*out = TRANSMIT_PATTERN_11110000;
		return 0;
	case RADIO_TEST_MODE_PATTERN_11001100:
		*out = TRANSMIT_PATTERN_11001100;
		return 0;
	case RADIO_TEST_MODE_PATTERN_00000000:
		/* The NCS driver is initialized with a known pattern and corrected
		 * immediately after radio_test_start() by apply_pattern_override(). */
		*out = TRANSMIT_PATTERN_11001100;
		return 0;
	case RADIO_TEST_MODE_PATTERN_11111111:
		/* See the all-zero pattern above. */
		*out = TRANSMIT_PATTERN_11110000;
		return 0;
	default:
		return -EINVAL;
	}
}

static bool channel_valid(enum radio_test_mode_phy phy, uint8_t channel) {
	if (phy == RADIO_TEST_MODE_PHY_IEEE802154_250K) {
		return channel >= IEEE_MIN_CHANNEL && channel <= IEEE_MAX_CHANNEL;
	}
	return channel <= CHANNEL_MAX;
}

static bool sweep_valid(const struct radio_test_mode_config *config) {
	return config->sweep_start_channel <= config->sweep_end_channel &&
	       config->sweep_end_channel <= CHANNEL_MAX &&
	       config->sweep_delay_ms > 0;
}

/* Validate the settings and build the driver configuration for them. */
static int convert(const struct radio_test_mode_config *config,
		   struct radio_test_config *out) {
	struct radio_test_config result = {0};
	enum transmit_pattern pattern;
	int err;

	err = phy_convert(config->phy, &result.mode);
	if (err) {
		return err;
	}
	err = pattern_convert(config->pattern, &pattern);
	if (err) {
		return err;
	}

	/* Finite tests always get the internal handler so the running state
	 * is tracked; it forwards to the caller's optional callback.
	 */
	void (*cb)(void) = config->packet_count ? done_handler : NULL;

	switch (config->type) {
	case RADIO_TEST_MODE_UNMODULATED_TX:
		if (!channel_valid(config->phy, config->channel)) {
			return -EINVAL;
		}
		result.type = UNMODULATED_TX;
		result.params.unmodulated_tx.txpower = config->txpower;
		result.params.unmodulated_tx.channel = config->channel;
		break;

	case RADIO_TEST_MODE_MODULATED_TX:
		if (!channel_valid(config->phy, config->channel)) {
			return -EINVAL;
		}
		result.type = MODULATED_TX;
		result.params.modulated_tx.txpower = config->txpower;
		result.params.modulated_tx.pattern = pattern;
		result.params.modulated_tx.channel = config->channel;
		result.params.modulated_tx.packets_num = config->packet_count;
		result.params.modulated_tx.cb = cb;
		break;

	case RADIO_TEST_MODE_RX:
		if (!channel_valid(config->phy, config->channel)) {
			return -EINVAL;
		}
		result.type = RX;
		result.params.rx.pattern = pattern;
		result.params.rx.channel = config->channel;
		result.params.rx.packets_num = config->packet_count;
		result.params.rx.cb = cb;
		break;

	case RADIO_TEST_MODE_TX_SWEEP:
		if (!sweep_valid(config)) {
			return -EINVAL;
		}
		result.type = TX_SWEEP;
		result.params.tx_sweep.txpower = config->txpower;
		result.params.tx_sweep.channel_start = config->sweep_start_channel;
		result.params.tx_sweep.channel_end = config->sweep_end_channel;
		result.params.tx_sweep.delay_ms = config->sweep_delay_ms;
		break;

	case RADIO_TEST_MODE_RX_SWEEP:
		if (!sweep_valid(config)) {
			return -EINVAL;
		}
		result.type = RX_SWEEP;
		result.params.rx_sweep.channel_start = config->sweep_start_channel;
		result.params.rx_sweep.channel_end = config->sweep_end_channel;
		result.params.rx_sweep.delay_ms = config->sweep_delay_ms;
		break;

	case RADIO_TEST_MODE_MODULATED_TX_DUTY_CYCLE:
		if (!channel_valid(config->phy, config->channel) ||
		    config->duty_cycle < 1 || config->duty_cycle > 99) {
			return -EINVAL;
		}
		result.type = MODULATED_TX_DUTY_CYCLE;
		result.params.modulated_tx_duty_cycle.txpower = config->txpower;
		result.params.modulated_tx_duty_cycle.pattern = pattern;
		result.params.modulated_tx_duty_cycle.channel = config->channel;
		result.params.modulated_tx_duty_cycle.duty_cycle = config->duty_cycle;
		result.params.modulated_tx_duty_cycle.packets_num = config->packet_count;
		result.params.modulated_tx_duty_cycle.cb = cb;
		break;

	case RADIO_TEST_MODE_TX_SWEEP_WITH_SLEEP:
		if (!config->tx_time_us || !config->sleep_time_us) {
			return -EINVAL;
		}
		result.type = TX_SWEEP_WITH_SLEEP;
		result.params.tx_sweep_with_sleep.txpower = config->txpower;
		result.params.tx_sweep_with_sleep.t_tx_us = config->tx_time_us;
		result.params.tx_sweep_with_sleep.t_sleep_us = config->sleep_time_us;
		break;

	case RADIO_TEST_MODE_TX_SWEEP_WITH_SLEEP_MODULATED:
		if (!config->tx_time_us || !config->sleep_time_us) {
			return -EINVAL;
		}
		result.type = TX_SWEEP_WITH_SLEEP_MODULATED;
		result.params.tx_sweep_with_sleep_modulated.txpower = config->txpower;
		result.params.tx_sweep_with_sleep_modulated.pattern = pattern;
		result.params.tx_sweep_with_sleep_modulated.t_tx_us = config->tx_time_us;
		result.params.tx_sweep_with_sleep_modulated.t_sleep_us =
				config->sleep_time_us;
		break;

	default:
		return -EINVAL;
	}

#if CONFIG_FEM
	result.fem.ramp_up_time = config->fem.ramp_up_time_us;
	result.fem.tx_power_control = config->fem.tx_power_control;
#endif

	*out = result;
	return 0;
}

int radio_test_mode_config_init(struct radio_test_mode_config *config,
				enum radio_test_mode_type type) {
	if (!config || type < RADIO_TEST_MODE_UNMODULATED_TX ||
	    type > RADIO_TEST_MODE_TX_SWEEP_WITH_SLEEP_MODULATED) {
		return -EINVAL;
	}

	*config = (struct radio_test_mode_config){
		.type = type,
		.phy = RADIO_TEST_MODE_PHY_BLE_1M,
		.channel = 3,
		.txpower = 0,
		.pattern = RADIO_TEST_MODE_PATTERN_RANDOM,
		.packet_count = 0,
		.sweep_start_channel = 0,
		.sweep_end_channel = CHANNEL_MAX,
		.sweep_delay_ms = 10,
		.duty_cycle = 50,
		.tx_time_us = 100,
		.sleep_time_us = 100,
		.fem = {
			.tx_power_control = FEM_USE_DEFAULT_TX_POWER_CONTROL,
		},
	};
	return 0;
}

int radio_test_mode_config_validate(const struct radio_test_mode_config *config) {
	struct radio_test_config result;

	if (!config) {
		return -EINVAL;
	}
	return convert(config, &result);
}

int radio_test_mode_init(void) {
	int err;

	if (initialized) {
		return -EALREADY;
	}

	err = clock_init();
	if (err) {
		return err;
	}

	err = radio_test_init(&active);
	if (err) {
		return err;
	}
	isr_chain(RADIO_IRQ_LINE, &radio_isr_next, radio_isr);
	isr_chain(TIMER_IRQ_LINE, &timer_isr_next, timer_isr);

	initialized = true;
	return 0;
}

int radio_test_mode_apply(const struct radio_test_mode_config *config) {
	struct radio_test_config result;
	int err;

	if (!initialized) {
		return -EACCES;
	}
	if (!config) {
		return -EINVAL;
	}

	err = convert(config, &result);
	if (err) {
		return err;
	}

	(void)radio_test_mode_stop();
	active = result;
	requested_pattern = config->pattern;
	user_done_cb = config->done_cb;
	applied = true;
	return 0;
}

int radio_test_mode_start(void) {
	unsigned int key;

	if (!initialized) {
		return -EACCES;
	}
	if (!applied) {
		return -ENODATA;
	}
	if (running) {
		return -EBUSY;
	}

	key = irq_lock();
	rx.received = 0U;
	rx.crc_errors = 0U;
	rx.packet_seen = false;
	irq_unlock(key);

	running = true;
	radio_test_start(&active);
	apply_pattern_override();

	key = irq_lock();
	rx_extend();
	irq_unlock(key);
	return 0;
}

int radio_test_mode_stop(void) {
	if (!initialized) {
		return -EACCES;
	}

	/* The driver defers cancelling modulated TX until the current packet
	 * ends, and only clears that request once it does. Passing a type it
	 * cancels synchronously stops every role immediately, so the driver is
	 * idle before the next role is copied into the shared configuration.
	 */
	radio_test_cancel(UNMODULATED_TX);
	running = false;
	return 0;
}

bool radio_test_mode_is_running(void) {
	return running;
}

int radio_test_mode_rx_stats_get(struct radio_test_mode_rx_stats *stats) {
	unsigned int key;

	if (!initialized) {
		return -EACCES;
	}
	if (!stats) {
		return -EINVAL;
	}

	key = irq_lock();
	stats->packets_received = rx.received;
	stats->crc_errors = rx.crc_errors;
	if (rx.packet_seen && rx.rssi_sample != RSSI_SAMPLE_NONE) {
		stats->rssi_dbm = -(int8_t)rx.rssi_sample;
	} else {
		stats->rssi_dbm = RADIO_TEST_MODE_RSSI_UNAVAILABLE;
	}
	stats->channel = rx.packet_seen ? rx.channel : tuned_channel();
	rx.packet_seen = false;
	irq_unlock(key);
	return 0;
}
