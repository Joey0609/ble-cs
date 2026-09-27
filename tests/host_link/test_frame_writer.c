/* SPDX-License-Identifier: MIT */
/* host_link_frame.c: a frame streamed in pieces equals the frame
 * cs_protocol_encode() builds in memory; a refused frame writes nothing; a
 * short frame is completed with an invalid CRC.
 */
#undef NDEBUG
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "cs_protocol/cs_protocol.h"
#include "cs_protocol/cs_protocol_packets.h"
#include "host_link/host_link_frame.h"

struct memory_sink {
	uint8_t data[4096];
	size_t len;
	size_t reserved;
	int begin_result;
	int begins;
	int ends;
};

static int sink_begin(void *ctx, size_t len) {
	struct memory_sink *sink = ctx;

	sink->begins++;
	if (sink->begin_result) {
		return sink->begin_result;
	}
	assert(sink->len + len <= sizeof(sink->data));
	sink->reserved = len;
	return 0;
}

static void sink_write(void *ctx, const uint8_t *data, size_t len) {
	struct memory_sink *sink = ctx;

	/* Never more than begin reserved. */
	assert(len <= sink->reserved);
	memcpy(sink->data + sink->len, data, len);
	sink->len += len;
	sink->reserved -= len;
}

static int sink_end(void *ctx) {
	struct memory_sink *sink = ctx;

	sink->ends++;
	assert(sink->reserved == 0U);
	return 0;
}

static void test_streamed_equals_encoded(void) {
	struct memory_sink memory = { 0 };
	const struct host_link_frame_sink sink = { sink_begin, sink_write, sink_end, &memory };
	struct host_link_frame frame;
	uint8_t payload[1000];
	uint8_t expected[sizeof(payload) + CS_PROTOCOL_OVERHEAD];
	struct cs_protocol_packet_t packet;

	for (size_t i = 0; i < sizeof(payload); i++) {
		payload[i] = (uint8_t)(i * 7U + 3U);
	}
	for (size_t payload_len = 0; payload_len <= sizeof(payload); payload_len += 97U) {
		int len = cs_protocol_encode(expected, sizeof(expected),
		                             CS_PROTOCOL_PACKET_CS_REFLECTOR_SUBEVENT_RESULT, payload,
		                             payload_len);

		assert(len == (int)(payload_len + CS_PROTOCOL_OVERHEAD));
		memory.len = 0U;
		assert(host_link_frame_begin(&frame, &sink, CS_PROTOCOL_PACKET_CS_REFLECTOR_SUBEVENT_RESULT,
		                             payload_len) == 0);
		/* Uneven pieces, as steps of different modes would be. */
		for (size_t offset = 0, piece = 1; offset < payload_len; piece = piece % 61U + 1U) {
			size_t n = payload_len - offset < piece ? payload_len - offset : piece;

			host_link_frame_write(&frame, payload + offset, n);
			offset += n;
		}
		assert(host_link_frame_end(&frame, true) == 0);
		assert(memory.len == (size_t)len);
		assert(memcmp(memory.data, expected, memory.len) == 0);
		assert(cs_protocol_decode(memory.data, memory.len, &packet) == CS_PROTOCOL_OK && packet.valid);
	}
}

static void test_refused_writes_nothing(void) {
	struct memory_sink memory = { .begin_result = -EAGAIN };
	const struct host_link_frame_sink sink = { sink_begin, sink_write, sink_end, &memory };
	struct host_link_frame frame;
	const uint8_t byte = 0x55;

	assert(host_link_frame_begin(&frame, &sink, CS_PROTOCOL_PACKET_LOG_MESSAGE, 10U) == -EAGAIN);
	host_link_frame_write(&frame, &byte, 1U);
	assert(host_link_frame_end(&frame, true) == -EINVAL);
	assert(memory.len == 0U && memory.ends == 0);

	assert(host_link_frame_begin(&frame, &sink, CS_PROTOCOL_PACKET_LOG_MESSAGE,
	                             (size_t)CS_PROTOCOL_MAX_PAYLOAD + 1U) == -EMSGSIZE);
}

static void test_short_or_invalid_frame_is_discarded(void) {
	struct memory_sink memory = { 0 };
	const struct host_link_frame_sink sink = { sink_begin, sink_write, sink_end, &memory };
	struct host_link_frame frame;
	struct cs_protocol_packet_t packet;
	const uint8_t piece[8] = { 1, 2, 3, 4, 5, 6, 7, 8 };

	/* Fewer bytes than announced: zero-filled to the announced size, CRC invalid. */
	assert(host_link_frame_begin(&frame, &sink, CS_PROTOCOL_PACKET_LOG_MESSAGE, 100U) == 0);
	host_link_frame_write(&frame, piece, sizeof(piece));
	assert(host_link_frame_end(&frame, true) == -EIO);
	assert(memory.len == 100U + CS_PROTOCOL_OVERHEAD && memory.ends == 1);
	assert(cs_protocol_decode(memory.data, memory.len, &packet) == CS_PROTOCOL_ERR_CRC);

	/* More bytes than announced are cut off. */
	memory.len = 0U;
	assert(host_link_frame_begin(&frame, &sink, CS_PROTOCOL_PACKET_LOG_MESSAGE, 4U) == 0);
	host_link_frame_write(&frame, piece, sizeof(piece));
	assert(host_link_frame_end(&frame, true) == 0);
	assert(memory.len == 4U + CS_PROTOCOL_OVERHEAD);
	assert(cs_protocol_decode(memory.data, memory.len, &packet) == CS_PROTOCOL_OK);
	assert(packet.payload_len == 4U && memcmp(packet.payload, piece, 4U) == 0);

	/* Invalidated explicitly. */
	memory.len = 0U;
	assert(host_link_frame_begin(&frame, &sink, CS_PROTOCOL_PACKET_LOG_MESSAGE, 8U) == 0);
	host_link_frame_write(&frame, piece, sizeof(piece));
	assert(host_link_frame_end(&frame, false) == -EIO);
	assert(cs_protocol_decode(memory.data, memory.len, &packet) == CS_PROTOCOL_ERR_CRC);
}

int main(void) {
	test_streamed_equals_encoded();
	test_refused_writes_nothing();
	test_short_or_invalid_frame_is_discarded();
	puts("host_link frame writer: OK");
	return 0;
}
