/* SPDX-License-Identifier: MIT */
/* Streamed and record-built subevent frames are the same bytes.
 *
 * cs_client streams local subevents straight from the HCI result
 * (cs_role_stream_hci() -> host_link_report_cs_subevent_begin/step/end); a
 * record parsed with cs_subevent_parse() and sent with
 * host_link_report_cs_subevent() must give the same frame. Every step type,
 * both roles, every RTT type and 1 to 4 antenna paths.
 */
#undef NDEBUG
#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "bt_stubs.h"
#include "cs_protocol/cs_protocol_packets.h"
#include "cs_roles/cs_role_internal.h"
#include "host_link/host_link_internal.h"
#include "host_link/host_link_reports.h"
#include "step_data.h"

/* From cs_role_core.c. */
struct cs_role_data cs_role_data;

bool cs_role_is_role_thread(void) { return false; }

/* host_link.c: the report sink, capturing one frame. */

static uint8_t frame[8192];
static size_t frame_len;
static size_t frame_reserved;
static size_t frames;

static int sink_begin(void *ctx, size_t len) {
	ARG_UNUSED(ctx);
	assert(len <= sizeof(frame));
	frame_reserved = len;
	frame_len = 0U;
	return 0;
}

static void sink_write(void *ctx, const uint8_t *data, size_t len) {
	ARG_UNUSED(ctx);
	assert(frame_len + len <= frame_reserved);
	memcpy(frame + frame_len, data, len);
	frame_len += len;
}

static int sink_end(void *ctx) {
	ARG_UNUSED(ctx);
	frames++;
	return 0;
}

const struct host_link_frame_sink host_link_report_sink = {
	.begin = sink_begin,
	.write = sink_write,
	.end = sink_end,
};

int host_link_send_report(const uint8_t *report, size_t len) {
	ARG_UNUSED(report);
	ARG_UNUSED(len);
	return 0;
}

void host_link_report_counters(uint32_t *sent, uint32_t *dropped) {
	*sent = 0U;
	*dropped = 0U;
}

/* The streaming callbacks as cs_client registers them. */

static void stream_end(bool complete) {
	ARG_UNUSED(complete);
	assert(host_link_report_cs_subevent_end() == 0);
}

static const struct cs_role_callbacks callbacks = {
	.subevent_begin = host_link_report_cs_subevent_begin,
	.subevent_step = host_link_report_cs_subevent_step,
	.subevent_end = stream_end,
};

/* Both frames of @p se, compared. Returns the frame's step count. */
static uint8_t compare(struct test_subevent *se, enum bt_conn_le_cs_role role,
                       enum bt_conn_le_cs_rtt_type rtt_type) {
	static uint8_t streamed[sizeof(frame)];
	static uint8_t record[CS_SUBEVENT_BUF_SIZE(64)];
	struct cs_subevent_counter counter = {0};
	struct cs_subevent_parse_cfg cfg = {.role = role, .rtt_type = rtt_type, .timestamp_us = 1};
	struct cs_protocol_packet_t packet;
	size_t streamed_len;

	cs_role_data.counter = (struct cs_subevent_counter){0};
	frames = 0U;
	cs_role_stream_hci(&se->result, role);
	assert(frames == 1U && frame_len == frame_reserved);
	memcpy(streamed, frame, frame_len);
	streamed_len = frame_len;

	cfg.subevent_id = cs_subevent_counter_next(&counter, &se->result);
	assert(cs_subevent_parse(&se->result, &cfg, record, sizeof(record)) == 0);
	assert(host_link_report_cs_subevent((const struct cs_subevent *)record) == 0);
	assert(frames == 2U && frame_len == frame_reserved);

	assert(streamed_len == frame_len && memcmp(streamed, frame, frame_len) == 0);
	/* A valid frame of the role's type. */
	assert(cs_protocol_decode(frame, frame_len, &packet) == CS_PROTOCOL_OK);
	assert(packet.type == (role == BT_CONN_LE_CS_ROLE_INITIATOR ?
	                               CS_PROTOCOL_PACKET_CS_INITIATOR_SUBEVENT_RESULT :
	                               CS_PROTOCOL_PACKET_CS_REFLECTOR_SUBEVENT_RESULT));
	return ((const struct cs_protocol_cs_initiator_subevent_result_frame_t *)frame)
		->num_steps_reported;
}

