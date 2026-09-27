/* SPDX-License-Identifier: MIT */
/**
 * @file cs_role.h
 * @brief Connection, CS and RAS sequencing for one CS initiator or reflector.
 *
 * Shared by cs_client, the hostless applications and cs_reflector_tag; knows
 * nothing about the host protocol. The application registers callbacks and
 * drives the library with a link (scan/advertise, connect, encrypt) and a role
 * (setup, run, stop).
 *
 * @section cs_role_contexts Execution contexts
 *
 * - All role and link state is owned by one cs_roles thread. Bluetooth
 *   callbacks hand it their parameters; API functions post a request and wait
 *   for its result.
 * - Control callbacks (@c state, @c capabilities, @c configuration,
 *   @c procedure, @c fae_table, @c ras_data_lost) are delivered in order from
 *   the cs_roles event thread. Control events are never dropped. A callback
 *   may call the API: from the event thread, requests are posted without
 *   waiting and return 0; their outcome arrives as events.
 * - Subevent callbacks (@c subevent_begin, @c subevent_step, @c subevent_end)
 *   and @c scan_result are called in Bluetooth context and must not block.
 *   Subevents are streamed straight from the controller or RAS data, without
 *   a copy: a subevent may therefore arrive before an earlier control event
 *   (e.g. RUNNING) has been delivered.
 *
 * Tested natively in tests/cs_roles (run.sh, needs ZEPHYR_BASE): the role state
 * machine against logged Bluetooth commands, the event queue and subevent streaming.
 */
#ifndef CS_ROLE_H_
#define CS_ROLE_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <zephyr/bluetooth/addr.h>
#include <zephyr/kernel.h>
#include <cs_utils/cs_capabilities.h>
#include <cs_utils/cs_config.h>
#include <cs_utils/cs_reports.h>
#include <cs_utils/cs_results.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Link and role states reported through @ref cs_role_callbacks.state. */
enum cs_role_state {
	/** Scanning (discovery, or for a name pattern). */
	CS_ROLE_STATE_SCANNING,
	/** Advertising, waiting for a central. */
	CS_ROLE_STATE_ADVERTISING,
	/** Connection being created. */
	CS_ROLE_STATE_LINK_CONNECTING,
	/** Connected; encryption follows. */
	CS_ROLE_STATE_LINK_CONNECTED,
	/** Link encrypted; a role can run. */
	CS_ROLE_STATE_LINK_ENCRYPTED,
	/**
	 * Initiator: RAS subscribed (not reported without RAS, reflector data
	 * none). Reflector: waiting for the initiator.
	 */
	CS_ROLE_STATE_RAS_READY,
	/** Procedures enabled. */
	CS_ROLE_STATE_RUNNING,
	/** Procedures ended; @c stop_reason says why. */
	CS_ROLE_STATE_STOPPED,
	/** The link was lost without a local request. */
	CS_ROLE_STATE_LINK_LOST,
	/** Link released on request (cs_role_link_disconnect()). */
	CS_ROLE_STATE_LINK_DISCONNECTED,
	/** A step failed; @c failure says which. */
	CS_ROLE_STATE_ERROR,
};

/** Why procedures stopped (@ref CS_ROLE_STATE_STOPPED). */
enum cs_role_stop_reason {
	CS_ROLE_STOP_NONE,
	/** cs_role_stop(), or setup cancelled by it. */
	CS_ROLE_STOP_HOST,
	/** Initiator: the controller completed max_procedure_count. */
	CS_ROLE_STOP_COMPLETE,
	/**
	 * Reflector: the initiator disabled the procedures. The reflector stays
	 * started and reports RAS_READY again, waiting for the next run.
	 */
	CS_ROLE_STOP_PEER,
	/** cs_role_interrupt(); @c error is the interrupting error. */
	CS_ROLE_STOP_INTERRUPTED,
	/** The link was lost while running. */
	CS_ROLE_STOP_LINK_LOST,
};

