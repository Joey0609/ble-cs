/* SPDX-License-Identifier: MIT */
#ifndef CLIENT_STATE_H_
#define CLIENT_STATE_H_

#include <stdbool.h>
#include <stdint.h>

/**
 * @file
 * @brief Client state and applied operation mode, reported as CLIENT_STATE.
 *
 * Thread context only. Every change is reported to the host while holding the
 * state lock, so the host sees changes in the order they happened: a
 * CLIENT_STATE frame followed by a LOG_MESSAGE naming the old and new state
 * (level warning for LINK_LOST, ERROR and any change with an error).
 *
 * A change with a non-zero error that could not be reported (no host session)
 * is reported again when the next session opens, unless the host has seen a
 * newer state in between.
 */

/** @brief Current @ref cs_protocol_client_state. */
uint8_t client_state_get(void);

/** @brief Applied operation mode, or @ref CS_PROTOCOL_MODE_NONE. */
uint8_t client_state_mode(void);

/** @brief Record the applied operation mode; no report. */
void client_state_set_mode(uint8_t mode);

/**
 * @brief Change the state and report it.
 *
 * @param state      One of @ref cs_protocol_client_state.
 * @param reason     One of @ref cs_protocol_reject_reason.
 * @param hci_status HCI status behind the change; 0 when none.
 * @param error      Negative errno when an operation ended abnormally; 0 otherwise.
 */
void client_state_set(uint8_t state, uint8_t reason, uint8_t hci_status, int32_t error);

/**
 * @brief Change the state and report it only if it is still @p from.
 * @return True when the state changed.
 */
bool client_state_change(uint8_t from, uint8_t to, uint8_t reason, int32_t error);

/**
 * @brief host_link session_changed handler: on open, report an undelivered
 * change with an error; ending a session preserves device state and mode.
 */
void client_state_session_changed(bool active);

#endif /* CLIENT_STATE_H_ */
