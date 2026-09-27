/* SPDX-License-Identifier: MIT */
/* Event queue and local subevent streaming of cs_roles (cs_role_events.c).
 * The file is included so the test can drain the queue as the event thread
 * does.
 */
#undef NDEBUG
#include <assert.h>
#include <stdio.h>

#include "cs_roles/cs_role_events.c"

#include "bt_stubs.h"
#include "step_data.h"

/* From cs_role_core.c. */
struct cs_role_data cs_role_data;
static struct k_thread role_thread;

bool cs_role_is_role_thread(void) {
	return k_current_get() == &role_thread;
}

/* Callbacks. */

static enum cs_role_state states[64];
static size_t state_count;
static size_t capabilities_count;
struct lost {
	uint16_t counter;
	int error;
};
static struct lost lost[64];
static size_t lost_count;
/* Order of delivery: 's' state, 'c' capabilities, 'l' RAS lost. */
static char order[128];
static size_t order_len;

static struct cs_subevent begun;
static uint16_t begun_tones;
static size_t begin_count;
static int begin_result;
static size_t step_count;
static size_t step_bytes;
static uint16_t step_tones;
static bool step_index_ok;
static size_t end_count;
static bool end_complete;

static void on_state(enum cs_role_state state, enum cs_role_failure_stage failure,
                     enum cs_role_stop_reason stop_reason, uint8_t hci_status, int error) {
	ARG_UNUSED(failure);
	ARG_UNUSED(stop_reason);
	ARG_UNUSED(hci_status);
	ARG_UNUSED(error);
	states[state_count++] = state;
	order[order_len++] = 's';
}

static void on_capabilities(const struct cs_capabilities *record) {
	ARG_UNUSED(record);
	capabilities_count++;
	order[order_len++] = 'c';
}

static void on_ras_lost(uint16_t procedure_counter, int error) {
	lost[lost_count++] = (struct lost){procedure_counter, error};
	order[order_len++] = 'l';
}

static int on_begin(const struct cs_subevent *header, uint16_t num_tones) {
	begun = *header;
	begun_tones = num_tones;
	begin_count++;
	return begin_result;
}

static void on_step(const struct cs_step_header *step) {
	uint8_t n;

	step_index_ok = step_index_ok && step->index == step_count;
	step_count++;
	step_bytes += step->size;
	(void)cs_step_tones(step, &n);
	step_tones += n;
}

static void on_end(bool complete) {
	end_count++;
	end_complete = complete;
}

static const struct cs_role_callbacks callbacks_table = {
	.state = on_state,
	.capabilities = on_capabilities,
	.ras_data_lost = on_ras_lost,
	.subevent_begin = on_begin,
	.subevent_step = on_step,
	.subevent_end = on_end,
};

static void reset(void) {
	cs_role_events_init(&callbacks_table);
	k_msgq_purge(&events);
	atomic_clear(&lost_merged);
	state_count = 0U;
	capabilities_count = 0U;
	lost_count = 0U;
	order_len = 0U;
	memset(&cs_role_data, 0, sizeof(cs_role_data));
	begin_count = 0U;
	begin_result = 0;
	step_count = 0U;
	step_bytes = 0U;
	step_tones = 0U;
	step_index_ok = true;
	end_count = 0U;
	test_current_thread = NULL;
}

/* The event thread's loop, until the queue is empty. */
static void drain(void) {
	struct event event;

	while (k_msgq_get(&events, &event, K_NO_WAIT) == 0) {
		deliver_queued(&event);
	}
}

