/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief Client -> host reports.
 *
 * Reports are sent only while a host session is open; otherwise they are
 * dropped and counted, and the next CONNECT reports the client state. Each
 * call waits at most CONFIG_APP_HOST_LINK_REPORT_TIMEOUT_MS for transmit room.
 * Thread context only, except the streamed subevent calls
 * (host_link_report_cs_subevent_begin() and following), which never wait and
 * are made from Bluetooth callbacks.
 */

#ifndef HOST_LINK_REPORTS_H_
#define HOST_LINK_REPORTS_H_

#include <stddef.h>
#include <stdint.h>

struct cs_capabilities;
struct cs_config_complete;
struct cs_procedure_enable_complete;
struct cs_subevent;
struct cs_step_header;

#ifdef __cplusplus
extern "C" {
#endif

/** Report counters since boot. */
struct host_link_report_stats {
	/** Reports queued for the host. */
	uint32_t sent;
	/** Reports dropped: no session, or no transmit room in time. */
	uint32_t dropped;
};

/**
 * @brief Send CLIENT_STATE.
 *
 * @param state          One of @ref cs_protocol_client_state.
 * @param operation_mode Applied operation mode, or @ref CS_PROTOCOL_MODE_NONE.
 * @param reason         One of @ref cs_protocol_reject_reason.
 * @param hci_status     HCI status behind the change; 0 when none.
 * @param error          Negative errno when an operation ended abnormally; 0 otherwise.
 * @retval 0 Queued.
 * @retval -ENOTCONN No host session.
 * @return Other negative error from the transport.
 */
int host_link_report_client_state(uint8_t state, uint8_t operation_mode, uint8_t reason,
                                  uint8_t hci_status, int32_t error);

/**
 * @brief Send CS_FAE_TABLE for one remote FAE table read completion.
 *
 * @param hci_status HCI status of the read.
 * @param entries    CS_PROTOCOL_FAE_TABLE_ENTRIES values in HCI order, or
 *                   NULL on failure (all entries zero).
 * @param lsb_denominator Scale of @p entries: ppm = entry / @p lsb_denominator.
 */
int host_link_report_fae_table(uint8_t hci_status, const int8_t *entries, uint8_t lsb_denominator);

int host_link_report_cs_capabilities(const struct cs_capabilities *record);
int host_link_report_cs_configuration(const struct cs_config_complete *record);
int host_link_report_cs_procedure(const struct cs_procedure_enable_complete *record);

/**
 * @brief Begin a CS_INITIATOR/REFLECTOR_SUBEVENT_RESULT frame streamed step by step.
 *
 * The frame type follows @p header->role. The frame is sized from
 * @p header->num_steps and @p num_tones and must receive exactly that many
 * steps through host_link_report_cs_subevent_step() before
 * host_link_report_cs_subevent_end(); otherwise it is sent with an invalid
 * CRC. Never waits: without room for the whole frame it is dropped and
 * counted, before any byte is queued.
 *
 * @param header Subevent header fields; @c num_steps is the number of steps that follow.
 * @param num_tones Tones of all those steps together.
 * @retval 0 Frame begun.
 * @retval -ENOTCONN No host session.
 * @retval -EAGAIN No transmit room, or another frame is being written.
 * @retval -EBUSY Another streamed subevent is open.
 */
int host_link_report_cs_subevent_begin(const struct cs_subevent *header, uint16_t num_tones);

/** @brief Encode one step record into the open subevent frame. */
void host_link_report_cs_subevent_step(const struct cs_step_header *step);

/**
 * @brief Complete the open subevent frame and start sending it.
 * @retval 0 Sent as a valid frame.
 * @retval -EIO Step or tone count disagreed with begin; sent with an invalid CRC.
 */
int host_link_report_cs_subevent_end(void);

/** @brief Send a whole cs_utils subevent record (streams it through the calls above). */
int host_link_report_cs_subevent(const struct cs_subevent *record);

/**
 * @brief Send RAS_DATA_LOST for one procedure's real-time ranging data.
 * @param ranging_counter Procedure counter when known (16 bits), otherwise the RAS ranging counter (12 bits).
 */
int host_link_report_ras_data_lost(uint16_t ranging_counter, int16_t error);

/**
 * @brief Send CS_PROCEDURES_COMPLETE: the run's procedures ended on their own.
 * @param procedures_completed Procedures of the run that completed.
 */
int host_link_report_cs_procedures_complete(uint16_t procedures_completed);

/**
 * @brief Send CS_PEER_DATA: the data the initiator receives from the reflector on this link.
 * @param peer_data One of @ref cs_protocol_peer_data.
 */
int host_link_report_peer_data(uint8_t peer_data);

/**
 * @brief Send the negotiated ACL connection parameters of the current link.
 *
 * @param interval Connection interval, in 1.25 ms units.
 * @param latency Peripheral latency, in ACL events.
 * @param timeout Supervision timeout, in 10 ms units.
 * @param mtu Negotiated ATT MTU, in bytes.
 */
int host_link_report_connection_parameters(uint16_t interval, uint16_t latency,
                                           uint16_t timeout, uint16_t mtu);

/**
 * @brief Send RADIO_TEST_STATS for a running radio RX or RX sweep test.
 *
 * @param packets_received Packets with a valid CRC since START.
 * @param crc_errors       Packets with a failed CRC since START.
 * @param rssi_dbm         RSSI of the latest packet since the previous report,
 *                         or CS_PROTOCOL_RSSI_UNAVAILABLE.
 * @param channel          Channel of that packet, or the tuned channel.
 */
int host_link_report_radio_test_stats(uint32_t packets_received, uint32_t crc_errors,
                                      int8_t rssi_dbm, uint8_t channel);

/**
 * @brief Send a report frame the caller has already finalized.
 *
 * For variable-length frames such as subevent results.
 */
int host_link_report_frame(const uint8_t *frame, size_t len);

/** @brief Copy the report counters. */
void host_link_report_stats_get(struct host_link_report_stats *stats);

#ifdef __cplusplus
}
#endif

#endif /* HOST_LINK_REPORTS_H_ */