/** Step that failed (@ref CS_ROLE_STATE_ERROR). */
enum cs_role_failure_stage {
	CS_ROLE_FAILURE_NONE,
	/** Scan, advertising or connection creation. */
	CS_ROLE_FAILURE_CONNECT,
	/** Link encryption (pairing). */
	CS_ROLE_FAILURE_LINK_SECURITY,
	/** RAS instance allocation, discovery, features or subscription. */
	CS_ROLE_FAILURE_RAS_DISCOVERY,
	/** The peer's RAS does not support real-time ranging data. */
	CS_ROLE_FAILURE_RAS_NO_REALTIME,
	/** Local or remote capabilities, default settings. */
	CS_ROLE_FAILURE_CAPABILITIES,
	/** CS configuration creation or procedure parameters. */
	CS_ROLE_FAILURE_CONFIG,
	/** CS security. */
	CS_ROLE_FAILURE_SECURITY,
	/** Procedure enable or disable. */
	CS_ROLE_FAILURE_PROCEDURE,
	/**
	 * Initiator with reflector data none: the peer does not support IPT, or
	 * the created configuration does not enable it. The link is not restarted
	 * for it (@c auto_restart), since the same peer would fail again.
	 */
	CS_ROLE_FAILURE_PEER_IPT,
	/**
	 * Initiator: @c preferred_peer_antenna names a reflector antenna beyond
	 * the count in the peer's capabilities. Not restarted either.
	 */
	CS_ROLE_FAILURE_PEER_ANTENNA,
};

/** Link to establish (cs_role_link_start()). */
struct cs_role_link_params {
	/** True: GAP central (connect); false: GAP peripheral (advertise). */
	bool central;
	/** Requested connection parameters; copied. */
	struct cs_config_connection connection;
	/** Central: peer to connect to, or NULL to scan for @c patterns. */
	const bt_addr_le_t *peer;
	/**
	 * Central without @c peer: name prefixes to connect to. With none, the
	 * first connectable device advertising the Ranging Service is used. The
	 * strings must stay valid while the link is started.
	 */
	const char *const *patterns;
	/** Entries in @c patterns. */
	size_t pattern_count;
	/** Peripheral: include the Ranging Service UUID in the advertising data. */
	bool advertise_ras_uuid;
	/**
	 * Restart the link after it is lost or fails to come up (hostless
	 * applications). cs_role_link_disconnect() ends the restarts.
	 */
	bool auto_restart;
};

/** One advertising report, for discovery (cs_role_scan_start()). */
struct cs_role_scan_result {
	bt_addr_le_t address;
	int8_t rssi;
	bool connectable;
	/** Name bytes, not terminated; @c name_len 0 when none. */
	const uint8_t *name;
	uint8_t name_len;
	/** True for a complete name, false for a shortened one. */
	bool name_complete;
};

struct cs_role_callbacks {
	/** State change. @p hci_status and @p error describe failures and losses. */
	void (*state)(enum cs_role_state state, enum cs_role_failure_stage failure,
	              enum cs_role_stop_reason stop_reason, uint8_t hci_status, int error);
	/**
	 * Negotiated ACL connection parameters and ATT MTU, initially and after every
	 * update. Called from Bluetooth context and must not block; @p params is
	 * temporary and @p mtu is in bytes.
	 */
	void (*connection_params)(const struct cs_config_connection *params, uint16_t mtu);
	/** Advertising report while scanning for discovery; Bluetooth context. Optional. */
	void (*scan_result)(const struct cs_role_scan_result *result);
	/** Local capabilities (source local) and the peer's (source remote). */
	void (*capabilities)(const struct cs_capabilities *record);
	/** CS configuration complete. */
	void (*configuration)(const struct cs_config_complete *record);
	/** Procedure enable complete. */
	void (*procedure)(const struct cs_procedure_enable_complete *record);
	/**
	 * Begin one subevent: local HCI results (@c header->role is the local
	 * role) or the reflector's results from RAS (initiator only, @c role
	 * reflector). @c header->num_steps steps with @p num_tones tones in
	 * total follow; @c header->size is their total record size. Nonzero
	 * skips the steps; subevent_end() is still called. Bluetooth context.
	 */
	int (*subevent_begin)(const struct cs_subevent *header, uint16_t num_tones);
	/** One decoded step record of the open subevent. Bluetooth context. */
	void (*subevent_step)(const struct cs_step_header *step);
	/**
	 * End of the open subevent. @p complete is false when fewer steps than
	 * the controller or peer reported could be decoded.
	 */
	void (*subevent_end)(bool complete);
	/**
	 * Remote FAE table read completion (initiator). @p entries is NULL on
	 * failure. ppm = entry / @p lsb_denominator.
	 */
	void (*fae_table)(uint8_t hci_status, uint8_t lsb_denominator, const int8_t *entries);
	/**
	 * The reflector's data of a procedure is missing or incomplete.
	 * @p procedure_counter is 16 bits when the procedure is known, otherwise
	 * the 12-bit RAS ranging counter. @p error: -ENOENT no local procedure
	 * matched, -ENOBUFS the next procedure started first, -ETIMEDOUT not
	 * received in time after procedures stopped, -EBADMSG or -ENOMEM
	 * incomplete parse, or the RAS error.
	 */
	void (*ras_data_lost)(uint16_t procedure_counter, int error);
	/**
	 * Initiator: the controller completed max_procedure_count. Delivered right
	 * before STOPPED(COMPLETE). @p procedures_completed counts the procedures
	 * of the run whose done status was complete. Optional.
	 */
	void (*procedures_complete)(uint16_t procedures_completed);
};

