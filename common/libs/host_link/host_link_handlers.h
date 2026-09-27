/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief Handler table an application registers with host_link_init().
 *
 * The host link applies the command rules of cs_protocol/README.md (session,
 * frame sizes, BUSY / LINK_ACTIVE, staging, CRC) and calls a handler only for
 * work that belongs to the application. Handlers run on the host link thread,
 * one at a time. A handler may block until its operation completes (STOP,
 * LINK_DISCONNECT), but must return well within the host's 5 s timeout.
 */

#ifndef HOST_LINK_HANDLERS_H_
#define HOST_LINK_HANDLERS_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "host_link_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Application handlers. Every function pointer is required. */
struct host_link_handlers {
	/** Modes this build runs, bits @ref CS_PROTOCOL_MODE_BIT. */
	uint8_t supported_modes;
	/** Reported in CONNECT_RESPONSE. */
	uint32_t firmware_version;

	/** Current @ref cs_protocol_client_state. RUNNING makes configuration changes BUSY. */
	uint8_t (*client_state)(void);

	/** True while a Bluetooth link exists or scanning / advertising is active. */
	bool (*link_active)(void);

	/**
	 * Check the field values of a configuration payload for @p mode, e.g. with
	 * the cs_utils setters. Return OK, or VALUE_OUT_OF_RANGE with the errno.
	 * The payload is staged only when OK is returned.
	 */
	struct host_link_result (*validate_config)(uint8_t mode, const uint8_t *payload, size_t len);

	/**
	 * Take a complete, validated configuration into use. On OK the host link
	 * makes it the applied configuration; on any other result the previous
	 * applied configuration stays. Report CLIENT_STATE(CONFIGURED) from here.
	 */
	struct host_link_result (*apply)(const struct host_link_config_set *config);

	/**
	 * Start the applied configuration. Called only with an applied
	 * configuration whose CRC the host confirmed, and never while RUNNING.
	 */
	struct host_link_result (*start)(const struct host_link_config_set *config);

	/**
	 * Stop CS procedures or the radio test; the Bluetooth link is kept.
	 * Stopping a finite operation before it completed reports
	 * CLIENT_STATE(STOPPED, INTERRUPTED, -ECANCELED); a failed stop reports
	 * CLIENT_STATE(ERROR) with the error.
	 *
	 * Also called, with the session already closed, when the host session ends
	 * while SCANNING, ADVERTISING, LINK_CONNECTING, LINK_CONNECTED or RAS_READY:
	 * stop discovery, a connection attempt or a CS setup, and do nothing when
	 * none is in progress. Report the resulting state before returning, so a
	 * report with an error is held for the next CONNECT rather than racing it.
	 */
	struct host_link_result (*stop)(void);

	/**
	 * The host session ended while RUNNING (CLOSE_SESSION: -ECANCELED, host port
	 * lost: -ENOTCONN). Stop the operation like @ref stop and report
	 * CLIENT_STATE(STOPPED, INTERRUPTED, @p error), or CLIENT_STATE(ERROR) with
	 * the error of a failed stop. Called with the session already closed.
	 */
	void (*interrupt)(int error);

	/**
	 * Disconnect the Bluetooth link and stop scanning / advertising. Also called
	 * while RUNNING: stop the operation first, like @ref stop. Return once the
	 * link is down.
	 */
	struct host_link_result (*link_disconnect)(void);

	/** Optional discovery command handler; absent in radio builds. */
	struct host_link_result (*discovery)(uint16_t type, const uint8_t *payload);

	/**
	 * Optional: the host session opened (true, after CONNECT_RESPONSE was sent)
	 * or ended (false) by CLOSE_SESSION or a dropped port. On end it is called
	 * after @ref interrupt and after the applied configuration was cleared:
	 * return the application to its boot state (IDLE, no mode, defaults) so it
	 * waits for the next CONNECT.
	 */
	void (*session_changed)(bool active);

	/**
	 * Optional: the COMMAND_RESPONSE for @p request_type with @p result was
	 * queued. Reports sent from here follow the response, e.g. the radio RX
	 * statistics baseline after START.
	 */
	void (*response_sent)(uint16_t request_type, struct host_link_result result);
};

#ifdef __cplusplus
}
#endif

#endif /* HOST_LINK_HANDLERS_H_ */
