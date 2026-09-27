/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief Names of protocol values, for LOG_MESSAGE text.
 *
 * No Zephyr headers, so the tables build in native tests. Every function
 * returns a static string; unknown values give "?".
 */

#ifndef HOST_LINK_NAMES_H_
#define HOST_LINK_NAMES_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** @brief Name of a @ref cs_protocol_client_state, e.g. "RUNNING". */
const char *host_link_state_name(uint8_t state);

/** @brief Name of a @ref cs_protocol_operation_mode, or "NONE". */
const char *host_link_mode_name(uint8_t mode);

/** @brief Name of a @ref cs_protocol_status, e.g. "BAD_STATE". */
const char *host_link_status_name(uint8_t status);

/** @brief Name of a @ref cs_protocol_reject_reason, e.g. "LINK_ACTIVE". */
const char *host_link_reason_name(uint8_t reason);

/** @brief Name of a host command type, e.g. "APPLY_CONFIG". */
const char *host_link_command_name(uint16_t type);

#ifdef __cplusplus
}
#endif

#endif /* HOST_LINK_NAMES_H_ */
