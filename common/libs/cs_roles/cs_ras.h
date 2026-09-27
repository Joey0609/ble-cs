/* SPDX-License-Identifier: MIT */
/**
 * @file cs_ras.h
 * @brief RAS data bookkeeping of the CS initiator, without Zephyr dependencies.
 *
 * The Ranging Requestor receives the reflector's steps once per procedure,
 * after the initiator's own subevents of that procedure. The NCS parser
 * (bt_ras_rreq_rd_subevent_data_parse()) needs the local steps of the same
 * procedure to interpret them, so one procedure's local steps are kept until
 * its RAS data arrives. This module decides when that buffer starts, when a
 * buffered procedure is lost, and how the 12-bit ranging counter maps back
 * to the 16-bit procedure counter. It also maps RAS header fields to
 * subevent header fields.
 *
 * Tested natively in tests/cs_roles.
 */
#ifndef CS_RAS_H_
#define CS_RAS_H_

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Bits of the procedure counter carried by the RAS ranging counter. */
#define CS_RAS_RANGING_COUNTER_MASK 0x0FFFU

/** Abort step value for RAS subevents, which do not report one. */
#define CS_RAS_ABORT_STEP_NONE 0xFFU

/** Local procedure whose steps are buffered for the RAS parser. */
struct cs_ras_tracker {
	/** Procedure counter of the buffered local steps. */
	uint16_t procedure_counter;
	/** Local steps of @c procedure_counter are buffered and not yet matched. */
	bool buffered;
	/** The local procedure reported its last subevent. */
	bool complete;
	/** An earlier procedure was reported lost; its RAS data may still arrive late. */
	bool lost;
	/** Procedure counter of that lost procedure, when @c lost. */
	uint16_t lost_procedure_counter;
};

/** What to do with a local subevent, from cs_ras_local_subevent(). */
struct cs_ras_local_action {
	/** Reset the local step buffer before appending this subevent's steps. */
	bool reset;
	/** A buffered earlier procedure never received its RAS data. */
	bool lost;
	/** Procedure counter of the lost procedure, when @c lost. */
	uint16_t lost_procedure_counter;
};

/** @brief 12-bit RAS ranging counter of @p procedure_counter. */
static inline uint16_t cs_ras_ranging_counter(uint16_t procedure_counter) {
	return procedure_counter & CS_RAS_RANGING_COUNTER_MASK;
}

/** @brief Forget any buffered procedure (link or configuration change). */
void cs_ras_tracker_reset(struct cs_ras_tracker *tracker);

/**
 * @brief Account for one local subevent that carries steps.
 *
 * A subevent of a new procedure starts a new buffer; a buffered earlier
 * procedure that was never matched is reported as lost.
 *
 * @param procedure_done True when this is the procedure's last subevent
 *        (procedure done status complete or aborted).
 */
struct cs_ras_local_action cs_ras_local_subevent(struct cs_ras_tracker *tracker,
                                                 uint16_t procedure_counter, bool procedure_done);

/**
 * @brief Match RAS data to the buffered procedure and release it.
 *
 * @param[out] procedure_counter 16-bit procedure counter of the match.
 * @retval 0 Matched; the buffer holds that procedure's local steps.
 * @retval -EALREADY Late data of the procedure cs_ras_local_subevent() last
 *         reported lost; it was reported once already.
 * @retval -ENOENT No buffered procedure with this ranging counter.
 */
int cs_ras_match(struct cs_ras_tracker *tracker, uint16_t ranging_counter,
                 uint16_t *procedure_counter);

/** @brief Antenna paths reported by a ranging header mask: bits 0 to 3 set. */
uint8_t cs_ras_antenna_paths(uint8_t antenna_paths_mask);

/** RAS subevent header fields, unpacked from their bit fields. */
struct cs_ras_subevent_fields {
	uint16_t start_acl_conn_event;
	uint16_t freq_compensation;
	uint8_t ranging_done_status;
	uint8_t subevent_done_status;
	uint8_t ranging_abort_reason;
	uint8_t subevent_abort_reason;
	int8_t ref_power_level;
	uint8_t num_steps_reported;
};

/** Subevent header fields for a reflector subevent reported through RAS. */
struct cs_ras_subevent_header {
	uint8_t config_id;
	uint8_t num_antenna_paths;
	int8_t reference_power_level;
	uint16_t subevent_id;
	uint16_t event_id;
	uint16_t procedure_id;
	uint16_t frequency_compensation;
	uint8_t procedure_done_status;
	uint8_t subevent_done_status;
	uint8_t procedure_abort_reason;
	uint8_t subevent_abort_reason;
	uint8_t abort_step;
};

/**
 * @brief Map RAS headers to subevent header fields.
 *
 * RAS done statuses (0 complete, 1 partial, 0xF aborted) and abort reasons use
 * the HCI values, so they are copied. RAS carries no abort step.
 *
 * @retval 0 Mapped.
 * @retval -EINVAL Configuration ID above 3 or no antenna path in the mask.
 */
int cs_ras_map_subevent(uint8_t config_id, uint8_t antenna_paths_mask, uint16_t procedure_counter,
                        uint16_t subevent_id, const struct cs_ras_subevent_fields *fields,
                        struct cs_ras_subevent_header *header);

#ifdef __cplusplus
}
#endif

#endif /* CS_RAS_H_ */
