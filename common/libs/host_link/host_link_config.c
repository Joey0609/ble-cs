/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>

#include "cs_protocol/cs_protocol_packets.h"
#include "host_link_config.h"
#include "host_link_types.h"

#if defined(CONFIG_BT_CHANNEL_SOUNDING)
#include "cs_utils/cs_config.h"
#endif
#if defined(APP_LIBS_RADIO_TEST)
#include "radio_test_utils/radio_test_mode.h"
#endif

/* Copy a payload into the message fields of its frame struct. */
#define PAYLOAD_TO_FRAME(frame, payload) \
	memcpy((uint8_t *)&(frame) + CS_PROTOCOL_HEADER_SIZE, (payload), HOST_LINK_PAYLOAD_SIZE(frame))

#if defined(CONFIG_BT_CHANNEL_SOUNDING)

/* Frame encodings are HCI values, as are the cs_utils record encodings. */
BUILD_ASSERT(CS_PROTOCOL_CONFIG_CHANNEL_MAP_SIZE == CS_CONFIG_CHANNEL_MAP_SIZE);
BUILD_ASSERT(CS_PROTOCOL_CONFIG_ENHANCEMENTS_1_IPT == CS_CONFIG_ENHANCEMENTS_1_IPT);

/* The leading fields are identical in the initiator and reflector frames. */
#define COMMON_FIELDS_TO_RECORDS(f, connection, defaults, procedure)                 \
	do {                                                                         \
		(connection) = (struct cs_config_connection){                        \
			.interval_min = sys_le16_to_cpu((f).connection_interval_min), \
			.interval_max = sys_le16_to_cpu((f).connection_interval_max), \
			.latency = sys_le16_to_cpu((f).connection_latency),           \
			.timeout = sys_le16_to_cpu((f).connection_timeout),           \
		};                                                                   \
		(defaults) = (struct cs_config_default_settings){                    \
			.cs_sync_antenna_selection = (f).cs_sync_antenna_selection,   \
			.max_tx_power = (f).max_tx_power,                             \
		};                                                                   \
		(procedure) = (struct cs_config_procedure){                          \
			.max_procedure_len = sys_le16_to_cpu((f).max_procedure_len),  \
			.min_procedure_interval = sys_le16_to_cpu((f).min_procedure_interval), \
			.max_procedure_interval = sys_le16_to_cpu((f).max_procedure_interval), \
			.max_procedure_count = sys_le16_to_cpu((f).max_procedure_count), \
			.min_subevent_len = sys_le32_to_cpu((f).min_subevent_len),    \
			.max_subevent_len = sys_le32_to_cpu((f).max_subevent_len),    \
			.tone_antenna_config_selection = (f).tone_antenna_config_selection, \
			.phy = (f).phy,                                               \
			.tx_power_delta = (f).tx_power_delta,                         \
			.preferred_peer_antenna = (f).preferred_peer_antenna,         \
			.snr_control_initiator = (f).snr_control_initiator,           \
			.snr_control_reflector = (f).snr_control_reflector,           \
		};                                                                   \
	} while (0)

static bool gap_role_valid(uint8_t gap_role) {
	return gap_role == CS_PROTOCOL_GAP_CENTRAL || gap_role == CS_PROTOCOL_GAP_PERIPHERAL;
}

int host_link_config_to_initiator(const uint8_t *payload, size_t len,
                                  struct cs_initiator_config *config) {
	struct cs_protocol_cs_initiator_config_frame_t f;
	struct cs_config_connection connection;
	struct cs_config_default_settings defaults;
	struct cs_config_procedure procedure;
	struct cs_config_creation creation;
	int err;

	if (len != HOST_LINK_INITIATOR_PAYLOAD_SIZE) {
		return -EMSGSIZE;
	}
	PAYLOAD_TO_FRAME(f, payload);
	if (!gap_role_valid(f.gap_role) ||
	    (f.creation_cs_enhancements_1 & ~CS_PROTOCOL_CONFIG_ENHANCEMENTS_1_IPT) != 0U) {
		return -EINVAL;
	}
	err = host_link_config_check_antennas(CS_PROTOCOL_MODE_CS_INITIATOR, f.cs_sync_antenna_selection,
	                                      f.tone_antenna_config_selection,
	                                      CONFIG_APP_HOST_LINK_NUM_ANTENNAS);
	if (err) {
		return err;
	}

	COMMON_FIELDS_TO_RECORDS(f, connection, defaults, procedure);
	creation = (struct cs_config_creation){
		.mode = f.creation_mode,
		.min_main_mode_steps = f.creation_min_main_mode_steps,
		.max_main_mode_steps = f.creation_max_main_mode_steps,
		.main_mode_repetition = f.creation_main_mode_repetition,
		.mode_0_steps = f.creation_mode_0_steps,
		.rtt_type = f.creation_rtt_type,
		.cs_sync_phy = f.creation_cs_sync_phy,
		.channel_map_repetition = f.creation_channel_map_repetition,
		.channel_selection_type = f.creation_channel_selection_type,
		.ch3c_shape = f.creation_ch3c_shape,
		.ch3c_jump = f.creation_ch3c_jump,
		.cs_enhancements_1 = f.creation_cs_enhancements_1,
		.context = f.creation_context,
	};
	memcpy(creation.channel_map, f.creation_channel_map, sizeof(creation.channel_map));

	err = cs_initiator_config_get_default(config);
	err = err ?: cs_initiator_config_set_config_id(config, f.config_id);
	err = err ?: cs_initiator_config_set_connection(config, &connection);
	err = err ?: cs_initiator_config_set_default_settings(config, &defaults);
	err = err ?: cs_initiator_config_set_procedure(config, &procedure);
	err = err ?: cs_initiator_config_set_creation(config, &creation);
	return err;
}

