/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief Command results and configuration sets shared by the host link parts.
 *
 * No Zephyr headers, so the configuration store builds in native tests.
 */

#ifndef HOST_LINK_TYPES_H_
#define HOST_LINK_TYPES_H_

#include <stdbool.h>
#include <stdint.h>

#include "cs_protocol/cs_protocol_packets.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Payload bytes of a fixed-size frame struct. */
#define HOST_LINK_PAYLOAD_SIZE(frame_struct) (sizeof(frame_struct) - CS_PROTOCOL_OVERHEAD)

/** SET_OPERATION_MODE payload (1). */
#define HOST_LINK_MODE_PAYLOAD_SIZE HOST_LINK_PAYLOAD_SIZE(struct cs_protocol_operation_mode_frame_t)
/** SET_CS_INITIATOR_CONFIG payload (57). */
#define HOST_LINK_INITIATOR_PAYLOAD_SIZE HOST_LINK_PAYLOAD_SIZE(struct cs_protocol_cs_initiator_config_frame_t)
/** SET_CS_REFLECTOR_CONFIG payload (34). */
#define HOST_LINK_REFLECTOR_PAYLOAD_SIZE HOST_LINK_PAYLOAD_SIZE(struct cs_protocol_cs_reflector_config_frame_t)
/** SET_RADIO_TX_TEST_CONFIG payload (25). */
#define HOST_LINK_RADIO_TEST_PAYLOAD_SIZE HOST_LINK_PAYLOAD_SIZE(struct cs_protocol_radio_tx_test_config_frame_t)
/** SET_PERIPHERAL_PATTERNS payload (265). */
#define HOST_LINK_PATTERNS_PAYLOAD_SIZE HOST_LINK_PAYLOAD_SIZE(struct cs_protocol_peripheral_patterns_frame_t)
#define HOST_LINK_DEVICE_NAME_PAYLOAD_SIZE 33U
/** SET_PEER_DATA payload (1). */
#define HOST_LINK_PEER_DATA_PAYLOAD_SIZE HOST_LINK_PAYLOAD_SIZE(struct cs_protocol_peer_data_frame_t)
/** SET_T_PM payload (1). */
#define HOST_LINK_T_PM_PAYLOAD_SIZE HOST_LINK_PAYLOAD_SIZE(struct cs_protocol_t_pm_frame_t)
/** SET_LOG_CONFIG payload (2). */
#define HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE HOST_LINK_PAYLOAD_SIZE(struct cs_protocol_log_config_frame_t)
/** Largest configuration frame payload (the initiator configuration). */
#define HOST_LINK_CONFIG_PAYLOAD_MAX HOST_LINK_INITIATOR_PAYLOAD_SIZE

/** Outcome of one command, as carried in COMMAND_RESPONSE. */
struct host_link_result {
	/** One of @ref cs_protocol_status. */
	uint8_t status;
	/** One of @ref cs_protocol_reject_reason. */
	uint8_t reason;
	/** Negative errno from a setter, apply, start or stop call; 0 otherwise. */
	int32_t error;
};

/** Command accepted and completed. */
#define HOST_LINK_RESULT_OK ((struct host_link_result){.status = CS_PROTOCOL_STATUS_OK})

/** Result with @p status_ and @p reason_ and no errno. */
#define HOST_LINK_RESULT(status_, reason_) \
	((struct host_link_result){.status = (status_), .reason = (reason_)})

/** A field value was refused by a setter or range check. */
#define HOST_LINK_RESULT_OUT_OF_RANGE(err_)                                               \
	((struct host_link_result){.status = CS_PROTOCOL_STATUS_REJECTED,                    \
	                          .reason = CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE, .error = (err_)})

/** An apply, start or stop call failed with @p err_. */
#define HOST_LINK_RESULT_FAILED(err_) \
	((struct host_link_result){.status = CS_PROTOCOL_STATUS_FAILED, .error = (err_)})

/**
 * @brief One configuration: operation mode, configuration payload and the optional payloads.
 *
 * Payloads are stored exactly as received, so the configuration CRC can be
 * recomputed from them (cs_protocol/README.md, Configuration CRC).
 */
struct host_link_config_set {
	/** True once SET_OPERATION_MODE was received. */
	bool has_mode;
	/** One of @ref cs_protocol_operation_mode. */
	uint8_t mode;
	/** Configuration payload bytes; 0 when none. */
	uint8_t config_len;
	/** Configuration frame payload for @c mode. */
	uint8_t config[HOST_LINK_CONFIG_PAYLOAD_MAX];
	/** True when peripheral patterns are part of the set. */
	bool has_patterns;
	bool has_device_name;
	uint8_t device_name[HOST_LINK_DEVICE_NAME_PAYLOAD_SIZE];
	/** SET_PERIPHERAL_PATTERNS payload. */
	uint8_t patterns[HOST_LINK_PATTERNS_PAYLOAD_SIZE];
	/** True when SET_PEER_DATA is part of the set; without it the initiator uses RAS real-time. */
	bool has_peer_data;
	/** SET_PEER_DATA payload: one of @ref cs_protocol_peer_data. */
	uint8_t peer_data;
	/** True when SET_T_PM is part of the set; without it the initiator prefers 10 us. */
	bool has_t_pm;
	/** SET_T_PM payload: one of @ref cs_protocol_t_pm. */
	uint8_t t_pm_us;
	/** True when SET_LOG_CONFIG is part of the set; without it the log levels are the defaults. */
	bool has_log_config;
	/** SET_LOG_CONFIG payload: console level, protocol level. */
	uint8_t log_config[HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE];
};

#ifdef __cplusplus
}
#endif

#endif /* HOST_LINK_TYPES_H_ */
