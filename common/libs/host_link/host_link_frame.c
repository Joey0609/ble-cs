/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <string.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/crc.h>

#include "cs_protocol/cs_protocol.h"
#include "host_link_frame.h"

int host_link_frame_begin(struct host_link_frame *frame, const struct host_link_frame_sink *sink,
                          uint16_t type, size_t payload_len) {
	uint8_t header[CS_PROTOCOL_HEADER_SIZE];
	size_t len = payload_len + CS_PROTOCOL_OVERHEAD;
	int err;

	frame->open = false;
	if (payload_len > CS_PROTOCOL_MAX_PAYLOAD) {
		return -EMSGSIZE;
	}
	err = sink->begin(sink->ctx, len);
	if (err) {
		return err;
	}
	sys_put_le16(CS_PROTOCOL_SYNC, header);
	sys_put_le16((uint16_t)len, header + 2);
	sys_put_le16(type, header + 4);
	sink->write(sink->ctx, header, sizeof(header));
	/* The CRC covers size, type and payload, not the sync word. */
	*frame = (struct host_link_frame){
		.sink = sink,
		.crc = crc32_ieee_update(0U, header + 2, sizeof(header) - 2U),
		.payload_remaining = payload_len,
		.open = true,
	};
	return 0;
}

void host_link_frame_write(struct host_link_frame *frame, const uint8_t *data, size_t len) {
	if (!frame->open) {
		return;
	}
	len = len < frame->payload_remaining ? len : frame->payload_remaining;
	frame->crc = crc32_ieee_update(frame->crc, data, len);
	frame->sink->write(frame->sink->ctx, data, len);
	frame->payload_remaining -= len;
}

int host_link_frame_end(struct host_link_frame *frame, bool valid) {
	static const uint8_t zeros[32];
	uint8_t footer[CS_PROTOCOL_FOOTER_SIZE];
	int err;

	if (!frame->open) {
		return -EINVAL;
	}
	if (frame->payload_remaining != 0U) {
		valid = false;
		while (frame->payload_remaining != 0U) {
			host_link_frame_write(frame, zeros, sizeof(zeros));
		}
	}
	sys_put_le32(valid ? frame->crc : ~frame->crc, footer);
	sys_put_le16(CS_PROTOCOL_END_SYNC, footer + 4);
	frame->sink->write(frame->sink->ctx, footer, sizeof(footer));
	frame->open = false;
	err = frame->sink->end(frame->sink->ctx);
	return err ? err : (valid ? 0 : -EIO);
}
