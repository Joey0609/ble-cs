/* SPDX-License-Identifier: MIT */
/**
 * @file cs_reports.h
 * @brief Parse an HCI CS subevent report into a packed, byte-aligned record.
 *
 * @section cs_reports_overview Overview
 *
 * The Bluetooth stack delivers Channel Sounding results one subevent at a
 * time: a subevent header plus a buffer of `[mode, channel, data_len, data]`
 * step entries where @c data is raw HCI wire data -- nibble-packed quality
 * indicators, 24-bit packed phase correction terms, little-endian multi-byte
 * fields and in-band "not available" sentinels. This module turns one such
 * report into one subevent record whose every field is a whole, byte-aligned
 * integer, written into a buffer the caller owns.
 *
 * @section cs_reports_record The record format
 *
 * A subevent record is one @ref cs_subevent followed immediately by
 * @ref cs_subevent.num_steps step records, back to back with no padding.
 * Everything common to the steps of a subevent -- identifiers, statuses,
 * antenna path count, timestamp -- lives once in the subevent header.
 *
 * @verbatim
 * cs_subevent
 * offset  size  field
 *      0     2  size                    total bytes, header and all steps
 *      2     1  num_steps               step records that follow
 *      3     1  config_id
 *      4     1  role                    enum bt_conn_le_cs_role
 *      5     1  rtt_type                enum bt_conn_le_cs_rtt_type
 *      6     1  num_antenna_paths
 *      7     1  reference_power_level
 *      8     2  subevent_id
 *     10     2  event_id
 *     12     2  procedure_id
 *     14     2  frequency_compensation
 *     16     1  procedure_done_status
 *     17     1  subevent_done_status
 *     18     1  procedure_abort_reason
 *     19     1  subevent_abort_reason
 *     20     1  abort_step
 *     21     1  reserved                written as zero
 *     22     8  timestamp_us
 *     30   ...  step records
 *
 * step record
 * offset  size  field
 *      0     1  type                    enum cs_step_type
 *      1     1  size                    total record bytes, header and body
 *      2     1  index                   step index within the subevent
 *      3   ...  body, layout named by type
 * @endverbatim
 *
 * Bodies are @ref cs_step_mode_0_initiator, @ref cs_step_mode_0_reflector,
 * @ref cs_step_mode_1, @ref cs_step_mode_1_ss_rtt, @ref cs_step_mode_2,
 * @ref cs_step_mode_3 and @ref cs_step_mode_3_ss_rtt. Every body starts with
 * the step's @c channel. The three tone-bearing bodies end in a
 * variable-length @ref cs_step_tone array.
 *
 * @section cs_reports_design Design principles
 *
 * - <b>Steps belong to their subevent.</b> A step record carries only what
 *   differs from step to step. Identity and context shared by the whole
 *   subevent are stored once, in @ref cs_subevent.
 * - <b>Records are self-describing.</b> The subevent header states its total
 *   size and step count, and every step record starts with its type and size.
 *   A reader walks the steps, and skips a type it does not recognize, without
 *   knowing anything about the bodies.
 * - <b>Every field is byte-aligned.</b> Nibbles are expanded to whole bytes,
 *   24-bit phase correction terms to @ref cs_step_iq, and tones to a real
 *   array. Nothing in a record needs shifting or masking to read.
 * - <b>Packed output, byte-wise input.</b> The record structs are @c __packed
 *   because they describe this module's own output, which is written field by
 *   field. The HCI payload is never dereferenced through a packed struct
 *   overlaid on it: multi-byte source fields are read with sys_get_le16().
 * - <b>The type carries what the mode cannot.</b> Mode 0 differs by role, and
 *   modes 1 and 3 differ by whether a sounding-sequence RTT type was
 *   negotiated. @ref cs_step_type folds all of that into one discriminant.
 * - <b>The caller owns the memory.</b> Nothing is allocated and the source
 *   buffer is not consumed. Output is bounded by the buffer size passed in.
 * - <b>Validate before writing.</b> Framing, step lengths and antenna
 *   permutations are checked in full before any byte is written, so malformed
 *   input never leaves a partial record. The only partial result is a buffer
 *   that fills up, and that record is still consistent (see cs_subevent_parse()).
 * - <b>Missing context comes from the caller.</b> A report says nothing about
 *   the role or RTT type that produced it and carries no subevent index. All
 *   three arrive in @ref cs_subevent_parse_cfg.
 * - <b>Sentinels are preserved, not interpreted.</b> An unavailable value
 *   keeps its HCI sentinel in the record. Test it with the @c *_valid() helpers
 *   rather than using the number directly.
 *
 * @section cs_reports_usage Usage
 *
 * @code{.c}
 * static struct cs_subevent_counter counter;
 * static uint8_t record[CS_SUBEVENT_BUF_SIZE(160)];
 *
 * static void subevent_result_cb(struct bt_conn *conn,
 *                                struct bt_conn_le_cs_subevent_result *result)
 * {
 *         struct cs_subevent_parse_cfg cfg = {
 *                 .role = cached_role,
 *                 .rtt_type = cached_rtt_type,
 *                 .subevent_id = cs_subevent_counter_next(&counter, result),
 *         };
 *         const struct cs_subevent *subevent = (const struct cs_subevent *)record;
 *         const struct cs_step_header *step;
 *         int err;
 *
 *         err = cs_subevent_parse(result, &cfg, record, sizeof(record));
 *         if (err != 0 && err != -ENOMEM) {
 *                 return;
 *         }
 *
 *         for (step = cs_step_first(subevent); step != NULL;
 *              step = cs_step_next(subevent, step)) {
 *                 if (step->type == CS_STEP_TYPE_MODE_2) {
 *                         const struct cs_step_mode_2 *body = cs_step_body(step);
 *                         uint8_t num_tones;
 *                         const struct cs_step_tone *tones =
 *                                 cs_step_tones(step, &num_tones);
 *
 *                         use_tones(body->channel, tones, num_tones);
 *                 }
 *         }
 * }
 * @endcode
 */