static void test_control_events(void) {
	const struct cs_capabilities record = {0};

	reset();
	/* The role thread waits for room: its events are never dropped. */
	test_current_thread = &role_thread;
	cs_role_notify(CS_ROLE_STATE_RUNNING, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_NONE, 0U, 0);
	assert(K_TIMEOUT_EQ(test_msgq_put_timeout, K_FOREVER));
	/* Bluetooth context never waits. */
	test_current_thread = NULL;
	cs_role_event_capabilities(&record);
	assert(K_TIMEOUT_EQ(test_msgq_put_timeout, K_NO_WAIT));
	/* Nor does the event thread, whose callbacks may post. */
	test_current_thread = &event_thread;
	cs_role_notify(CS_ROLE_STATE_STOPPED, CS_ROLE_FAILURE_NONE, CS_ROLE_STOP_HOST, 0U, 0);
	assert(K_TIMEOUT_EQ(test_msgq_put_timeout, K_NO_WAIT));
	test_current_thread = NULL;

	/* Delivered in the order posted. */
	drain();
	assert(order_len == 3U && memcmp(order, "scs", 3) == 0);
	assert(states[0] == CS_ROLE_STATE_RUNNING && states[1] == CS_ROLE_STATE_STOPPED);
}

static void test_ras_lost_reserve(void) {
	const struct cs_capabilities record = {0};
	const size_t room = CONFIG_APP_CS_ROLES_EVENT_QUEUE_DEPTH - CONFIG_APP_CS_ROLES_EVENT_RESERVE;

	reset();
	/* RAS-lost events stop short of the reserve; the rest are merged. */
	for (uint16_t counter = 0; counter < room + 4U; counter++) {
		cs_role_event_ras_lost(counter, -EBADMSG);
	}
	assert(k_msgq_num_used_get(&events) == room);
	assert(atomic_get(&lost_merged) == 4 && atomic_get(&lost_merged_counter) == room + 3U);

	/* The reserve still takes the control events of Bluetooth context. */
	for (size_t i = 0; i < CONFIG_APP_CS_ROLES_EVENT_RESERVE; i++) {
		cs_role_event_capabilities(&record);
	}
	assert(k_msgq_num_free_get(&events) == 0U);

	/* The merged ones arrive as one event after the first delivered event. */
	drain();
	assert(lost_count == room + 1U && capabilities_count == CONFIG_APP_CS_ROLES_EVENT_RESERVE);
	assert(lost[0].counter == 0 && lost[0].error == -EBADMSG);
	assert(lost[1].counter == room + 3U && lost[1].error == -ENOBUFS);
	for (size_t i = 2; i < lost_count; i++) {
		assert(lost[i].counter == i - 1U && lost[i].error == -EBADMSG);
	}
	assert(atomic_get(&lost_merged) == 0);

	/* With room again, nothing is merged. */
	cs_role_event_ras_lost(7, -ETIMEDOUT);
	drain();
	assert(lost_count == room + 2U && lost[room + 1U].error == -ETIMEDOUT);
}

/* Stream @p se as the local controller's result and check the two passes agree. */
static void check_two_pass(struct test_subevent *se, enum bt_conn_le_cs_role role,
                           enum bt_conn_le_cs_rtt_type rtt_type) {
	uint8_t record[CS_SUBEVENT_BUF_SIZE(64)];
	const struct cs_subevent_parse_cfg cfg = {.role = role, .rtt_type = rtt_type, .timestamp_us = 1};
	const struct cs_subevent *parsed = (const struct cs_subevent *)record;

	begin_count = step_count = step_bytes = step_tones = end_count = 0U;
	step_index_ok = true;
	cs_role_stream_hci(&se->result, role);
	assert(begin_count == 1U && end_count == 1U && end_complete && step_index_ok);
	/* Pass 1 sized exactly what pass 2 streamed. */
	assert(begun.num_steps == step_count && begun.num_steps == se->result.header.num_steps_reported);
	assert(begun.size == sizeof(struct cs_subevent) + step_bytes);
	assert(begun_tones == step_tones);
	assert(begun.role == role && begun.rtt_type == rtt_type);
	/* And the record parser agrees on the size. */
	assert(cs_subevent_parse(&se->result, &cfg, record, sizeof(record)) == 0);
	assert(parsed->size == begun.size && parsed->num_steps == begun.num_steps);
}