int host_link_config_set_to_initiator(const struct host_link_config_set *set,
                                      struct cs_initiator_config *config) {
	int err;

	if (!set->has_mode || set->mode != CS_PROTOCOL_MODE_CS_INITIATOR) {
		return -EINVAL;
	}
	err = host_link_config_to_initiator(set->config, set->config_len, config);
	if (!err && set->has_peer_data) {
		err = cs_initiator_config_set_peer_data(config, set->peer_data);
	}
	if (!err && set->has_t_pm) {
		err = cs_initiator_config_set_t_pm(config, set->t_pm_us);
	}
	return err ?: cs_initiator_config_check_peer_data(config);
}

int host_link_config_to_reflector(const uint8_t *payload, size_t len,
                                  struct cs_reflector_config *config) {
	struct cs_protocol_cs_reflector_config_frame_t f;
	struct cs_config_connection connection;
	struct cs_config_default_settings defaults;
	struct cs_config_procedure procedure;
	int err;

	if (len != HOST_LINK_REFLECTOR_PAYLOAD_SIZE) {
		return -EMSGSIZE;
	}
	PAYLOAD_TO_FRAME(f, payload);
	if (!gap_role_valid(f.gap_role)) {
		return -EINVAL;
	}
	err = host_link_config_check_antennas(CS_PROTOCOL_MODE_CS_REFLECTOR, f.cs_sync_antenna_selection,
	                                      f.tone_antenna_config_selection,
	                                      CONFIG_APP_HOST_LINK_NUM_ANTENNAS);
	if (err) {
		return err;
	}

	COMMON_FIELDS_TO_RECORDS(f, connection, defaults, procedure);

	err = cs_reflector_config_get_default(config);
	err = err ?: cs_reflector_config_set_config_id(config, f.config_id);
	err = err ?: cs_reflector_config_set_connection(config, &connection);
	err = err ?: cs_reflector_config_set_default_settings(config, &defaults);
	err = err ?: cs_reflector_config_set_procedure(config, &procedure);
	return err;
}

#endif /* CONFIG_BT_CHANNEL_SOUNDING */

#if defined(APP_LIBS_RADIO_TEST)

int host_link_config_to_radio_test(const uint8_t *payload, size_t len,
                                   struct radio_test_mode_config *config) {
	struct cs_protocol_radio_tx_test_config_frame_t f;
	struct radio_test_mode_config result;
	int err;

	if (len != HOST_LINK_RADIO_TEST_PAYLOAD_SIZE) {
		return -EMSGSIZE;
	}
	PAYLOAD_TO_FRAME(f, payload);

	/* Rejects an unknown test type before any enum cast is used. */
	err = radio_test_mode_config_init(&result, (enum radio_test_mode_type)f.test_type);
	if (err) {
		return err;
	}
	if (f.phy > RADIO_TEST_MODE_PHY_IEEE802154_250K ||
	    f.pattern > RADIO_TEST_MODE_PATTERN_11111111) {
		return -EINVAL;
	}

	result.phy = (enum radio_test_mode_phy)f.phy;
	result.channel = f.channel;
	result.txpower = f.txpower;
	result.pattern = (enum radio_test_mode_pattern)f.pattern;
	result.packet_count = sys_le32_to_cpu(f.packet_count);
	result.sweep_start_channel = f.sweep_start_channel;
	result.sweep_end_channel = f.sweep_end_channel;
	result.sweep_delay_ms = sys_le32_to_cpu(f.sweep_delay_ms);
	result.duty_cycle = f.duty_cycle;
	result.tx_time_us = sys_le16_to_cpu(f.tx_time_us);
	result.sleep_time_us = sys_le16_to_cpu(f.sleep_time_us);
	result.fem.ramp_up_time_us = sys_le32_to_cpu(f.fem_ramp_up_time_us);
	result.fem.tx_power_control = f.fem_tx_power_control;

	err = radio_test_mode_config_validate(&result);
	if (err) {
		return err;
	}
	*config = result;
	return 0;
}

#endif /* APP_LIBS_RADIO_TEST */
