/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief Staging area, applied configuration and configuration CRC.
 *
 * Implements the configuration CRC rules of cs_protocol/README.md on raw payload bytes. Field
 * values are not checked here; the application validates them through
 * @ref host_link_handlers.validate_config. Not thread safe: the host link
 * thread is the only user.
 */

#ifndef HOST_LINK_CONFIG_STORE_H_
#define HOST_LINK_CONFIG_STORE_H_

#include <stddef.h>
#include <stdint.h>

#include "host_link_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Staged and applied configurations. */
struct host_link_config_store {
	/** Filled by SET_* commands, cleared by a successful apply. */
	struct host_link_config_set staged;
	/** The configuration reported in CONNECT_RESPONSE and replayed by GET_CONFIG. */
	struct host_link_config_set applied;
	/** True when @c applied holds a configuration. */
	bool applied_valid;
	/** CRC of @c applied; 0 when none. */
	uint32_t applied_crc32;
};

/** @brief Clear both the staging area and the applied configuration. */
void host_link_config_store_init(struct host_link_config_store *store);

/**
 * @brief Operation mode a configuration frame type belongs to.
 * @return A @ref cs_protocol_operation_mode, or -1 for other types.
 */
int host_link_config_mode_of_type(uint16_t type);

/**
 * @brief Configuration frame type and payload size for an operation mode.
 * @return The frame type, or 0 for an unknown mode.
 */
uint16_t host_link_config_type_of_mode(uint8_t mode, size_t *payload_len);

/**
 * @brief Stage an operation mode, discarding everything staged before.
 *
 * Whether the build supports the mode is the caller's check.
 */
void host_link_config_stage_mode(struct host_link_config_store *store, uint8_t mode);

/**
 * @brief Check that a configuration frame of @p type may be staged.
 * @return OK; BAD_STATE / MISSING_CONFIG without a staged mode;
 *         REJECTED / MODE_MISMATCH when @p type does not match the staged mode.
 */
struct host_link_result host_link_config_check_config(const struct host_link_config_store *store,
                                                      uint16_t type);

/**
 * @brief Stage a configuration payload after host_link_config_check_config().
 *
 * Staged patterns are kept. @p len must be the payload size for the staged mode.
 */
void host_link_config_stage_config(struct host_link_config_store *store, const uint8_t *payload,
                                   size_t len);

/**
 * @brief Check a SET_PERIPHERAL_PATTERNS payload against the staged mode.
 * @return OK; BAD_STATE / MISSING_CONFIG without a staged mode;
 *         REJECTED / MODE_MISMATCH for the radio test mode;
 *         REJECTED / VALUE_OUT_OF_RANGE for a count outside 1..8, a length
 *         outside 1..32, a NUL byte or invalid UTF-8;
 *         REJECTED / NONZERO_PADDING for non-zero bytes after a length or in
 *         unused slots.
 */
struct host_link_result host_link_config_check_patterns(const struct host_link_config_store *store,
                                                        const uint8_t *payload);

struct host_link_result host_link_config_check_device_name(const struct host_link_config_store *store,
                                                          const uint8_t *payload);

/**
 * @brief Check a SET_PEER_DATA payload against the staged mode.
 * @return OK; BAD_STATE / MISSING_CONFIG without a staged mode;
 *         REJECTED / MODE_MISMATCH outside the CS initiator mode;
 *         REJECTED / VALUE_OUT_OF_RANGE for any value but NONE (RAS real-time
 *         is expressed by omitting the frame).
 */
struct host_link_result host_link_config_check_peer_data(const struct host_link_config_store *store,
                                                         const uint8_t *payload);

/** @brief Stage a peer data payload after host_link_config_check_peer_data(). */
void host_link_config_stage_peer_data(struct host_link_config_store *store, const uint8_t *payload);

/**
 * @brief Check a SET_T_PM payload against the staged mode.
 * @return OK; BAD_STATE / MISSING_CONFIG without a staged mode;
 *         REJECTED / MODE_MISMATCH outside the CS initiator mode;
 *         REJECTED / VALUE_OUT_OF_RANGE for any value but 20 or 40 (10 us is
 *         expressed by omitting the frame).
 */
struct host_link_result host_link_config_check_t_pm(const struct host_link_config_store *store,
                                                    const uint8_t *payload);

/** @brief Stage a T_PM payload after host_link_config_check_t_pm(). */
void host_link_config_stage_t_pm(struct host_link_config_store *store, const uint8_t *payload);

/**
 * @brief Check a SET_LOG_CONFIG payload.
 * @return OK; BAD_STATE / MISSING_CONFIG without a staged mode;
 *         REJECTED / VALUE_OUT_OF_RANGE for a level above DEBUG or for the
 *         default levels (they are expressed by omitting the frame).
 */
struct host_link_result host_link_config_check_log_config(const struct host_link_config_store *store,
                                                          const uint8_t *payload);

/** @brief Stage a log configuration payload after host_link_config_check_log_config(). */
void host_link_config_stage_log_config(struct host_link_config_store *store, const uint8_t *payload);

/** @brief Stage a patterns payload after host_link_config_check_patterns(). */
void host_link_config_stage_patterns(struct host_link_config_store *store, const uint8_t *payload);

/**
 * @brief Check that the staged set is a complete configuration.
 * @return OK; REJECTED / MISSING_CONFIG without a mode and matching
 *         configuration; BAD_STATE / MISSING_PATTERNS for a GAP central CS
 *         configuration without patterns; REJECTED / VALUE_OUT_OF_RANGE with
 *         -EINVAL for reflector data none without the IPT request in the
 *         initiator configuration.
 */
struct host_link_result host_link_config_check_apply(const struct host_link_config_store *store);

/**
 * @brief Make the staged set the applied configuration and clear the staging area.
 *
 * Call only after host_link_config_check_apply() and a successful application
 * apply. Patterns staged in the radio test mode are never part of a set, as
 * host_link_config_check_patterns() refuses them.
 */
void host_link_config_commit(struct host_link_config_store *store);

/**
 * @brief CRC-32 over the set's payloads in CRC order (cs_protocol/README.md).
 * @return The CRC, or 0 when the set has no mode or configuration.
 */
uint32_t host_link_config_crc32(const struct host_link_config_set *set);

#ifdef __cplusplus
}
#endif

#endif /* HOST_LINK_CONFIG_STORE_H_ */