/**
 * @brief Register callbacks and start the cs_roles threads. Call once, after bt_enable().
 * @retval -EALREADY Already initialized.
 */
int cs_role_init(const struct cs_role_callbacks *callbacks);

/**
 * @brief Scan for discovery: every report goes to @c scan_result, nothing connects.
 * @retval -EBUSY A link is active.
 */
int cs_role_scan_start(void);

/**
 * @brief Scan/advertise and connect, then encrypt the link.
 *
 * Stops a discovery scan first. Progress arrives as SCANNING / ADVERTISING,
 * LINK_CONNECTING, LINK_CONNECTED, LINK_ENCRYPTED; failures as ERROR with
 * @ref CS_ROLE_FAILURE_CONNECT or @ref CS_ROLE_FAILURE_LINK_SECURITY.
 *
 * @retval -EBUSY Already connecting or connected.
 * @retval -EINVAL Invalid parameters.
 * @return Other negative error from the Bluetooth stack.
 */
int cs_role_link_start(const struct cs_role_link_params *params);

/**
 * @brief Stop scanning and advertising, disconnect and release RAS resources.
 *
 * A running role reports STOPPED(HOST) first. Ends automatic restarts.
 * @retval 0 No link remains.
 * @retval -ETIMEDOUT The disconnection did not complete within @p timeout.
 */
int cs_role_link_disconnect(k_timeout_t timeout);

/** @brief True while scanning, advertising, connecting or connected. */
bool cs_role_link_active(void);

/**
 * @brief Run the CS initiator role on the link.
 *
 * Waits for link encryption, then RAS discovery and real-time subscription,
 * capabilities, FAE table, configuration, CS security and procedure enable.
 * Steps already done on this link are skipped, so a START after STOP only
 * re-enables procedures. Frees a reflector's RAS instance first.
 *
 * With reflector data none (@c peer_data @ref CS_CONFIG_PEER_DATA_NONE) there
 * is no RAS discovery, subscription or RAS_READY, and only local subevents
 * are streamed. The peer's capabilities must report IPT in the reflector and
 * the created configuration must enable it; otherwise the setup fails with
 * @ref CS_ROLE_FAILURE_PEER_IPT and -ENOTSUP. A @c preferred_peer_antenna bit
 * above the peer's antenna count fails at remote capabilities with
 * @ref CS_ROLE_FAILURE_PEER_ANTENNA and -ERANGE: some controllers switch to the
 * named antenna unchecked. STOP and a completed
 * @c max_procedure_count end the run at the disable event, without waiting
 * for RAS data.
 *
 * @retval 0 Setup started; results arrive as events.
 * @retval -EINVAL @p config is NULL or fails cs_initiator_config_check_peer_data().
 * @retval -ENOTCONN No link.
 * @retval -EBUSY A role is being set up or running.
 */
int cs_role_start_initiator(const struct cs_initiator_config *config);

/**
 * @brief Run the CS reflector role on the link.
 *
 * Allocates the RAS responder, applies default settings, reads the remote
 * capabilities and waits for the initiator's configuration and procedures.
 * @return As cs_role_start_initiator().
 */
int cs_role_start_reflector(const struct cs_reflector_config *config);

/**
 * @brief Stop procedures, or cancel a setup, keeping the link.
 *
 * The initiator also waits for the reflector's data of the last procedure,
 * unless it receives no reflector data.
 * @retval 0 Stopped (STOPPED(HOST) reported), or nothing to stop.
 * @retval -ETIMEDOUT Procedures stopped, but the last procedure's RAS data did
 *         not arrive in time (reported through @c ras_data_lost). Never
 *         returned without RAS.
 * @retval -ETIME The controller did not confirm the disable; ERROR(PROCEDURE) reported.
 * @retval -ENOTCONN The link was lost meanwhile.
 */
int cs_role_stop(void);

/**
 * @brief Stop a running role because of @p error (STOPPED(INTERRUPTED, error)).
 *
 * Waits like cs_role_stop(). Does nothing when not running.
 */
void cs_role_interrupt(int error);

/** @brief True while procedures are enabled. */
bool cs_role_running(void);

#ifdef __cplusplus
}
#endif

#endif /* CS_ROLE_H_ */
