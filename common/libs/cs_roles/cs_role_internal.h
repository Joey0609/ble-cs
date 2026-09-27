/* SPDX-License-Identifier: MIT */
/* Shared between the cs_roles sources; not part of the API.
 *
 * Contexts:
 * - Role thread (cs_role_core.c): owns struct cs_role_ctx. Every request and
 *   every Bluetooth completion arrives as a struct cs_role_msg.
 * - Bluetooth context: connection, CS, RAS and scan callbacks. They post
 *   messages, stream subevents and own struct cs_role_data, the data path.
 * - Event thread (cs_role_events.c): delivers control callbacks.
 */
#ifndef CS_ROLE_INTERNAL_H_
#define CS_ROLE_INTERNAL_H_

#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>

#include "cs_role.h"

enum cs_role_kind {
	CS_ROLE_KIND_NONE,
	CS_ROLE_KIND_INITIATOR,
	CS_ROLE_KIND_REFLECTOR,
};

enum cs_role_stage {
	CS_ROLE_STAGE_IDLE,
	CS_ROLE_STAGE_WAIT_ENCRYPTION,
	CS_ROLE_STAGE_RAS_DISCOVERY,
	CS_ROLE_STAGE_RAS_FEATURES,
	CS_ROLE_STAGE_REMOTE_CAPABILITIES,
	CS_ROLE_STAGE_FAE,
	CS_ROLE_STAGE_CONFIG,
	CS_ROLE_STAGE_SECURITY,
	/* Reflector: waiting for the initiator's configuration; no deadline. */
	CS_ROLE_STAGE_WAIT_PEER_CONFIG,
	/* Initiator: enable requested. Reflector: waiting for the initiator; no deadline. */
	CS_ROLE_STAGE_ENABLE,
	CS_ROLE_STAGE_RUNNING,
	/* Disable requested, or procedures ended by the controller or peer. */
	CS_ROLE_STAGE_STOPPING,
	/* Initiator: procedures disabled, waiting for the last RAS data. */
	CS_ROLE_STAGE_STOP_RAS,
};

enum cs_role_link_phase {
	CS_ROLE_LINK_IDLE,
	CS_ROLE_LINK_DISCOVERY,
	CS_ROLE_LINK_SCANNING,
	CS_ROLE_LINK_ADVERTISING,
	CS_ROLE_LINK_CONNECTING,
	CS_ROLE_LINK_CONNECTED,
};

enum cs_role_msg_type {
	/* API requests. */
	CS_ROLE_MSG_SCAN_START,
	CS_ROLE_MSG_LINK_START,
	CS_ROLE_MSG_LINK_DISCONNECT,
	CS_ROLE_MSG_START_INITIATOR,
	CS_ROLE_MSG_START_REFLECTOR,
	CS_ROLE_MSG_STOP,
	CS_ROLE_MSG_INTERRUPT,
	/* Bluetooth completions. */
	CS_ROLE_MSG_CONNECTED,
	CS_ROLE_MSG_DISCONNECTED,
	CS_ROLE_MSG_SECURITY_CHANGED,
	CS_ROLE_MSG_SCAN_MATCH,
	CS_ROLE_MSG_RAS_DISCOVERED,
	CS_ROLE_MSG_RAS_FEATURES,
	CS_ROLE_MSG_REMOTE_CAPABILITIES,
	CS_ROLE_MSG_FAE,
	CS_ROLE_MSG_CONFIG,
	CS_ROLE_MSG_CS_SECURITY,
	CS_ROLE_MSG_PROCEDURE,
	CS_ROLE_MSG_RAS_RESOLVED,
};

struct cs_role_msg {
	uint8_t type;
	/* HCI status of a completion. */
	uint8_t status;
	int err;
	/* Referenced by the poster; the role thread releases it. */
	struct bt_conn *conn;
	union {
		struct cs_initiator_config initiator;
		struct cs_reflector_config reflector;
		struct {
			struct cs_role_link_params params;
			bt_addr_le_t peer;
		} link;
		struct {
			uint8_t config_id;
			uint8_t state;
			uint8_t rtt_type;
			bool fae_needed;
			/* Remote capabilities: IPT in the reflector. Configuration: IPT enabled. */
			bool ipt;
			/* Remote capabilities: the peer's antenna count. */
			uint8_t num_antennas;
		} cs;
		bt_addr_le_t addr;
		uint32_t features;
		uint8_t security_level;
		k_timeout_t timeout;
		int error;
	};
	/* Requests: given when the request is complete, with *result set. NULL: nobody waits. */
	struct k_sem *done;
	int *result;
};

/* Role thread state. Only the role thread reads or writes it. */
struct cs_role_ctx {
	const struct cs_role_callbacks *callbacks;

	/* Link. */
	enum cs_role_link_phase link;
	struct bt_conn *conn;
	struct bt_conn *connecting;
	bool encrypted;
	struct cs_role_link_params params;
	bt_addr_le_t peer;
	/* A link is wanted: restarts apply. */
	bool link_requested;
	bool disconnect_requested;
	/* An ERROR already explains the disconnection in progress. */
	bool link_failed;
	bool restart_pending;
	k_timepoint_t restart_at;
	struct k_sem *disconnect_done;
	int *disconnect_result;
	k_timepoint_t disconnect_deadline;

	/* Role. */
	enum cs_role_kind role;
	enum cs_role_stage stage;
	bool deadline_set;
	k_timepoint_t deadline;
	struct cs_initiator_config initiator;
	struct cs_reflector_config reflector;

