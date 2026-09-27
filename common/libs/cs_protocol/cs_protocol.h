/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief CS protocol framing, CRC, frame codec and UART stream parser.
 *
 * Message IDs and complete frame layouts are in cs_protocol_packets.h.
 */

#ifndef CS_PROTOCOL_H_
#define CS_PROTOCOL_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @defgroup cs_protocol CS protocol
 * @brief Byte-frame protocol between a host and a Channel Sounding client.
 *
 * Every frame has the same layout. All multi-byte integers are little endian
 * and there is no padding:
 *
 * @code
 * offset      size  field
 * 0           2     sync      CS_PROTOCOL_SYNC (0x5AA5)          \
 * 2           2     size      total frame size, 12..65535         | header
 * 4           2     type      enum cs_protocol_packet_type_t      /
 * 6           N     payload   message fields, N = size - 12
 * size - 6    4     crc32     CRC-32/IEEE over size, type, payload \ footer
 * size - 2    2     end_sync  CS_PROTOCOL_END_SYNC (0xA55A)        /
 * @endcode
 *
 * - @c size counts the whole frame, header and footer included.
 * - @c crc32 is CRC-32/IEEE (reflected polynomial 0xEDB88320, initial value
 *   0xFFFFFFFF, final XOR 0xFFFFFFFF; check value for "123456789" is
 *   0xCBF43926). It covers bytes 2 .. size - 7. The sync markers are
 *   deliberately excluded so that they can be used for stream recovery.
 *
 * The library only frames bytes. It does not interpret payloads, convert
 * utility records or sequence commands; that is application work.
 * @{
 */

/**
 * @defgroup cs_protocol_framing Framing
 * @brief Frame markers, sizes and the common header and footer.
 * @{
 */

/** Value of @ref cs_protocol_header_t.sync, first on the wire as 0xA5 0x5A. */
#define CS_PROTOCOL_SYNC UINT16_C(0x5AA5)
/** Value of @ref cs_protocol_footer_t.end_sync, last on the wire as 0x5A 0xA5. */
#define CS_PROTOCOL_END_SYNC UINT16_C(0xA55A)

/** Size of @ref cs_protocol_header_t in bytes (6). */
#define CS_PROTOCOL_HEADER_SIZE sizeof(struct cs_protocol_header_t)
/** Size of the CRC-32 field in bytes (4). */
#define CS_PROTOCOL_CRC_SIZE sizeof(uint32_t)
/** Size of @ref cs_protocol_footer_t in bytes (6). */
#define CS_PROTOCOL_FOOTER_SIZE sizeof(struct cs_protocol_footer_t)
/** Framing bytes in every frame: header plus footer (12). */
#define CS_PROTOCOL_OVERHEAD (CS_PROTOCOL_HEADER_SIZE + CS_PROTOCOL_FOOTER_SIZE)
/** Largest payload, limited by the 16-bit @ref cs_protocol_header_t.size. */
#define CS_PROTOCOL_MAX_PAYLOAD (UINT16_MAX - CS_PROTOCOL_OVERHEAD)
/** Largest complete frame (65535). */
#define CS_PROTOCOL_MAX_FRAME_SIZE (CS_PROTOCOL_OVERHEAD + CS_PROTOCOL_MAX_PAYLOAD)

/**
 * @brief Common frame header, first member of every frame struct.
 *
 * Written by cs_protocol_finalize_frame(); fields are little endian.
 */
struct cs_protocol_header_t {
	/** Start marker, @ref CS_PROTOCOL_SYNC. */
	uint16_t sync;
	/** Total frame size in bytes, header and footer included. */
	uint16_t size;
	/** Message ID, one of @ref cs_protocol_packet_type_t. */
	uint16_t type;
} __attribute__((__packed__));

/**
 * @brief Common frame footer, last member of every fixed-size frame struct.
 *
 * Variable-length frames cannot declare it after their flexible array; there
 * it is located at offset @c header.size - @ref CS_PROTOCOL_FOOTER_SIZE.
 * Written by cs_protocol_finalize_frame(); fields are little endian.
 */
struct cs_protocol_footer_t {
	/** CRC-32/IEEE over @c size, @c type and the payload. */
	uint32_t crc32;
	/** End marker, @ref CS_PROTOCOL_END_SYNC. */
	uint16_t end_sync;
} __attribute__((__packed__));

_Static_assert(sizeof(struct cs_protocol_header_t) == 6U,
               "CS protocol header must be packed");
_Static_assert(offsetof(struct cs_protocol_header_t,
                        size) == 2U,
               "Frame size offset");
_Static_assert(offsetof(struct cs_protocol_header_t,
                        type) == 4U,
               "Frame type offset");
_Static_assert(sizeof(struct cs_protocol_footer_t) == 6U,
               "CS protocol footer must be packed");

/** @} */

/**
 * @defgroup cs_protocol_codec Frame codec
 * @brief CRC helpers, frame encoding and decoding.
 * @{
 */

/** Return codes. Negative values are errors. */
enum cs_protocol_result {
	/** Success. */
	CS_PROTOCOL_OK = 0,
	/** No complete frame is available yet. */
	CS_PROTOCOL_NEED_MORE = 1,
	/** A required pointer is NULL or the parser is misconfigured. */
	CS_PROTOCOL_ERR_ARGUMENT = -1,
	/** The output or parser buffer is too small. */
	CS_PROTOCOL_ERR_NO_SPACE = -2,
	/** A size is outside the valid frame range or does not match. */
	CS_PROTOCOL_ERR_LENGTH = -3,
	/** A sync or end-sync marker is wrong. */
	CS_PROTOCOL_ERR_SYNC = -4,
	/** The CRC does not match. */
	CS_PROTOCOL_ERR_CRC = -5,
	/** Internal state is invalid. */
	CS_PROTOCOL_ERR_FORMAT = -6,
};

/**
 * @brief Compute CRC-32/IEEE.
 *
 * @param data     Bytes to checksum.
 * @param data_len Number of bytes.
 * @return The CRC value.
 */
uint32_t cs_protocol_crc32(const void *data,
                           size_t data_len);

/**
 * @brief Append a little-endian CRC-32 after @p data_len bytes of @p buffer.
 *
 * @param buffer          Data, with room for the CRC after it.
 * @param buffer_capacity Total writable bytes in @p buffer.
 * @param data_len        Bytes to checksum.
 * @return @p data_len + @ref CS_PROTOCOL_CRC_SIZE,
 *         @ref CS_PROTOCOL_ERR_ARGUMENT or @ref CS_PROTOCOL_ERR_NO_SPACE.
 */
int cs_protocol_crc32_append(uint8_t *buffer,
                             size_t buffer_capacity,
                             size_t data_len);

/**
 * @brief Verify a little-endian CRC-32 stored right after @p data_len bytes.
 *
 * @param buffer   Data followed by its 4-byte CRC.
 * @param data_len Bytes covered by the CRC, excluding the CRC itself.
 * @return @ref CS_PROTOCOL_OK, @ref CS_PROTOCOL_ERR_CRC or
 *         @ref CS_PROTOCOL_ERR_ARGUMENT.
 */
int cs_protocol_crc32_check(const uint8_t *buffer,
                            size_t data_len);

/**
 * @brief Decoded view of a frame, filled by cs_protocol_decode().
 *
 * @c type, @c payload and @c payload_len are meaningful only when @c valid
 * is true.
 */
struct cs_protocol_packet_t {
	/**
	 * True when sync, size, end sync and CRC were all verified. Cleared at
	 * the start of every cs_protocol_decode() call, so a failed decode never
	 * leaves a stale valid packet behind.
	 */
	bool valid;
	/** Message ID from the header, one of @ref cs_protocol_packet_type_t. */
	uint16_t type;
	/** First payload byte; points into the decoded frame buffer. */
	const uint8_t *payload;
	/** Payload length, @c size - @ref CS_PROTOCOL_OVERHEAD. */
	uint16_t payload_len;
};

/**
 * @brief Finish a complete wire frame in place.
 *
 * The caller supplies @p frame_size writable bytes with the message fields
 * already filled in little endian, typically one of the frame structs from
 * cs_protocol_packets.h. Only the header (@c sync, @c size, @c type) and the
 * footer (@c crc32, @c end_sync) are written; the payload is not interpreted.
 * No allocation or conversion is performed.
 *
 * @param frame      Start of the frame.
 * @param frame_size Complete frame size, header and footer included.
 * @param type       Message ID, one of @ref cs_protocol_packet_type_t.
 * @return @p frame_size, @ref CS_PROTOCOL_ERR_ARGUMENT, or
 *         @ref CS_PROTOCOL_ERR_LENGTH when @p frame_size is outside
 *         @ref CS_PROTOCOL_OVERHEAD .. @ref CS_PROTOCOL_MAX_FRAME_SIZE.
 */
int cs_protocol_finalize_frame(void *frame,
                               size_t frame_size,
                               uint16_t type);

/**
 * @brief Encode one complete frame from serialized payload bytes.
 *
 * @param frame          Output buffer.
 * @param frame_capacity Writable bytes in @p frame.
 * @param type           Message ID, one of @ref cs_protocol_packet_type_t.
 * @param payload        Payload bytes; may be NULL when @p payload_len is 0.
 * @param payload_len    Payload length, at most @ref CS_PROTOCOL_MAX_PAYLOAD.
 * @return The frame length, or a negative @ref cs_protocol_result.
 */
int cs_protocol_encode(uint8_t *frame,
                       size_t frame_capacity,
                       uint16_t type,
                       const void *payload,
                       size_t payload_len);

/**
 * @brief Encode one frame whose payload is the concatenation of two parts.
 *
 * Useful for a fixed prefix followed by variable data without an extra copy
 * by the caller.
 *
 * @param frame              Output buffer.
 * @param frame_capacity     Writable bytes in @p frame.
 * @param type               Message ID, one of @ref cs_protocol_packet_type_t.
 * @param payload_part_1     First part; may be NULL when its length is 0.
 * @param payload_part_1_len Length of the first part.
 * @param payload_part_2     Second part; may be NULL when its length is 0.
 * @param payload_part_2_len Length of the second part.
 * @return The frame length, @ref CS_PROTOCOL_ERR_ARGUMENT,
 *         @ref CS_PROTOCOL_ERR_LENGTH when the combined payload exceeds
 *         @ref CS_PROTOCOL_MAX_PAYLOAD, or @ref CS_PROTOCOL_ERR_NO_SPACE.
 */
int cs_protocol_encode_parts(uint8_t *frame,
                             size_t frame_capacity,
                             uint16_t type,
                             const void *payload_part_1,
                             size_t payload_part_1_len,
                             const void *payload_part_2,
                             size_t payload_part_2_len);

/**
 * @brief Validate framing and CRC, then decode the common header.
 *
 * @p packet->valid is cleared first and set only on success.
 * @p packet->payload points into @p frame. The application must check the
 * type-specific size and field values before using them. Unknown message IDs
 * are accepted; the application decides which ones it supports.
 *
 * @param frame     One complete frame.
 * @param frame_len Number of bytes in @p frame; must equal the header size.
 * @param packet    Filled on success.
 * @return @ref CS_PROTOCOL_OK, @ref CS_PROTOCOL_ERR_ARGUMENT,
 *         @ref CS_PROTOCOL_ERR_LENGTH, @ref CS_PROTOCOL_ERR_SYNC or
 *         @ref CS_PROTOCOL_ERR_CRC.
 */
int cs_protocol_decode(const uint8_t *frame,
                       size_t frame_len,
                       struct cs_protocol_packet_t *packet);

/** @} */

/**
 * @defgroup cs_protocol_parser Stream parser
 * @brief Incremental frame parser for fragmented UART byte streams.
 *
 * Bytes preceding a valid sync are discarded and the detected frame is
 * compacted to @c buffer[0]. Check @c parser.state rather than the return
 * value to find ready frames. Typical use:
 *
 * @code
 * while (len > 0) {
 *     size_t consumed;
 *     int state = cs_protocol_parser_feed(&parser, data, len, &consumed);
 *     data += consumed;
 *     len -= consumed;
 *     while (state == CS_PROTOCOL_PARSER_FRAME_READY) {
 *         size_t frame_size = sizeof(frame);
 *         if (cs_protocol_parser_get_frame(&parser, frame, &frame_size) != CS_PROTOCOL_OK) {
 *             break;
 *         }
 *         handle(frame, frame_size);
 *         state = parser.state;
 *     }
 * }
 * @endcode
 * @{
 */

/** Parser states, returned by cs_protocol_parser_feed(). */
enum cs_protocol_parser_state_t {
	/** Searching for a header. */
	CS_PROTOCOL_PARSER_START = 0,
	/** Header found; waiting for the rest of the frame. */
	CS_PROTOCOL_PARSER_GET_FRAME,
	/** A validated frame is waiting for cs_protocol_parser_get_frame(). */
	CS_PROTOCOL_PARSER_FRAME_READY,
};

/** @brief Parser context. Initialize with cs_protocol_parser_init(). */
struct cs_protocol_parser_t {
	/** Caller-owned storage; must hold the largest expected frame. */
	uint8_t *buffer;
	/** Capacity of @c buffer, at least @ref CS_PROTOCOL_OVERHEAD. */
	size_t buffer_size;
	/** Bytes currently buffered. */
	size_t buffer_len;
	/** Size of the frame being received, from its header; 0 in START. */
	size_t expected_frame_size;
	/** Current state. */
	enum cs_protocol_parser_state_t state;
};

/**
 * @brief Initialize a parser with caller-owned storage.
 *
 * @param parser      Parser to initialize.
 * @param buffer      Storage for incoming bytes.
 * @param buffer_size Capacity of @p buffer. Frames larger than this are
 *                    rejected with @ref CS_PROTOCOL_ERR_NO_SPACE.
 */
void cs_protocol_parser_init(struct cs_protocol_parser_t *parser,
                             uint8_t *buffer,
                             size_t buffer_size);

/**
 * @brief Feed up to @p len bytes into the parser.
 *
 * @p *consumed is set to how many bytes were copied into the parser's buffer,
 * which may be less than @p len when the buffer fills. If the parser is
 * already holding an unclaimed frame (@ref CS_PROTOCOL_PARSER_FRAME_READY),
 * @p *consumed is 0 and @p data is untouched: call
 * cs_protocol_parser_get_frame() and retry with the same data.
 *
 * @param parser   Parser context.
 * @param data     Received bytes.
 * @param len      Number of bytes in @p data.
 * @param consumed Set to the number of bytes taken from @p data.
 * A sync marker whose frame turns out invalid (bad size, end sync or CRC) is
 * skipped one byte at a time, and the search resumes right after it, so a
 * valid frame behind noise or a corrupted frame is still found.
 *
 * @return @ref CS_PROTOCOL_PARSER_FRAME_READY when a frame is ready, otherwise
 *         a negative @ref cs_protocol_result if an invalid frame was skipped,
 *         otherwise the new @ref cs_protocol_parser_state_t. The parser stays
 *         usable after an error; @c state always holds the current state.
 */
int cs_protocol_parser_feed(struct cs_protocol_parser_t *parser,
                            const uint8_t *data,
                            size_t len,
                            size_t *consumed);

/**
 * @brief Copy out the validated frame while in @ref CS_PROTOCOL_PARSER_FRAME_READY.
 *
 * Data buffered past the end of the frame is preserved and immediately
 * re-checked for the next header, so the parser may already be in
 * @ref CS_PROTOCOL_PARSER_FRAME_READY again for a following frame.
 *
 * @param parser         Parser context.
 * @param frame_buffer   Destination for the frame.
 * @param max_frame_size In: capacity of @p frame_buffer. Out: frame size.
 * @return @ref CS_PROTOCOL_OK, @ref CS_PROTOCOL_NEED_MORE when no frame is
 *         ready, @ref CS_PROTOCOL_ERR_NO_SPACE when @p frame_buffer is too
 *         small (the frame is kept), or @ref CS_PROTOCOL_ERR_ARGUMENT.
 */
int cs_protocol_parser_get_frame(struct cs_protocol_parser_t *parser,
                                 uint8_t *frame_buffer,
                                 size_t *max_frame_size);

/**
 * @brief Discard all buffered data and return to @ref CS_PROTOCOL_PARSER_START.
 *
 * @param parser Parser context; NULL is ignored.
 */
void cs_protocol_parser_reset(struct cs_protocol_parser_t *parser);

/** @} */

/** @} */

#ifdef __cplusplus
}
#endif

#endif /* CS_PROTOCOL_H_ */
