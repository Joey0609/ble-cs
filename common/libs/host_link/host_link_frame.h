/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief Protocol frame written piece by piece, with an incremental CRC.
 *
 * A frame whose payload is produced incrementally (a streamed subevent result)
 * is written straight into a byte sink: the header when it begins, payload
 * pieces as they come, the CRC footer when it ends. The byte stream equals
 * the frame cs_protocol_finalize_frame() would produce from the same payload.
 *
 * The sink reserves room for the whole frame when it begins, so a frame is
 * either queued whole or not at all. If fewer payload bytes than announced
 * are written, the rest is zero-filled and the CRC is inverted, so the host
 * discards the frame instead of misreading it.
 *
 * No Zephyr kernel dependency (tested natively in tests/host_link).
 */

#ifndef HOST_LINK_FRAME_H_
#define HOST_LINK_FRAME_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Destination of a streamed frame. */
struct host_link_frame_sink {
	/** Reserve room for @p len bytes; nonzero refuses the frame. Must not block. */
	int (*begin)(void *ctx, size_t len);
	/** Append bytes to the reserved frame. */
	void (*write)(void *ctx, const uint8_t *data, size_t len);
	/** Complete the frame. */
	int (*end)(void *ctx);
	/** Passed to every call. */
	void *ctx;
};

/** Writer state of one frame. */
struct host_link_frame {
	const struct host_link_frame_sink *sink;
	uint32_t crc;
	size_t payload_remaining;
	bool open;
};

/**
 * @brief Begin a frame of @p type with @p payload_len payload bytes.
 * @retval 0 Header written; the frame is open.
 * @retval -EMSGSIZE The frame exceeds the protocol size limit.
 * @return Other nonzero value returned by the sink's @c begin.
 */
int host_link_frame_begin(struct host_link_frame *frame, const struct host_link_frame_sink *sink,
                          uint16_t type, size_t payload_len);

/** @brief Append payload bytes; bytes beyond the announced length are ignored. */
void host_link_frame_write(struct host_link_frame *frame, const uint8_t *data, size_t len);

/**
 * @brief Write the footer and close the frame.
 * @param valid False invalidates the CRC, so the host discards the frame.
 * @retval 0 A valid frame was completed.
 * @retval -EIO The frame was short or @p valid was false; its CRC is invalid.
 * @return Other nonzero value returned by the sink's @c end.
 */
int host_link_frame_end(struct host_link_frame *frame, bool valid);

#ifdef __cplusplus
}
#endif

#endif /* HOST_LINK_FRAME_H_ */