	/* Per-link progress, cleared when the link goes down or setup fails. */
	bool rreq_allocated;
	bool rreq_subscribed;
	bool rrsp_allocated;
	bool capabilities_read;
	bool fae_read;
	bool config_created;
	bool security_enabled;
	/* Reflector: the initiator created a configuration on this link. */
	bool peer_config;
	uint8_t peer_config_id;

	/* Stop. */
	bool stop_requested;
	enum cs_role_stop_reason stop_reason;
	int stop_error;
	int stop_outcome;
	struct k_sem *stop_done;
	int *stop_result;
};

/* Data path state, written in Bluetooth context. */
#define CS_ROLE_RAS_PENDING BIT(16)
#define CS_ROLE_RAS_CLAIMED BIT(17)

struct cs_role_data {
	/* enum cs_role_kind of the started role; set by the role thread. */
	atomic_t role;
	/* Initiator: the reflector's data arrives through RAS; set by the role thread. */
	atomic_t ras;
	/* Bit per configuration ID whose RTT type is known. */
	atomic_t layouts;
	uint8_t rtt_types[CS_CONFIG_ID_MAX + 1];
	struct cs_subevent_counter counter;
	/* CS_ROLE_RAS_PENDING | procedure counter of a completed local procedure
	 * whose RAS data has not been matched or declared lost. The role thread
	 * gives up on it by replacing it with CS_ROLE_RAS_CLAIMED | counter, so
	 * late data is discarded; Bluetooth context resolves it to 0. Changes
	 * use atomic_cas(): whoever wins reports the procedure.
	 */
	atomic_t ras_pending;
	/* The role thread waits for ras_pending to clear. */
	atomic_t ras_waiter;
	/* Local procedures of the run with done status complete; cleared at RUNNING. */
	atomic_t procedures_completed;
};

extern struct cs_role_ctx cs_role;
extern struct cs_role_data cs_role_data;
/* Current connection, set and cleared in Bluetooth context. */
extern atomic_ptr_t cs_role_conn_ptr;
/* enum cs_role_link_phase, mirrored for Bluetooth context. */
extern atomic_t cs_role_link_phase;

/* cs_role_core.c */
void cs_role_post(const struct cs_role_msg *msg);
bool cs_role_is_role_thread(void);
void cs_role_set_stage(enum cs_role_stage stage, bool deadline);
void cs_role_fail(enum cs_role_failure_stage failure, uint8_t hci_status, int error);
void cs_role_advance(void);
void cs_role_stop_finish(int outcome);
void cs_role_link_down(void);
bool cs_role_is_ours(const struct bt_conn *conn);

/* cs_role_events.c */
void cs_role_events_init(const struct cs_role_callbacks *callbacks);
bool cs_role_is_event_thread(void);
void cs_role_notify(enum cs_role_state state, enum cs_role_failure_stage failure,
                    enum cs_role_stop_reason stop_reason, uint8_t hci_status, int error);
void cs_role_event_capabilities(const struct cs_capabilities *record);
void cs_role_event_configuration(const struct cs_config_complete *record);
void cs_role_event_procedure(const struct cs_procedure_enable_complete *record);
void cs_role_event_fae(uint8_t hci_status, const int8_t *entries);
void cs_role_event_ras_lost(uint16_t procedure_counter, int error);
void cs_role_event_procedures_complete(uint16_t procedures_completed);
/* Subevent streaming, Bluetooth context. */
void cs_role_stream_hci(const struct bt_conn_le_cs_subevent_result *result,
                        enum bt_conn_le_cs_role role);
int cs_role_stream_begin(const struct cs_subevent *header, uint16_t num_tones);
void cs_role_stream_step(const struct cs_step_header *step);
void cs_role_stream_end(bool complete);

/* cs_role_link.c */
int cs_role_link_init(void);
int cs_role_link_scan(void);
int cs_role_link_begin(const struct cs_role_msg *msg);
void cs_role_link_disconnect_request(const struct cs_role_msg *msg);
void cs_role_link_connected(const struct cs_role_msg *msg);
void cs_role_link_disconnected(const struct cs_role_msg *msg);
void cs_role_link_security(const struct cs_role_msg *msg);
void cs_role_link_scan_match(const struct cs_role_msg *msg);
void cs_role_link_timers(void);
k_timepoint_t cs_role_link_next_timer(void);
void cs_role_link_schedule_restart(void);

/* cs_role_initiator.c (CONFIG_APP_CS_ROLES_INITIATOR) */
void cs_role_initiator_advance(void);
/* Preferred T_PM for the next LE CS Create Config (vendor command CS Params
 * Set); returns the HCI status. The controller keeps it until the next call.
 */
uint8_t cs_role_controller_t_pm_set(uint8_t t_pm_us);
void cs_role_initiator_handle(const struct cs_role_msg *msg);
void cs_role_initiator_release(bool link_down);
void cs_role_initiator_disabled(void);
void cs_role_initiator_stop_ras_timeout(void);
void cs_role_initiator_local_subevent(const struct bt_conn_le_cs_subevent_result *result);
void cs_role_initiator_data_reset(void);

/* cs_role_reflector.c (CONFIG_APP_CS_ROLES_REFLECTOR) */
void cs_role_reflector_advance(void);
void cs_role_reflector_handle(const struct cs_role_msg *msg);
void cs_role_reflector_release(bool link_down);

#endif /* CS_ROLE_INTERNAL_H_ */
