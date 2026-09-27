/* SPDX-License-Identifier: MIT */

#include "cs_protocol.h"

#include <string.h>

#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/crc.h>

uint32_t cs_protocol_crc32(const void *data,
                           size_t data_len) {
	return crc32_ieee(data, data_len);
}

int cs_protocol_crc32_append(uint8_t *buffer,
                             size_t buffer_capacity,
                             size_t data_len) {
	if (buffer == NULL) {
		return CS_PROTOCOL_ERR_ARGUMENT;
	}
	if (data_len > buffer_capacity || buffer_capacity - data_len < CS_PROTOCOL_CRC_SIZE) {
		return CS_PROTOCOL_ERR_NO_SPACE;
	}

	sys_put_le32(cs_protocol_crc32(buffer, data_len), &buffer[data_len]);
	return (int)(data_len + CS_PROTOCOL_CRC_SIZE);
}

int cs_protocol_crc32_check(const uint8_t *buffer,
                            size_t data_len) {
	uint32_t expected_crc;
	uint32_t received_crc;

	if (buffer == NULL) {
		return CS_PROTOCOL_ERR_ARGUMENT;
	}

	received_crc = sys_get_le32(&buffer[data_len]);
	expected_crc = cs_protocol_crc32(buffer, data_len);

	return received_crc == expected_crc ? CS_PROTOCOL_OK : CS_PROTOCOL_ERR_CRC;
}

int cs_protocol_finalize_frame(void *frame,
                               size_t frame_size,
                               uint16_t type) {
	uint8_t *bytes = frame;

	if (frame == NULL) {
		return CS_PROTOCOL_ERR_ARGUMENT;
	}
	if (frame_size < CS_PROTOCOL_OVERHEAD || frame_size > CS_PROTOCOL_MAX_FRAME_SIZE) {
		return CS_PROTOCOL_ERR_LENGTH;
	}
	sys_put_le16(CS_PROTOCOL_SYNC, bytes);
	sys_put_le16((uint16_t)frame_size, bytes + 2);
	sys_put_le16(type, bytes + 4);
	sys_put_le32(cs_protocol_crc32(bytes + 2, frame_size - 8), bytes + frame_size - 6);
	sys_put_le16(CS_PROTOCOL_END_SYNC, bytes + frame_size - 2);
	return (int)frame_size;
}

int cs_protocol_encode(uint8_t *frame,
                       size_t frame_capacity,
                       uint16_t type,
                       const void *payload,
                       size_t payload_len) {
	return cs_protocol_encode_parts(frame, frame_capacity, type, payload, payload_len, NULL, 0U);
}

int cs_protocol_encode_parts(uint8_t *frame,
                             size_t frame_capacity,
                             uint16_t type,
                             const void *payload_part_1,
                             size_t payload_part_1_len,
                             const void *payload_part_2,
                             size_t payload_part_2_len) {
	size_t payload_len;
	size_t frame_size;

	if (frame == NULL || (payload_part_1 == NULL && payload_part_1_len != 0U) ||
	    (payload_part_2 == NULL && payload_part_2_len != 0U)) {
		return CS_PROTOCOL_ERR_ARGUMENT;
	}
	if (payload_part_1_len > CS_PROTOCOL_MAX_PAYLOAD ||
	    payload_part_2_len > CS_PROTOCOL_MAX_PAYLOAD - payload_part_1_len) {
		return CS_PROTOCOL_ERR_LENGTH;
	}

	payload_len = payload_part_1_len + payload_part_2_len;
	frame_size = CS_PROTOCOL_OVERHEAD + payload_len;
	if (frame_capacity < frame_size) {
		return CS_PROTOCOL_ERR_NO_SPACE;
	}

	if (payload_part_1_len != 0U) {
		memcpy(&frame[CS_PROTOCOL_HEADER_SIZE], payload_part_1, payload_part_1_len);
	}
	if (payload_part_2_len != 0U) {
		memcpy(&frame[CS_PROTOCOL_HEADER_SIZE + payload_part_1_len], payload_part_2, payload_part_2_len);
	}

	return cs_protocol_finalize_frame(frame, frame_size, type);
}