#ifndef CS_REPORTS_H_
#define CS_REPORTS_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/bluetooth/hci_types.h>
#include <zephyr/toolchain.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @defgroup cs_reports CS subevent and step parsing
 * @brief Turn one subevent report into a subevent record with its steps.
 *
 * See the @ref cs_reports.h file documentation for the record format, the design
 * principles behind it and a worked example.
 * @{
 */

/** Maximum antenna paths a CS step may report. */
#define CS_STEP_MAX_ANTENNA_PATHS 4U

/** Maximum tones per step: one per antenna path plus the extension slot. */
#define CS_STEP_MAX_TONES (CS_STEP_MAX_ANTENNA_PATHS + 1U)

/**
 * @brief CS step mode, as reported by the controller.
 *
 * A mode does not identify a record layout on its own; @ref cs_step_type does.
 */
enum cs_step_mode {
	/** Frequency offset and timing recovery. Layout differs by role. */
	CS_STEP_MODE_0 = 0x00,
	/** Round-trip time. */
	CS_STEP_MODE_1 = 0x01,
	/** Phase-based ranging; carries tones only. */
	CS_STEP_MODE_2 = 0x02,
	/** Round-trip time and phase-based ranging together. */
	CS_STEP_MODE_3 = 0x03,
};

/**
 * @brief Record type, naming the body struct that follows a step header.
 *
 * The step mode alone does not determine the layout: mode 0 differs by role,
 * and modes 1 and 3 differ by whether a sounding-sequence RTT type was
 * negotiated. The type resolves all of that into one discriminant.
 */
enum cs_step_type {
	/** Body is @ref cs_step_mode_0_initiator. */
	CS_STEP_TYPE_MODE_0_INITIATOR = 0x00,
	/** Body is @ref cs_step_mode_0_reflector. */
	CS_STEP_TYPE_MODE_0_REFLECTOR = 0x01,
	/** Body is @ref cs_step_mode_1. */
	CS_STEP_TYPE_MODE_1 = 0x02,
	/** Body is @ref cs_step_mode_1_ss_rtt. */
	CS_STEP_TYPE_MODE_1_SS_RTT = 0x03,
	/** Body is @ref cs_step_mode_2. */
	CS_STEP_TYPE_MODE_2 = 0x04,
	/** Body is @ref cs_step_mode_3. */
	CS_STEP_TYPE_MODE_3 = 0x05,
	/** Body is @ref cs_step_mode_3_ss_rtt. */
	CS_STEP_TYPE_MODE_3_SS_RTT = 0x06,
};

/**
 * @brief Subevent record header, followed by @c num_steps step records.
 *
 * Holds everything shared by the steps of one subevent. Enum-valued fields are
 * stored as single bytes; compare them against the Zephyr enum named in each
 * field's description.
 */
struct cs_subevent {
	/** Total record size in bytes: this header plus every step record. */
	uint16_t size;
	/** Step records following this header. */
	uint8_t num_steps;
	/** CS configuration identifier that produced this subevent, 0 to 3. */
	uint8_t config_id;
	/** Local role, one of @c bt_conn_le_cs_role, as given to the parser. */
	uint8_t role;
	/** RTT type, one of @c bt_conn_le_cs_rtt_type, as given to the parser. */
	uint8_t rtt_type;
	/** Antenna paths used during the phase measurement stage. */
	uint8_t num_antenna_paths;
	/** Reference power level in dBm, or @ref CS_SUBEVENT_REF_POWER_LEVEL_NOT_AVAILABLE. */
	int8_t reference_power_level;
	/** Zero-based index of the subevent within its procedure. */
	uint16_t subevent_id;
	/** ACL connection event the procedure started in. */
	uint16_t event_id;
	/** CS procedure counter these results belong to. */
	uint16_t procedure_id;
	/** Frequency compensation in 0.01 ppm, or @ref CS_SUBEVENT_FREQ_COMPENSATION_NOT_AVAILABLE. */
	uint16_t frequency_compensation;
	/** One of @c bt_conn_le_cs_procedure_done_status. */
	uint8_t procedure_done_status;
	/** One of @c bt_conn_le_cs_subevent_done_status. */
	uint8_t subevent_done_status;
	/** One of @c bt_conn_le_cs_procedure_abort_reason. */
	uint8_t procedure_abort_reason;
	/** One of @c bt_conn_le_cs_subevent_abort_reason. */
	uint8_t subevent_abort_reason;
	/** Step the subevent was aborted on, or 255 when it was not aborted. */
	uint8_t abort_step;
	/** Reserved for future use; written as zero. */
	uint8_t reserved;
	/** GRTC time the report was taken, in microseconds. */
	uint64_t timestamp_us;
} __attribute__((__packed__));

/** Sign-extended IQ pair decoded from a 24-bit HCI phase correction term. */
struct cs_step_iq {
	/** In-phase term, sign-extended from 12 bits. */
	int16_t i;
	/** Quadrature term, sign-extended from 12 bits. */
	int16_t q;
} __attribute__((__packed__));

/** One tone from a mode-2 or mode-3 step, with its nibbles expanded. */
struct cs_step_tone {
	/** Sign-extended, host-endian IQ pair decoded from the 24-bit PCT. */
	struct cs_step_iq iq;
	/** Antenna path this tone belongs to, resolved through the permutation. */
	uint8_t antenna_path;
	/** Tone quality. See BT_HCI_LE_CS_TONE_QUALITY_*. */
	uint8_t quality;
	/** Tone extension indicator. */
	uint8_t extension;
} __attribute__((__packed__));

/**
 * @brief Header every step record starts with.
 *
 * Only what is needed to walk the steps. Everything else a step reports is in
 * its body; everything it shares with its siblings is in @ref cs_subevent.
 */
struct cs_step_header {
	/** Record type, one of @ref cs_step_type. */
	uint8_t type;
	/** Total record size in bytes, header and body together. */
	uint8_t size;
	/** Zero-based index of this step within its subevent. */
	uint8_t index;
} __attribute__((__packed__));

/** Mode 0, initiator. Body of a @ref CS_STEP_TYPE_MODE_0_INITIATOR record. */
struct cs_step_mode_0_initiator {
	/** CS channel index, as reported. */
	uint8_t channel;
	/** Access-address check result, expanded from its nibble. */
	uint8_t aa_quality;
	/** Access-address bit error count, expanded from its nibble. */
	uint8_t bit_errors;
	/** Packet RSSI in dBm, or @ref CS_STEP_RSSI_NOT_AVAILABLE. */
	int8_t rssi;
	/** Antenna the packet was received on. */
	uint8_t antenna;
	/**
	 * Measured frequency offset in 0.01 ppm units, or
	 * @ref CS_STEP_FREQ_OFFSET_NOT_AVAILABLE. Only the initiator measures it.
	 */
	uint16_t measured_freq_offset;
} __attribute__((__packed__));

/**
 * @brief Mode 0, reflector. Body of a @ref CS_STEP_TYPE_MODE_0_REFLECTOR record.
 *
 * Identical to @ref cs_step_mode_0_initiator without the frequency offset,
 * which only an initiator measures.
 */
struct cs_step_mode_0_reflector {
	/** CS channel index, as reported. */
	uint8_t channel;
	/** Access-address check result, expanded from its nibble. */
	uint8_t aa_quality;
	/** Access-address bit error count, expanded from its nibble. */
	uint8_t bit_errors;
	/** Packet RSSI in dBm, or @ref CS_STEP_RSSI_NOT_AVAILABLE. */
	int8_t rssi;
	/** Antenna the packet was received on. */
	uint8_t antenna;
} __attribute__((__packed__));

/**
 * @brief Mode 1 without a sounding-sequence RTT type.
 *
 * Body of a @ref CS_STEP_TYPE_MODE_1 record. Its fields are also the leading
 * fields of @ref cs_step_mode_1_ss_rtt, @ref cs_step_mode_3 and
 * @ref cs_step_mode_3_ss_rtt, in the same order and at the same offsets.
 */
struct cs_step_mode_1 {
	/** CS channel index, as reported. */
	uint8_t channel;
	/** Access-address check result, expanded from its nibble. */
	uint8_t aa_quality;
	/** Access-address bit error count, expanded from its nibble. */
	uint8_t bit_errors;
	/** Normalized attack detector metric. */
	uint8_t nadm;
	/** Packet RSSI in dBm, or @ref CS_STEP_RSSI_NOT_AVAILABLE. */
	int8_t rssi;
	/**
	 * Round-trip time difference in half-nanoseconds, or
	 * @ref CS_STEP_TIME_DIFFERENCE_NOT_AVAILABLE. This is ToA-ToD for an
	 * initiator and ToD-ToA for a reflector; @ref cs_subevent.role says which.
	 */
	int16_t time_difference;
	/** Antenna the packet was received on. */
	uint8_t antenna;
} __attribute__((__packed__));

/**
 * @brief Mode 1 with a sounding-sequence RTT type.
 *
 * Body of a @ref CS_STEP_TYPE_MODE_1_SS_RTT record: @ref cs_step_mode_1 plus
 * the two packet phase correction terms a sounding sequence carries.
 */
struct cs_step_mode_1_ss_rtt {
	/** CS channel index, as reported. */
	uint8_t channel;
	/** Access-address check result, expanded from its nibble. */
	uint8_t aa_quality;
	/** Access-address bit error count, expanded from its nibble. */
	uint8_t bit_errors;
	/** Normalized attack detector metric. */
	uint8_t nadm;
	/** Packet RSSI in dBm, or @ref CS_STEP_RSSI_NOT_AVAILABLE. */
	int8_t rssi;
	/** Round-trip time difference. See @ref cs_step_mode_1.time_difference. */
	int16_t time_difference;
	/** Antenna the packet was received on. */
	uint8_t antenna;
	/** First packet phase correction term, decoded. */
	struct cs_step_iq pct1;
	/** Second packet phase correction term, decoded. */
	struct cs_step_iq pct2;
} __attribute__((__packed__));

/**
 * @brief Mode 2. Body of a @ref CS_STEP_TYPE_MODE_2 record.
 *
 * Tones only; a mode-2 step carries no packet quality or RSSI.
 */
struct cs_step_mode_2 {
	/** CS channel index, as reported. */
	uint8_t channel;
	/** Raw antenna path permutation index, as reported. */
	uint8_t antenna_permutation_index;
	/** Entries in @c tones: one per antenna path plus the extension slot. */
	uint8_t num_tones;
	/** Decoded tones. Reach them through cs_step_tones(). */
	struct cs_step_tone tones[];
} __attribute__((__packed__));

/**
 * @brief Mode 3 without a sounding-sequence RTT type.
 *
 * Body of a @ref CS_STEP_TYPE_MODE_3 record: the @ref cs_step_mode_1 fields
 * followed by the tones of a mode-2 step.
 */
struct cs_step_mode_3 {
	/** CS channel index, as reported. */
	uint8_t channel;
	/** Access-address check result, expanded from its nibble. */
	uint8_t aa_quality;
	/** Access-address bit error count, expanded from its nibble. */
	uint8_t bit_errors;
	/** Normalized attack detector metric. */
	uint8_t nadm;
	/** Packet RSSI in dBm, or @ref CS_STEP_RSSI_NOT_AVAILABLE. */
	int8_t rssi;
	/** Round-trip time difference. See @ref cs_step_mode_1.time_difference. */
	int16_t time_difference;
	/** Antenna the packet was received on. */
	uint8_t antenna;
	/** Raw antenna path permutation index, as reported. */
	uint8_t antenna_permutation_index;
	/** Entries in @c tones: one per antenna path plus the extension slot. */
	uint8_t num_tones;
	/** Decoded tones. Reach them through cs_step_tones(). */
	struct cs_step_tone tones[];
} __attribute__((__packed__));

/**
 * @brief Mode 3 with a sounding-sequence RTT type.
 *
 * Body of a @ref CS_STEP_TYPE_MODE_3_SS_RTT record: @ref cs_step_mode_3 with
 * the two packet phase correction terms inserted before the permutation index,
 * matching the HCI layout.
 */
struct cs_step_mode_3_ss_rtt {
	/** CS channel index, as reported. */
	uint8_t channel;
	/** Access-address check result, expanded from its nibble. */
	uint8_t aa_quality;
	/** Access-address bit error count, expanded from its nibble. */
	uint8_t bit_errors;
	/** Normalized attack detector metric. */
	uint8_t nadm;
	/** Packet RSSI in dBm, or @ref CS_STEP_RSSI_NOT_AVAILABLE. */
	int8_t rssi;
	/** Round-trip time difference. See @ref cs_step_mode_1.time_difference. */
	int16_t time_difference;
	/** Antenna the packet was received on. */
	uint8_t antenna;
	/** First packet phase correction term, decoded. */
	struct cs_step_iq pct1;
	/** Second packet phase correction term, decoded. */
	struct cs_step_iq pct2;
	/** Raw antenna path permutation index, as reported. */
	uint8_t antenna_permutation_index;
	/** Entries in @c tones: one per antenna path plus the extension slot. */
	uint8_t num_tones;
	/** Decoded tones. Reach them through cs_step_tones(). */
	struct cs_step_tone tones[];
} __attribute__((__packed__));

/** Largest step record this module emits: a mode-3 SS-RTT step with 4 antenna paths. */
#define CS_STEP_MAX_SIZE                                                    \
	(sizeof(struct cs_step_header) + sizeof(struct cs_step_mode_3_ss_rtt) + \
	 CS_STEP_MAX_TONES * sizeof(struct cs_step_tone))

/**
 * @brief Buffer size that always holds a subevent of @p num_steps steps.
 * @param num_steps Steps to make room for; a subevent reports at most 160.
 */
#define CS_SUBEVENT_BUF_SIZE(num_steps) (sizeof(struct cs_subevent) + (size_t)(num_steps) * CS_STEP_MAX_SIZE)

/** Value in a step's @c rssi meaning the controller reported no measurement. */
#define CS_STEP_RSSI_NOT_AVAILABLE ((int8_t)BT_HCI_LE_CS_PACKET_RSSI_NOT_AVAILABLE)

/** Value in @c time_difference meaning the controller reported no measurement. */
#define CS_STEP_TIME_DIFFERENCE_NOT_AVAILABLE BT_HCI_LE_CS_TIME_DIFFERENCE_NOT_AVAILABLE

/**
 * Value in @c measured_freq_offset meaning the initiator reported no
 * measurement. The field is 15 bits wide, so this cannot collide with a real
 * measurement.
 */
#define CS_STEP_FREQ_OFFSET_NOT_AVAILABLE UINT16_C(0xc000)

/** Value in @ref cs_subevent.frequency_compensation meaning none is available. */
#define CS_SUBEVENT_FREQ_COMPENSATION_NOT_AVAILABLE \
	((uint16_t)BT_HCI_LE_CS_SUBEVENT_RESULT_FREQ_COMPENSATION_NOT_AVAILABLE)

/** Value in @ref cs_subevent.reference_power_level meaning none is available. */
#define CS_SUBEVENT_REF_POWER_LEVEL_NOT_AVAILABLE ((int8_t)BT_HCI_LE_CS_REF_POWER_LEVEL_UNAVAILABLE)

/**
 * @brief Test whether an RSSI field holds a measurement.
 * @param[in] rssi Value of a step's @c rssi field.
 * @return true when @p rssi is a real measurement, false for the sentinel.
 */
static inline bool cs_step_rssi_valid(int8_t rssi) {
	return rssi != CS_STEP_RSSI_NOT_AVAILABLE;
}

/**
 * @brief Test whether a time difference field holds a measurement.
 * @param[in] time_difference Value of a step's @c time_difference field.
 * @return true when @p time_difference is a real measurement.
 */
static inline bool cs_step_time_difference_valid(int16_t time_difference) {
	return time_difference != CS_STEP_TIME_DIFFERENCE_NOT_AVAILABLE;
}

/**
 * @brief Test whether a frequency offset field holds a measurement.
 * @param[in] measured_freq_offset Value of @c measured_freq_offset.
 * @return true when @p measured_freq_offset is a real measurement.
 */
static inline bool cs_step_freq_offset_valid(uint16_t measured_freq_offset) {
	return measured_freq_offset != CS_STEP_FREQ_OFFSET_NOT_AVAILABLE;
}

/**
 * @brief Test whether a subevent reports a frequency compensation value.
 * @param[in] frequency_compensation Value of @ref cs_subevent.frequency_compensation.
 * @return true when @p frequency_compensation is a real value.
 */
static inline bool cs_subevent_freq_compensation_valid(uint16_t frequency_compensation) {
	return frequency_compensation != CS_SUBEVENT_FREQ_COMPENSATION_NOT_AVAILABLE;
}

/**
 * @brief Test whether a subevent reports a reference power level.
 * @param[in] reference_power_level Value of @ref cs_subevent.reference_power_level.
 * @return true when @p reference_power_level is a real value.
 */
static inline bool cs_subevent_ref_power_level_valid(int8_t reference_power_level) {
	return reference_power_level != CS_SUBEVENT_REF_POWER_LEVEL_NOT_AVAILABLE;
}

/**
 * @brief Layout and identity inputs the report itself does not carry.
 *
 * A subevent report says nothing about the role or RTT type that produced it,
 * and carries no subevent index. All three come from the caller. The role and
 * RTT type must match the CS configuration named by the report's @c config_id,
 * or steps will be checked against the wrong layout and rejected as @c -EBADMSG.
 */
struct cs_subevent_parse_cfg {
	/** Role of the endpoint that produced the report. */
	enum bt_conn_le_cs_role role;
	/** Negotiated RTT type; mode-3 lengths cannot identify the layout alone. */
	enum bt_conn_le_cs_rtt_type rtt_type;
	/** Index of this subevent within its procedure. See @ref cs_subevent_counter. */
	uint16_t subevent_id;
	/** Report timestamp in microseconds, or 0 to sample the GRTC now. */
	uint64_t timestamp_us;
};

/**
 * @brief Derives a subevent index by counting reports within a procedure.
 *
 * Zero-initialize before the first subevent. The Bluetooth report carries a
 * procedure counter but no subevent index, so this counts reports and restarts
 * whenever the procedure counter changes.
 */
struct cs_subevent_counter {
	/** Procedure counter the current count belongs to. */
	uint16_t procedure_id;
	/** Index handed out for the most recent subevent. */
	uint16_t subevent_id;
	/** False until the first subevent has been counted. */
	bool started;
};

/**
 * @brief Take the next subevent index for @p result.
 * @param[in,out] counter Counter state, zero-initialized before first use.
 * @param[in] result Subevent report about to be parsed.
 * @return Zero-based index of this subevent within its procedure, or 0 when
 *         either argument is NULL.
 * @note Call exactly once per report. Calling it twice for the same report
 *       advances the index twice.
 */
uint16_t cs_subevent_counter_next(struct cs_subevent_counter *counter,
                                  const struct bt_conn_le_cs_subevent_result *result);

/**
 * @brief Read the GRTC in microseconds.
 * @return Current timestamp, on the same time base written into records.
 * @note Falls back to the kernel uptime when the GRTC timer is not enabled, in
 *       which case the value is still microseconds but a different epoch.
 */
uint64_t cs_subevent_timestamp_us(void);

/**
 * @brief Parse one subevent report into a subevent record.
 *
 * Writes a @ref cs_subevent at offset 0 of @p buf, followed by one step record
 * per reported step. The record is only ever left in a consistent state: its
 * @c size and @c num_steps always describe exactly the steps written.
 *
 * @param[in] result Subevent report, as delivered by the SDK callback.
 * @param[in] cfg Role, RTT type, subevent index and timestamp for this report.
 * @param[out] buf Destination, cast to @ref cs_subevent to read it back. Bytes
 *                 past @ref cs_subevent.size are left untouched.
 * @param[in] buf_size Capacity of @p buf in bytes. Size it with
 *                     @ref CS_SUBEVENT_BUF_SIZE to make @c -ENOMEM impossible.
 * @retval 0 The subevent and every reported step were written.
 * @retval -EINVAL NULL argument, @p buf_size too small for the subevent
 *                 header, an invalid role, RTT type or antenna path count, or
 *                 an antenna permutation the SDK rejects. Nothing is written.
 * @retval -EBADMSG Truncated framing, or a step whose length does not match
 *                  the layout @p cfg selects. Nothing is written.
 * @retval -ENOTSUP A step mode outside the 0 to 3 range. Nothing is written.
 * @retval -ENOMEM Buffer filled before the last step. A valid subevent record
 *                 holding the steps that fit is written; compare its
 *                 @c num_steps with the report's @c num_steps_reported.
 */
int cs_subevent_parse(const struct bt_conn_le_cs_subevent_result *result,
                      const struct cs_subevent_parse_cfg *cfg,
                      void *buf,
                      size_t buf_size);

/** Value of @ref cs_subevent.abort_step when no step was aborted or the source does not say (RAS). */
#define CS_SUBEVENT_ABORT_STEP_NONE UINT8_C(0xff)

/**
 * @brief Read one `[mode, channel, data_len, data]` entry of HCI or RAS step data.
 *
 * Does not consume @p steps: @p offset is advanced past the entry instead, so a
 * buffer can be walked more than once (see cs_step_decode()).
 *
 * @param[in] steps Step data, e.g. @c bt_conn_le_cs_subevent_result.step_data_buf.
 * @param[in,out] offset Byte offset of the entry; 0 for the first one.
 * @param[out] step Entry; @c data points into @p steps.
 * @retval 0 @p step filled and @p offset advanced.
 * @retval -ENODATA No entry left.
 * @retval -EBADMSG Truncated entry.
 * @retval -EINVAL NULL argument.
 */
int cs_step_data_read(const struct net_buf_simple *steps,
                      size_t *offset,
                      struct bt_le_cs_subevent_step *step);

/**
 * @brief Tones a step record of @p mode carries.
 * @return @p num_antenna_paths + 1 (extension slot) for modes 2 and 3, 0 otherwise.
 */
uint8_t cs_step_num_tones(uint8_t mode, uint8_t num_antenna_paths);

/**
 * @brief Decode a single step into one step record.
 *
 * The per-step part of cs_subevent_parse(), for callers that stream a subevent
 * step by step instead of building a whole record: the largest buffer needed
 * is @ref CS_STEP_MAX_SIZE. Called with @p dst NULL it only validates the step
 * and returns the record size, so a first pass can size the output and a
 * second pass decode with the same result.
 *
 * @param[in] step Step entry, from cs_step_data_read() or the RAS parser.
 * @param[in] cfg Role and RTT type of the endpoint that measured the step.
 * @param[in] num_antenna_paths Antenna paths of the subevent, 1 to 4.
 * @param[in] index Step index written into the record header.
 * @param[out] dst Destination, or NULL to validate only.
 * @param[in] size Capacity of @p dst.
 * @return Record size in bytes (also with @p dst NULL).
 * @retval -EINVAL NULL @p step, invalid @p cfg or antenna path count, or an
 *                 antenna permutation the SDK rejects.
 * @retval -EBADMSG Length does not match the layout @p cfg selects.
 * @retval -ENOTSUP Step mode outside 0 to 3.
 * @retval -ENOMEM @p size is smaller than the record; nothing written.
 */
int cs_step_decode(const struct bt_le_cs_subevent_step *step,
                   const struct cs_subevent_parse_cfg *cfg,
                   uint8_t num_antenna_paths,
                   uint8_t index,
                   uint8_t *dst,
                   size_t size);

/**
 * @brief First step record of a subevent.
 * @param[in] subevent Subevent record written by cs_subevent_parse().
 * @return First step, or NULL when there are none or it does not fit within
 *         @ref cs_subevent.size.
 */
const struct cs_step_header *cs_step_first(const struct cs_subevent *subevent);

/**
 * @brief Step record following @p current in the same subevent.
 * @param[in] subevent Subevent record @p current belongs to.
 * @param[in] current Step previously returned for @p subevent.
 * @return Next step, or NULL after the last one.
 */
const struct cs_step_header *cs_step_next(const struct cs_subevent *subevent,
                                          const struct cs_step_header *current);

/**
 * @brief Body of a step record, to be cast to the struct its type names.
 * @param[in] step Step header.
 * @return Pointer to the first body byte.
 * @note The result is not aligned for the body struct, which is why every body
 *       is @c __packed. Do not copy it into an unpacked struct by cast.
 */
static inline const void *cs_step_body(const struct cs_step_header *step) {
	return (const uint8_t *)step + sizeof(*step);
}

/**
 * @brief Tones of a mode-2 or mode-3 step record.
 * @param[in] step Step header.
 * @param[out] num_tones Tones in the returned array; set to zero when there
 *                       are none. May be NULL.
 * @return Tone array, or NULL when the record type carries no tones or its
 *         tone count disagrees with the size it declares.
 */
const struct cs_step_tone *cs_step_tones(const struct cs_step_header *step,
                                         uint8_t *num_tones);

/** Buffer size that always holds the cs_step_print() output for any step record. */
#define CS_STEP_PRINT_SIZE 768U

/** Buffer size that always holds the cs_subevent_header_print() output. */
#define CS_SUBEVENT_HEADER_PRINT_SIZE 384U

/**
 * @brief Format one step record as text.
 *
 * Writes the step header, the body fields its type carries and every tone.
 * Lines end in '\n'.
 *
 * @param[out] buf Destination; always NUL-terminated when @p size is non-zero.
 * @param[in] size Capacity of @p buf in bytes. @ref CS_STEP_PRINT_SIZE never
 *                 truncates.
 * @param[in] step Step to describe. Not modified or retained.
 * @return Characters written, excluding the NUL.
 * @retval -EINVAL @p buf or @p step is NULL, or @p size is zero; no output.
 * @retval -ENOSPC Output did not fit; @p buf holds the truncated prefix.
 * @note Issues no output of its own; the caller decides where the text goes.
 */
int cs_step_print(char *buf, size_t size, const struct cs_step_header *step);

/**
 * @brief Format a subevent header as text, without its steps.
 *
 * A subevent of up to 160 steps with tones formats to far more text than one
 * buffer should hold, so steps are formatted one call at a time:
 *
 * @code{.c}
 * char text[CS_STEP_PRINT_SIZE];
 *
 * if (cs_subevent_header_print(text, sizeof(text), subevent) > 0) {
 *         output(text);
 * }
 * for (step = cs_step_first(subevent); step; step = cs_step_next(subevent, step)) {
 *         if (cs_step_print(text, sizeof(text), step) > 0) {
 *                 output(text);
 *         }
 * }
 * @endcode
 *
 * @param[out] buf Destination; always NUL-terminated when @p size is non-zero.
 * @param[in] size Capacity of @p buf in bytes.
 *                 @ref CS_SUBEVENT_HEADER_PRINT_SIZE never truncates.
 * @param[in] subevent Subevent record written by cs_subevent_parse().
 * @return Characters written, excluding the NUL.
 * @retval -EINVAL @p buf or @p subevent is NULL, or @p size is zero; no output.
 * @retval -ENOSPC Output did not fit; @p buf holds the truncated prefix.
 */
int cs_subevent_header_print(char *buf, size_t size, const struct cs_subevent *subevent);

/** @} */
#ifdef __cplusplus
}
#endif
#endif /* CS_REPORTS_H_ */