static void test_stream_two_pass(void) {
	static const enum bt_conn_le_cs_role roles[] = {BT_CONN_LE_CS_ROLE_INITIATOR,
	                                               BT_CONN_LE_CS_ROLE_REFLECTOR};
	static const enum bt_conn_le_cs_rtt_type rtt_types[] = {
		BT_CONN_LE_CS_RTT_TYPE_AA_ONLY, BT_CONN_LE_CS_RTT_TYPE_32_BIT_SOUNDING,
		BT_CONN_LE_CS_RTT_TYPE_96_BIT_SOUNDING, BT_CONN_LE_CS_RTT_TYPE_32_BIT_RANDOM};
	static struct test_subevent se;

	reset();
	atomic_or(&cs_role_data.layouts, BIT(1));
	for (size_t r = 0; r < ARRAY_SIZE(roles); r++) {
		for (size_t t = 0; t < ARRAY_SIZE(rtt_types); t++) {
			cs_role_data.rtt_types[1] = (uint8_t)rtt_types[t];
			for (uint8_t paths = 1; paths <= CS_STEP_MAX_ANTENNA_PATHS; paths++) {
				test_subevent_init(&se, paths, (uint16_t)(r * 100U + t * 10U + paths),
				                   (uint32_t)(paths + 7U * t));
				for (uint8_t mode = 0; mode <= 3U; mode++) {
					for (int repeat = 0; repeat < 3; repeat++) {
						test_add_step(&se, mode, roles[r], rtt_types[t], 0U);
					}
				}
				check_two_pass(&se, roles[r], rtt_types[t]);
			}
		}
	}

	/* A step that does not decode ends the subevent there, marked incomplete. */
	cs_role_data.rtt_types[1] = BT_CONN_LE_CS_RTT_TYPE_AA_ONLY;
	test_subevent_init(&se, 2, 1, 3);
	test_add_step(&se, 2, BT_CONN_LE_CS_ROLE_INITIATOR, BT_CONN_LE_CS_RTT_TYPE_AA_ONLY, 0U);
	test_add_step(&se, 1, BT_CONN_LE_CS_ROLE_INITIATOR, BT_CONN_LE_CS_RTT_TYPE_AA_ONLY, 5U);
	test_add_step(&se, 0, BT_CONN_LE_CS_ROLE_INITIATOR, BT_CONN_LE_CS_RTT_TYPE_AA_ONLY, 0U);
	begin_count = step_count = step_bytes = end_count = 0U;
	cs_role_stream_hci(&se.result, BT_CONN_LE_CS_ROLE_INITIATOR);
	assert(begin_count == 1U && begun.num_steps == 1U && step_count == 1U);
	assert(begun.size == sizeof(struct cs_subevent) + step_bytes);
	assert(end_count == 1U && !end_complete);

	/* A refused begin skips the steps; the end is still called. */
	test_subevent_init(&se, 1, 2, 4);
	test_add_step(&se, 0, BT_CONN_LE_CS_ROLE_INITIATOR, BT_CONN_LE_CS_RTT_TYPE_AA_ONLY, 0U);
	begin_result = -EAGAIN;
	begin_count = step_count = end_count = 0U;
	cs_role_stream_hci(&se.result, BT_CONN_LE_CS_ROLE_INITIATOR);
	assert(begin_count == 1U && step_count == 0U && end_count == 1U);
	begin_result = 0;

	/* A configuration whose layout is unknown is not streamed at all. */
	se.result.header.config_id = 2;
	begin_count = end_count = 0U;
	cs_role_stream_hci(&se.result, BT_CONN_LE_CS_ROLE_INITIATOR);
	assert(begin_count == 0U && end_count == 0U);
}

int main(void) {
	test_control_events();
	test_ras_lost_reserve();
	test_stream_two_pass();
	printf("cs_roles events: OK\n");
	return 0;
}