int cs_protocol_decode(const uint8_t *frame,
                       size_t frame_size,
                       struct cs_protocol_packet_t *packet) {
	const struct cs_protocol_header_t *header;
	const struct cs_protocol_footer_t *footer;
	const uint8_t *crc_data;
	size_t crc_data_len;
	size_t expected_frame_size;
	uint16_t payload_len;
	int result;

	if (packet == NULL) {
		return CS_PROTOCOL_ERR_ARGUMENT;
	}
	packet->valid = false;
	if (frame == NULL) {
		return CS_PROTOCOL_ERR_ARGUMENT;
	}
	if (frame_size < CS_PROTOCOL_OVERHEAD) {
		return CS_PROTOCOL_ERR_LENGTH;
	}

	header = (const struct cs_protocol_header_t *)frame;
	if (sys_le16_to_cpu(header->sync) != CS_PROTOCOL_SYNC) {
		return CS_PROTOCOL_ERR_SYNC;
	}

	if (sys_le16_to_cpu(header->size) < CS_PROTOCOL_OVERHEAD) {
		return CS_PROTOCOL_ERR_LENGTH;
	}
	payload_len = sys_le16_to_cpu(header->size) - CS_PROTOCOL_OVERHEAD;
	expected_frame_size = CS_PROTOCOL_OVERHEAD + payload_len;
	if (frame_size != expected_frame_size) {
		return CS_PROTOCOL_ERR_LENGTH;
	}

	footer = (const struct cs_protocol_footer_t *)&frame[CS_PROTOCOL_HEADER_SIZE + payload_len];
	if (sys_le16_to_cpu(footer->end_sync) != CS_PROTOCOL_END_SYNC) {
		return CS_PROTOCOL_ERR_SYNC;
	}

	crc_data = (const uint8_t *)&header->size;
	crc_data_len = sizeof(header->type) + sizeof(header->size) + payload_len;
	result = cs_protocol_crc32_check(crc_data, crc_data_len);
	if (result != CS_PROTOCOL_OK) {
		return result;
	}

	packet->type = sys_le16_to_cpu(header->type);
	packet->payload = &frame[CS_PROTOCOL_HEADER_SIZE];
	packet->payload_len = payload_len;
	packet->valid = true;

	return CS_PROTOCOL_OK;
}

void cs_protocol_parser_reset(struct cs_protocol_parser_t *parser) {
	if (parser == NULL) {
		return;
	}

	parser->buffer_len = 0U;
	parser->expected_frame_size = 0U;
	parser->state = CS_PROTOCOL_PARSER_START;
}

void cs_protocol_parser_init(struct cs_protocol_parser_t *parser,
                             uint8_t *buffer,
                             size_t buffer_size) {
	if (parser == NULL) {
		return;
	}

	parser->buffer = buffer;
	parser->buffer_size = buffer_size;
	cs_protocol_parser_reset(parser);
}

/* Drop the first buffered byte, a sync that did not lead to a valid frame, so
 * the search resumes right after it and a real frame behind it is not lost.
 */
static void parser_skip_sync(struct cs_protocol_parser_t *parser) {
	parser->buffer_len -= 1U;
	memmove(parser->buffer, &parser->buffer[1], parser->buffer_len);
	parser->expected_frame_size = 0U;
	parser->state = CS_PROTOCOL_PARSER_START;
}

/* Align the first sync to buffer[0] and read its frame size. Returns the new
 * state, or a negative error after skipping a sync whose size is invalid.
 */
static int parser_find_header(struct cs_protocol_parser_t *parser) {
	const struct cs_protocol_header_t *header;
	size_t pos;
	size_t discarded_size;
	uint16_t size;

	for (pos = 0U; pos + CS_PROTOCOL_HEADER_SIZE <= parser->buffer_len; ++pos) {
		header = (const struct cs_protocol_header_t *)&parser->buffer[pos];
		if (sys_le16_to_cpu(header->sync) != CS_PROTOCOL_SYNC) {
			continue;
		}
		if (pos != 0U) {
			parser->buffer_len -= pos;
			memmove(parser->buffer, &parser->buffer[pos], parser->buffer_len);
		}
		header = (const struct cs_protocol_header_t *)parser->buffer;
		size = sys_le16_to_cpu(header->size);
		if (size < CS_PROTOCOL_OVERHEAD) {
			parser_skip_sync(parser);
			return CS_PROTOCOL_ERR_LENGTH;
		}
		if (size > parser->buffer_size) {
			parser_skip_sync(parser);
			return CS_PROTOCOL_ERR_NO_SPACE;
		}

		parser->expected_frame_size = size;
		parser->state = CS_PROTOCOL_PARSER_GET_FRAME;
		return parser->state;
	}

	/*
	 * No complete header was found. Keep only the bytes that may still form
	 * the beginning of a header when more serial data arrives.
	 */
	if (parser->buffer_len >= CS_PROTOCOL_HEADER_SIZE) {
		discarded_size = parser->buffer_len - (CS_PROTOCOL_HEADER_SIZE - 1U);
		parser->buffer_len -= discarded_size;
		memmove(parser->buffer, &parser->buffer[discarded_size], parser->buffer_len);
	}

	return CS_PROTOCOL_PARSER_START;
}

/* Validate the frame occupying buffer[0 .. expected_frame_size); header sync
 * and length were already validated when the header was first found. */
