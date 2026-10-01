/* SPDX-License-Identifier: MIT */
/* cs_ras.c: local procedure buffer decisions, ranging counter expansion and
 * RAS header -> subevent header mapping.
 */
#undef NDEBUG
#include <assert.h>
#include <errno.h>
#include <stdio.h>

#include <cs_roles/cs_ras.h>

static void test_counter_expansion_across_wrap(void) {
	struct cs_ras_tracker tracker;
	uint16_t counter = 0;

	cs_ras_tracker_reset(&tracker);
	/* Procedures on both sides of the 12-bit ranging counter wrap. */
	for (uint32_t procedure = 0x0FFEU; procedure <= 0x3001U; procedure += 0x0801U) {
		struct cs_ras_local_action action =
		        cs_ras_local_subevent(&tracker, (uint16_t)procedure, true);

		assert(action.reset);
		assert(cs_ras_match(&tracker, cs_ras_ranging_counter((uint16_t)procedure), &counter) == 0);
		assert(counter == (uint16_t)procedure);
	}
	/* 16-bit wrap. */
	(void)cs_ras_local_subevent(&tracker, 0xFFFFU, true);
	assert(cs_ras_match(&tracker, 0x0FFFU, &counter) == 0 && counter == 0xFFFFU);
	(void)cs_ras_local_subevent(&tracker, 0x0000U, true);
	assert(cs_ras_match(&tracker, 0x0000U, &counter) == 0 && counter == 0x0000U);
	/* Upper bits of the ranging counter are ignored. */
	(void)cs_ras_local_subevent(&tracker, 0x1234U, true);
	assert(cs_ras_match(&tracker, 0xF234U, &counter) == 0 && counter == 0x1234U);
}

static void test_buffer_kept_until_matched(void) {
	struct cs_ras_tracker tracker;
	struct cs_ras_local_action action;
	uint16_t counter = 0;

	cs_ras_tracker_reset(&tracker);
	action = cs_ras_local_subevent(&tracker, 7U, false);
	assert(action.reset && !action.lost);
	/* More subevents of the same procedure append. */
	action = cs_ras_local_subevent(&tracker, 7U, false);
	assert(!action.reset && !action.lost && !tracker.complete);
	action = cs_ras_local_subevent(&tracker, 7U, true);
	assert(!action.reset && tracker.complete && tracker.buffered);

	/* Data for another procedure does not release the buffer. */
	assert(cs_ras_match(&tracker, 6U, &counter) == -ENOENT);
	assert(tracker.buffered);
	assert(cs_ras_match(&tracker, 7U, &counter) == 0 && counter == 7U);
	assert(!tracker.buffered);
	/* Matched once only. */
	assert(cs_ras_match(&tracker, 7U, &counter) == -ENOENT);

	/* After a match, the next procedure starts a buffer without a loss. */
	action = cs_ras_local_subevent(&tracker, 8U, false);
	assert(action.reset && !action.lost);
}

static void test_next_procedure_before_data_is_lost(void) {
	struct cs_ras_tracker tracker;
	struct cs_ras_local_action action;
	uint16_t counter = 0;

	cs_ras_tracker_reset(&tracker);
	(void)cs_ras_local_subevent(&tracker, 0x0FFFU, true);
	action = cs_ras_local_subevent(&tracker, 0x1000U, false);
	assert(action.reset && action.lost && action.lost_procedure_counter == 0x0FFFU);
	/* The older procedure's late data is recognised as already reported, once. */
	assert(cs_ras_match(&tracker, 0x0FFFU, &counter) == -EALREADY);
	assert(tracker.buffered);
	assert(cs_ras_match(&tracker, 0x0FFFU, &counter) == -ENOENT);
	assert(cs_ras_match(&tracker, 0x0000U, &counter) == 0 && counter == 0x1000U);

	/* Only the latest lost procedure is remembered. */
	(void)cs_ras_local_subevent(&tracker, 0x1001U, true);
	(void)cs_ras_local_subevent(&tracker, 0x1002U, true);
	action = cs_ras_local_subevent(&tracker, 0x1003U, true);
	assert(action.lost && action.lost_procedure_counter == 0x1002U);
	assert(cs_ras_match(&tracker, 0x0001U, &counter) == -ENOENT);
	assert(cs_ras_match(&tracker, 0x0002U, &counter) == -EALREADY);

	cs_ras_tracker_reset(&tracker);
	assert(cs_ras_match(&tracker, 0U, &counter) == -ENOENT);
}

static void test_header_mapping(void) {
	const struct cs_ras_subevent_fields fields = {
		.start_acl_conn_event = 0x1234U,
		.freq_compensation = 0xC000U,
		.ranging_done_status = 0x1U,
		.subevent_done_status = 0xFU,
		.ranging_abort_reason = 0x0U,
		.subevent_abort_reason = 0x3U,
		.ref_power_level = -12,
		.num_steps_reported = 17U,
	};
	struct cs_ras_subevent_header header;

	assert(cs_ras_antenna_paths(0x00U) == 0U);
	assert(cs_ras_antenna_paths(0x01U) == 1U);
	assert(cs_ras_antenna_paths(0x0AU) == 2U);
	assert(cs_ras_antenna_paths(0x0FU) == 4U);
	/* Bits 4-7 are RFU. */
	assert(cs_ras_antenna_paths(0xF1U) == 1U);

	assert(cs_ras_map_subevent(2U, 0x05U, 0xABCDU, 3U, &fields, &header) == 0);
	assert(header.config_id == 2U);
	assert(header.num_antenna_paths == 2U);
	assert(header.procedure_id == 0xABCDU);
	assert(header.subevent_id == 3U);
	assert(header.event_id == 0x1234U);
	assert(header.frequency_compensation == 0xC000U);
	assert(header.reference_power_level == -12);
	assert(header.procedure_done_status == 0x1U);
	assert(header.subevent_done_status == 0xFU);
	assert(header.procedure_abort_reason == 0x0U);
	assert(header.subevent_abort_reason == 0x3U);
	assert(header.abort_step == CS_RAS_ABORT_STEP_NONE && header.abort_step == 0xFFU);

	assert(cs_ras_map_subevent(4U, 0x01U, 0U, 0U, &fields, &header) == -EINVAL);
	assert(cs_ras_map_subevent(0U, 0x01U, 0U, 0U, NULL, &header) == -EINVAL);
	/* No phase measurement (mode 1 only): no antenna paths. */
	assert(cs_ras_map_subevent(0U, 0x00U, 0U, 0U, &fields, &header) == 0);
	assert(header.num_antenna_paths == 0U);
	assert(cs_ras_map_subevent(0U, 0xF0U, 0U, 0U, &fields, &header) == 0);
	assert(header.num_antenna_paths == 0U);
}

int main(void) {
	test_counter_expansion_across_wrap();
	test_buffer_kept_until_matched();
	test_next_procedure_before_data_is_lost();
	test_header_mapping();
	puts("cs_ras: OK");
	return 0;
}
