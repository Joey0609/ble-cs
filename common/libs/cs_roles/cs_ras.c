/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <stddef.h>

#include "cs_ras.h"

/* Highest CS configuration ID. */
#define CONFIG_ID_MAX 3U

void cs_ras_tracker_reset(struct cs_ras_tracker *tracker) {
	*tracker = (struct cs_ras_tracker){ 0 };
}

struct cs_ras_local_action cs_ras_local_subevent(struct cs_ras_tracker *tracker,
                                                 uint16_t procedure_counter, bool procedure_done) {
	struct cs_ras_local_action action = { 0 };

	if (!tracker->buffered || tracker->procedure_counter != procedure_counter) {
		/* One procedure is buffered at a time, as in the NCS ras_initiator sample. */
		if (tracker->buffered) {
			action.lost = true;
			action.lost_procedure_counter = tracker->procedure_counter;
			tracker->lost = true;
			tracker->lost_procedure_counter = tracker->procedure_counter;
		}
		action.reset = true;
		tracker->procedure_counter = procedure_counter;
		tracker->buffered = true;
		tracker->complete = false;
	}
	tracker->complete = tracker->complete || procedure_done;
	return action;
}

int cs_ras_match(struct cs_ras_tracker *tracker, uint16_t ranging_counter,
                 uint16_t *procedure_counter) {
	uint16_t ranging = ranging_counter & CS_RAS_RANGING_COUNTER_MASK;

	if (!tracker->buffered || cs_ras_ranging_counter(tracker->procedure_counter) != ranging) {
		if (tracker->lost && cs_ras_ranging_counter(tracker->lost_procedure_counter) == ranging) {
			tracker->lost = false;
			return -EALREADY;
		}
		return -ENOENT;
	}
	*procedure_counter = tracker->procedure_counter;
	tracker->buffered = false;
	tracker->complete = false;
	return 0;
}

uint8_t cs_ras_antenna_paths(uint8_t antenna_paths_mask) {
	uint8_t paths = 0U;

	for (uint8_t bit = 0U; bit < 4U; bit++) {
		paths += (antenna_paths_mask >> bit) & 1U;
	}
	return paths;
}

int cs_ras_map_subevent(uint8_t config_id, uint8_t antenna_paths_mask, uint16_t procedure_counter,
                        uint16_t subevent_id, const struct cs_ras_subevent_fields *fields,
                        struct cs_ras_subevent_header *header) {
	uint8_t paths = cs_ras_antenna_paths(antenna_paths_mask);

	/* An empty mask is valid: no phase measurement (mode 1 only). */
	if (fields == NULL || header == NULL || config_id > CONFIG_ID_MAX) {
		return -EINVAL;
	}
	*header = (struct cs_ras_subevent_header){
		.config_id = config_id,
		.num_antenna_paths = paths,
		.reference_power_level = fields->ref_power_level,
		.subevent_id = subevent_id,
		.event_id = fields->start_acl_conn_event,
		.procedure_id = procedure_counter,
		.frequency_compensation = fields->freq_compensation,
		.procedure_done_status = fields->ranging_done_status,
		.subevent_done_status = fields->subevent_done_status,
		.procedure_abort_reason = fields->ranging_abort_reason,
		.subevent_abort_reason = fields->subevent_abort_reason,
		.abort_step = CS_RAS_ABORT_STEP_NONE,
	};
	return 0;
}