int main(void) {
	static const enum bt_conn_le_cs_role roles[] = {BT_CONN_LE_CS_ROLE_INITIATOR,
	                                               BT_CONN_LE_CS_ROLE_REFLECTOR};
	static const enum bt_conn_le_cs_rtt_type rtt_types[] = {
		BT_CONN_LE_CS_RTT_TYPE_AA_ONLY,          BT_CONN_LE_CS_RTT_TYPE_32_BIT_SOUNDING,
		BT_CONN_LE_CS_RTT_TYPE_96_BIT_SOUNDING,  BT_CONN_LE_CS_RTT_TYPE_32_BIT_RANDOM,
		BT_CONN_LE_CS_RTT_TYPE_64_BIT_RANDOM,    BT_CONN_LE_CS_RTT_TYPE_96_BIT_RANDOM,
		BT_CONN_LE_CS_RTT_TYPE_128_BIT_RANDOM};
	static struct test_subevent se;
	size_t compared = 0U;

	cs_role_events_init(&callbacks);
	atomic_or(&cs_role_data.layouts, BIT(1));
	for (size_t r = 0; r < ARRAY_SIZE(roles); r++) {
		for (size_t t = 0; t < ARRAY_SIZE(rtt_types); t++) {
			cs_role_data.rtt_types[1] = (uint8_t)rtt_types[t];
			for (uint8_t paths = 1; paths <= CS_STEP_MAX_ANTENNA_PATHS; paths++) {
				/* One mode per subevent, then all modes mixed. */
				for (uint8_t mode = 0; mode <= 4U; mode++) {
					test_subevent_init(&se, paths, (uint16_t)(1000U + compared),
					                   (uint32_t)(compared * 31U + 1U));
					for (int i = 0; i < 6; i++) {
						test_add_step(&se, mode == 4U ? (uint8_t)(i % 4) : mode, roles[r],
						              rtt_types[t], 0U);
					}
					assert(compare(&se, roles[r], rtt_types[t]) == 6U);
					compared++;
				}
			}
		}
	}

	/* No steps: an aborted subevent. */
	test_subevent_init(&se, 1, 7, 7);
	se.result.header.subevent_done_status = BT_CONN_LE_CS_SUBEVENT_ABORTED;
	se.result.header.subevent_abort_reason = BT_CONN_LE_CS_SUBEVENT_ABORT_NO_CS_SYNC;
	se.result.header.abort_step = 0;
	assert(compare(&se, BT_CONN_LE_CS_ROLE_REFLECTOR, BT_CONN_LE_CS_RTT_TYPE_AA_ONLY) == 0U);

	/* A long subevent: 64 mode-3 steps with 4 antenna paths, the most the test record holds. */
	cs_role_data.rtt_types[1] = BT_CONN_LE_CS_RTT_TYPE_96_BIT_SOUNDING;
	test_subevent_init(&se, 4, 8, 8);
	for (int i = 0; i < 64; i++) {
		test_add_step(&se, 3, BT_CONN_LE_CS_ROLE_INITIATOR, BT_CONN_LE_CS_RTT_TYPE_96_BIT_SOUNDING,
		              0U);
	}
	assert(compare(&se, BT_CONN_LE_CS_ROLE_INITIATOR, BT_CONN_LE_CS_RTT_TYPE_96_BIT_SOUNDING) ==
	       64U);

	printf("cs_roles streamed vs record-built frames: OK (%zu subevents)\n", compared + 2U);
	return 0;
}
