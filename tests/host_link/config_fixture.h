/* SPDX-License-Identifier: MIT */
/* Configuration shared by the host link native tests and the CRC vectors computed from it. */
#ifndef TEST_HOST_LINK_CONFIG_FIXTURE_H_
#define TEST_HOST_LINK_CONFIG_FIXTURE_H_

#include "host_link/host_link_types.h"

/* Shared with python/tests/test_protocol.py. */
#define CONFIG_CRC_VECTOR UINT32_C(0xb61d36f1)
#define CONFIG_CRC_VECTOR_NO_PATTERNS UINT32_C(0x7a403314)
/* The initiator configuration with IPT requested, the patterns and SET_PEER_DATA(NONE). */
#define CONFIG_CRC_VECTOR_PEER_DATA UINT32_C(0x8252106b)
/* The initiator configuration, the patterns and SET_LOG_CONFIG(console DEBUG, protocol INFO). */
#define CONFIG_CRC_VECTOR_LOG_CONFIG UINT32_C(0x7ea17539)
/* The initiator configuration, the patterns and SET_T_PM(40). */
#define CONFIG_CRC_VECTOR_T_PM UINT32_C(0x2dbb98cb)
/* The same with SET_LOG_CONFIG(console DEBUG, protocol INFO) after SET_T_PM. */
#define CONFIG_CRC_VECTOR_T_PM_LOG_CONFIG UINT32_C(0x6a66be09)

#define PAYLOAD(frame) ((const uint8_t *)&(frame) + CS_PROTOCOL_HEADER_SIZE)

static const struct cs_protocol_cs_initiator_config_frame_t initiator = {
	.gap_role = CS_PROTOCOL_GAP_CENTRAL,
	.config_id = 1,
	.connection_interval_min = 24,
	.connection_interval_max = 24,
	.connection_latency = 0,
	.connection_timeout = 400,
	.cs_sync_antenna_selection = CS_PROTOCOL_CONFIG_SYNC_ANTENNA_REPETITIVE,
	.max_tx_power = 20,
	.max_procedure_len = 0x3e80,
	.min_procedure_interval = 10,
	.max_procedure_interval = 20,
	.max_procedure_count = 0,
	.min_subevent_len = 60000,
	.max_subevent_len = 70000,
	.tone_antenna_config_selection = CS_PROTOCOL_CONFIG_TONE_ANTENNA_A2_B2,
	.phy = CS_PROTOCOL_CONFIG_PROCEDURE_PHY_2M,
	.tx_power_delta = CS_PROTOCOL_CONFIG_TX_POWER_DELTA_NONE,
	.preferred_peer_antenna = CS_PROTOCOL_CONFIG_PEER_ANTENNA_1 | CS_PROTOCOL_CONFIG_PEER_ANTENNA_2,
	.snr_control_initiator = CS_PROTOCOL_CONFIG_SNR_CONTROL_NOT_USED,
	.snr_control_reflector = CS_PROTOCOL_CONFIG_SNR_CONTROL_NOT_USED,
	.creation_mode = CS_PROTOCOL_CONFIG_MODE_3_SUB_MODE_2,
	.creation_min_main_mode_steps = 2,
	.creation_max_main_mode_steps = 5,
	.creation_main_mode_repetition = 1,
	.creation_mode_0_steps = 3,
	.creation_rtt_type = CS_PROTOCOL_CONFIG_RTT_TYPE_32_BIT_SOUNDING,
	.creation_cs_sync_phy = CS_PROTOCOL_CONFIG_SYNC_PHY_2M,
	.creation_channel_map = {0xfc, 0xff, 0x7f, 0xfc, 0xff, 0xff, 0xff, 0xff, 0xff, 0x1f},
	.creation_channel_map_repetition = 1,
	.creation_channel_selection_type = CS_PROTOCOL_CONFIG_CHSEL_TYPE_3B,
	.creation_ch3c_shape = CS_PROTOCOL_CONFIG_CH3C_SHAPE_HAT,
	.creation_ch3c_jump = 2,
	.creation_cs_enhancements_1 = 0,
	.creation_context = CS_PROTOCOL_CONFIG_CREATION_CONTEXT_LOCAL_AND_REMOTE,
};

static const struct cs_protocol_peripheral_patterns_frame_t patterns = {
	.count = 2,
	.lengths = {12, 3},
	.patterns = {"CS-Reflector", "nRF"},
};

#endif /* TEST_HOST_LINK_CONFIG_FIXTURE_H_ */