static int parser_validate_frame(const struct cs_protocol_parser_t *parser) {
	const struct cs_protocol_header_t *header;
	const struct cs_protocol_footer_t *footer;
	const uint8_t *crc_data;
	size_t crc_data_len;
	uint16_t payload_len;

	header = (const struct cs_protocol_header_t *)parser->buffer;
	payload_len = sys_le16_to_cpu(header->size) - CS_PROTOCOL_OVERHEAD;

	footer = (const struct cs_protocol_footer_t *)&parser->buffer[CS_PROTOCOL_HEADER_SIZE + payload_len];
	if (sys_le16_to_cpu(footer->end_sync) != CS_PROTOCOL_END_SYNC) {
		return CS_PROTOCOL_ERR_SYNC;
	}

	crc_data = (const uint8_t *)&header->size;
	crc_data_len = sizeof(header->type) + sizeof(header->size) + payload_len;
	return cs_protocol_crc32_check(crc_data, crc_data_len);
}

/* Advance the state machine as far as the buffered bytes allow. A sync that
 * does not lead to a valid frame is skipped and the search resumes after it,
 * so noise never costs a real frame that follows. Returns FRAME_READY when a
 * frame is ready, otherwise the last error seen, otherwise the state.
 */
static int parser_process(struct cs_protocol_parser_t *parser) {
	int error = CS_PROTOCOL_OK;
	int result;

	for (;;) {
		if (parser->state == CS_PROTOCOL_PARSER_START) {
			result = parser_find_header(parser);
			if (result < 0) {
				error = result;
				continue;
			}
			if (parser->state == CS_PROTOCOL_PARSER_START) {
				break;
			}
		}

		if (parser->buffer_len < parser->expected_frame_size) {
			break;
		}

		result = parser_validate_frame(parser);
		if (result != CS_PROTOCOL_OK) {
			error = result;
			parser_skip_sync(parser);
			continue;
		}

		parser->state = CS_PROTOCOL_PARSER_FRAME_READY;
		return parser->state;
	}

	return error != CS_PROTOCOL_OK ? error : (int)parser->state;
}

int cs_protocol_parser_feed(struct cs_protocol_parser_t *parser,
                            const uint8_t *data,
                            size_t len,
                            size_t *consumed) {
	size_t room;
	size_t chunk;

	if (parser == NULL || parser->buffer == NULL || data == NULL || consumed == NULL) {
		return CS_PROTOCOL_ERR_ARGUMENT;
	}
	if (parser->buffer_size < CS_PROTOCOL_OVERHEAD) {
		return CS_PROTOCOL_ERR_ARGUMENT;
	}
	*consumed = 0U;

	if (parser->state == CS_PROTOCOL_PARSER_FRAME_READY) {
		return CS_PROTOCOL_PARSER_FRAME_READY;
	}
	if (parser->buffer_len >= parser->buffer_size) {
		cs_protocol_parser_reset(parser);
		return CS_PROTOCOL_ERR_NO_SPACE;
	}

	room = parser->buffer_size - parser->buffer_len;
	chunk = (len < room) ? len : room;
	if (chunk != 0U) {
		memcpy(&parser->buffer[parser->buffer_len], data, chunk);
		parser->buffer_len += chunk;
		*consumed = chunk;
	}
	switch (parser->state) {
	case CS_PROTOCOL_PARSER_START:
	case CS_PROTOCOL_PARSER_GET_FRAME:
		break;
	case CS_PROTOCOL_PARSER_FRAME_READY:
		/* The caller must call cs_protocol_parser_get_frame() before feeding
		 * more data.
		 */
		return CS_PROTOCOL_PARSER_FRAME_READY;
	default:
		cs_protocol_parser_reset(parser);
		return CS_PROTOCOL_ERR_FORMAT;
	}

	return parser_process(parser);
}

int cs_protocol_parser_get_frame(struct cs_protocol_parser_t *parser,
                                 uint8_t *frame_buffer,
                                 size_t *max_frame_size) {
	size_t leftover;

	if (parser == NULL || frame_buffer == NULL || max_frame_size == NULL) {
		return CS_PROTOCOL_ERR_ARGUMENT;
	}
	if (parser->state != CS_PROTOCOL_PARSER_FRAME_READY) {
		return CS_PROTOCOL_NEED_MORE;
	}
	if (parser->expected_frame_size > *max_frame_size) {
		return CS_PROTOCOL_ERR_NO_SPACE;
	}

	memcpy(frame_buffer, parser->buffer, parser->expected_frame_size);
	*max_frame_size = parser->expected_frame_size;

	leftover = parser->buffer_len - parser->expected_frame_size;
	if (leftover != 0U) {
		memmove(parser->buffer, &parser->buffer[parser->expected_frame_size], leftover);
	}
	parser->buffer_len = leftover;
	parser->expected_frame_size = 0U;
	parser->state = CS_PROTOCOL_PARSER_START;

	(void)parser_process(parser);

	return CS_PROTOCOL_OK;
}
