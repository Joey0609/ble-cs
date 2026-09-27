/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief Binary protocol link to the host over USB CDC ACM.
 *
 * Receives host commands, applies the command rules of cs_protocol/README.md,
 * calls the application's @ref host_link_handlers and sends the responses.
 * Reports are sent with the functions in host_link_reports.h.
 */

#ifndef HOST_LINK_H_
#define HOST_LINK_H_

#include <stdbool.h>

#include "host_link_handlers.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Start the transport and the host link thread.
 *
 * @param handlers Handler table; must stay valid for the lifetime of the link.
 * @retval 0 Running.
 * @retval -EINVAL A required handler is missing.
 * @retval -EALREADY Already started.
 * @return Other negative error from the transport.
 */
int host_link_init(const struct host_link_handlers *handlers);

/** @brief Called from the system work queue each time the host opens the port. */
typedef void (*host_link_port_opened_t)(void);

/**
 * @brief Initialize binary report transport without starting host commands.
 *
 * @param port_opened Optional; with CONFIG_APP_HOST_LINK_DTR it is called once
 *                    each time DTR rises (polled every
 *                    CONFIG_APP_HOST_LINK_DTR_POLL_MS), after stale transmit
 *                    bytes were discarded, so it can resend reports a host that
 *                    opened the port late has missed. May send reports. NULL,
 *                    or no DTR: never called.
 * @retval 0 Running.
 * @retval -EALREADY Already started.
 * @return Other negative error from the transport.
 */
int host_link_report_only_init(host_link_port_opened_t port_opened);

/** @brief True while reports are enabled or a host session is open. */
bool host_link_session_active(void);

#ifdef __cplusplus
}
#endif

#endif /* HOST_LINK_H_ */
