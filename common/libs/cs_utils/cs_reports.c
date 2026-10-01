/* SPDX-License-Identifier: MIT */
#include "cs_reports.h"
#include "cs_print_internal.h"

#include <errno.h>
#include <stddef.h>
#include <string.h>
#include <zephyr/bluetooth/hci.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/byteorder.h>

#if defined(CONFIG_NRF_GRTC_TIMER)
#include <zephyr/drivers/timer/nrf_grtc_timer.h>
#endif

/* Nibble packing used by the HCI packet quality and tone indicator bytes. */
#define NIBBLE_LOW(byte) ((uint8_t)((byte) & 0x0fU))
#define NIBBLE_HIGH(byte) ((uint8_t)((byte) >> 4))

/* Size of one HCI tone entry: a 24-bit PCT plus the packed indicator byte. */
#define TONE_ENTRY_SIZE 4U

/* Header sizes of the HCI step data layouts, excluding any trailing tones.
 * These mirror the struct bt_hci_le_cs_step_data_* definitions in hci_types.h.
 */
#define HCI_MODE_0_INITIATOR 5U
#define HCI_MODE_0_REFLECTOR 3U
#define HCI_MODE_1 6U
#define HCI_MODE_1_SS_RTT 14U
#define HCI_MODE_2 1U
#define HCI_MODE_3 7U
#define HCI_MODE_3_SS_RTT 15U

/* Offsets within the HCI payload. Modes 1 and 3 share a common prefix, and
 * mode 0 packs its RSSI and antenna one byte earlier.
 */
#define OFF_QUALITY 0U
#define OFF_MODE_0_RSSI 1U
#define OFF_MODE_0_ANTENNA 2U
#define OFF_MODE_0_FREQ_OFFSET 3U
#define OFF_NADM 1U
#define OFF_RSSI 2U
#define OFF_TIME_DIFFERENCE 3U
#define OFF_ANTENNA 5U
#define OFF_PCT1 6U
#define OFF_PCT2 10U

/* The HCI layout constants above are the parser's only assumption about the
 * source. Tie them to the SDK's own definitions so an SDK layout change fails
 * the build instead of silently mis-parsing. The nibble-packed quality byte is
 * a bitfield and has no offsetof, so it is checked by struct size alone.
 */
BUILD_ASSERT(HCI_MODE_0_INITIATOR == sizeof(struct bt_hci_le_cs_step_data_mode_0_initiator));
BUILD_ASSERT(HCI_MODE_0_REFLECTOR == sizeof(struct bt_hci_le_cs_step_data_mode_0_reflector));
BUILD_ASSERT(HCI_MODE_1 == sizeof(struct bt_hci_le_cs_step_data_mode_1));
BUILD_ASSERT(HCI_MODE_1_SS_RTT == sizeof(struct bt_hci_le_cs_step_data_mode_1_ss_rtt));
BUILD_ASSERT(HCI_MODE_2 == sizeof(struct bt_hci_le_cs_step_data_mode_2));
BUILD_ASSERT(HCI_MODE_3 == sizeof(struct bt_hci_le_cs_step_data_mode_3));
BUILD_ASSERT(HCI_MODE_3_SS_RTT == sizeof(struct bt_hci_le_cs_step_data_mode_3_ss_rtt));
BUILD_ASSERT(TONE_ENTRY_SIZE == sizeof(struct bt_hci_le_cs_step_data_tone_info));

BUILD_ASSERT(OFF_MODE_0_RSSI == offsetof(struct bt_hci_le_cs_step_data_mode_0_reflector,
                                         packet_rssi));
BUILD_ASSERT(OFF_MODE_0_ANTENNA == offsetof(struct bt_hci_le_cs_step_data_mode_0_reflector,
                                            packet_antenna));
BUILD_ASSERT(OFF_MODE_0_FREQ_OFFSET == offsetof(struct bt_hci_le_cs_step_data_mode_0_initiator,
                                                measured_freq_offset));
BUILD_ASSERT(OFF_NADM == offsetof(struct bt_hci_le_cs_step_data_mode_1,
                                  packet_nadm));
BUILD_ASSERT(OFF_RSSI == offsetof(struct bt_hci_le_cs_step_data_mode_1,
                                  packet_rssi));
BUILD_ASSERT(OFF_TIME_DIFFERENCE == offsetof(struct bt_hci_le_cs_step_data_mode_1,
                                             toa_tod_initiator));
BUILD_ASSERT(OFF_ANTENNA == offsetof(struct bt_hci_le_cs_step_data_mode_1,
                                     packet_antenna));
BUILD_ASSERT(OFF_PCT1 == offsetof(struct bt_hci_le_cs_step_data_mode_1_ss_rtt,
                                  packet_pct1));
BUILD_ASSERT(OFF_PCT2 == offsetof(struct bt_hci_le_cs_step_data_mode_1_ss_rtt,
                                  packet_pct2));
/* Modes 1 and 3 must keep the shared prefix the parser relies on. */
BUILD_ASSERT(OFF_NADM == offsetof(struct bt_hci_le_cs_step_data_mode_3,
                                  packet_nadm));
BUILD_ASSERT(OFF_RSSI == offsetof(struct bt_hci_le_cs_step_data_mode_3,
                                  packet_rssi));
BUILD_ASSERT(OFF_TIME_DIFFERENCE == offsetof(struct bt_hci_le_cs_step_data_mode_3,
                                             toa_tod_initiator));
BUILD_ASSERT(OFF_ANTENNA == offsetof(struct bt_hci_le_cs_step_data_mode_3,
                                     packet_antenna));
BUILD_ASSERT(OFF_PCT1 == offsetof(struct bt_hci_le_cs_step_data_mode_3_ss_rtt,
                                  packet_pct1));
BUILD_ASSERT(OFF_PCT2 == offsetof(struct bt_hci_le_cs_step_data_mode_3_ss_rtt,
                                  packet_pct2));
/* The permutation index is the last byte before the tones in every tone mode. */
BUILD_ASSERT(HCI_MODE_2 - 1U == offsetof(struct bt_hci_le_cs_step_data_mode_2,
                                         antenna_permutation_index));
BUILD_ASSERT(HCI_MODE_3 - 1U == offsetof(struct bt_hci_le_cs_step_data_mode_3,
                                         antenna_permutation_index));
BUILD_ASSERT(HCI_MODE_3_SS_RTT - 1U == offsetof(struct bt_hci_le_cs_step_data_mode_3_ss_rtt,
                                                antenna_permutation_index));

/* The output records are written field by field into a byte buffer, so their
 * sizes are part of this module's contract rather than a compiler accident.
 */
BUILD_ASSERT(sizeof(struct cs_subevent) == 30U);
BUILD_ASSERT(sizeof(struct cs_step_iq) == 4U);
BUILD_ASSERT(sizeof(struct cs_step_tone) == 7U);
BUILD_ASSERT(sizeof(struct cs_step_header) == 3U);
BUILD_ASSERT(sizeof(struct cs_step_mode_0_initiator) == 7U);
BUILD_ASSERT(sizeof(struct cs_step_mode_0_reflector) == 5U);
BUILD_ASSERT(sizeof(struct cs_step_mode_1) == 8U);
BUILD_ASSERT(sizeof(struct cs_step_mode_1_ss_rtt) == 16U);
BUILD_ASSERT(sizeof(struct cs_step_mode_2) == 3U);
BUILD_ASSERT(sizeof(struct cs_step_mode_3) == 10U);
BUILD_ASSERT(sizeof(struct cs_step_mode_3_ss_rtt) == 18U);
/* Every body starts with the channel, so a reader can find it without the type. */
BUILD_ASSERT(offsetof(struct cs_step_mode_0_initiator, channel) == 0U);
BUILD_ASSERT(offsetof(struct cs_step_mode_0_reflector, channel) == 0U);
BUILD_ASSERT(offsetof(struct cs_step_mode_1, channel) == 0U);
BUILD_ASSERT(offsetof(struct cs_step_mode_1_ss_rtt, channel) == 0U);
BUILD_ASSERT(offsetof(struct cs_step_mode_2, channel) == 0U);
BUILD_ASSERT(offsetof(struct cs_step_mode_3, channel) == 0U);
BUILD_ASSERT(offsetof(struct cs_step_mode_3_ss_rtt, channel) == 0U);
/* A step's size is one byte, so no step record may grow past what it can express. */
BUILD_ASSERT(CS_STEP_MAX_SIZE <= UINT8_MAX);
/* A subevent's size is two bytes and it holds at most UINT8_MAX steps. */
BUILD_ASSERT(CS_SUBEVENT_BUF_SIZE(UINT8_MAX) <= UINT16_MAX);

/* Size of the [mode, channel, data_len] prefix of an HCI step entry. */
#define HCI_STEP_PREFIX 3U

static bool cfg_valid(const struct cs_subevent_parse_cfg *cfg) {
	if (cfg == NULL) {
		return false;
	}
	if (cfg->role != BT_CONN_LE_CS_ROLE_INITIATOR && cfg->role != BT_CONN_LE_CS_ROLE_REFLECTOR) {
		return false;
	}
	switch (cfg->rtt_type) {
	case BT_CONN_LE_CS_RTT_TYPE_AA_ONLY:
	case BT_CONN_LE_CS_RTT_TYPE_32_BIT_SOUNDING:
	case BT_CONN_LE_CS_RTT_TYPE_96_BIT_SOUNDING:
	case BT_CONN_LE_CS_RTT_TYPE_32_BIT_RANDOM:
	case BT_CONN_LE_CS_RTT_TYPE_64_BIT_RANDOM:
	case BT_CONN_LE_CS_RTT_TYPE_96_BIT_RANDOM:
	case BT_CONN_LE_CS_RTT_TYPE_128_BIT_RANDOM:
		return true;
	default:
		return false;
	}
}

static bool sounding(const struct cs_subevent_parse_cfg *cfg) {
	return cfg->rtt_type == BT_CONN_LE_CS_RTT_TYPE_32_BIT_SOUNDING ||
	       cfg->rtt_type == BT_CONN_LE_CS_RTT_TYPE_96_BIT_SOUNDING;
}

/* Resolve the record type from the step mode plus the configuration context.
 * The mode alone is not enough: mode 0 differs by role, and modes 1 and 3
 * differ by RTT type. Mode 3 lengths in particular cannot distinguish a
 * sounding-sequence step from one carrying two extra tones.
 */
static int type_resolve(uint8_t mode,
                        const struct cs_subevent_parse_cfg *cfg,
                        enum cs_step_type *type) {
	switch ((enum cs_step_mode)mode) {
	case CS_STEP_MODE_0:
		*type = cfg->role == BT_CONN_LE_CS_ROLE_INITIATOR ? CS_STEP_TYPE_MODE_0_INITIATOR
		                                                  : CS_STEP_TYPE_MODE_0_REFLECTOR;
		return 0;
	case CS_STEP_MODE_1:
		*type = sounding(cfg) ? CS_STEP_TYPE_MODE_1_SS_RTT : CS_STEP_TYPE_MODE_1;
		return 0;
	case CS_STEP_MODE_2:
		*type = CS_STEP_TYPE_MODE_2;
		return 0;
	case CS_STEP_MODE_3:
		*type = sounding(cfg) ? CS_STEP_TYPE_MODE_3_SS_RTT : CS_STEP_TYPE_MODE_3;
		return 0;
	default:
		return -ENOTSUP;
	}
}

/* Tones a record of this type carries: one per antenna path plus the
 * extension slot for the tone-bearing modes, none otherwise.
 */
static uint8_t type_num_tones(enum cs_step_type type,
                              uint8_t num_antenna_paths) {
	switch (type) {
	case CS_STEP_TYPE_MODE_2:
	case CS_STEP_TYPE_MODE_3:
	case CS_STEP_TYPE_MODE_3_SS_RTT:
		return (uint8_t)(num_antenna_paths + 1U);
	default:
		return 0U;
	}
}

/* Bytes of HCI payload a step of this type must carry, tones included. */
static size_t type_hci_len(enum cs_step_type type,
                           uint8_t num_tones) {
	size_t tones = (size_t)num_tones * TONE_ENTRY_SIZE;

	switch (type) {
	case CS_STEP_TYPE_MODE_0_INITIATOR:
		return HCI_MODE_0_INITIATOR;
	case CS_STEP_TYPE_MODE_0_REFLECTOR:
		return HCI_MODE_0_REFLECTOR;
	case CS_STEP_TYPE_MODE_1:
		return HCI_MODE_1;
	case CS_STEP_TYPE_MODE_1_SS_RTT:
		return HCI_MODE_1_SS_RTT;
	case CS_STEP_TYPE_MODE_2:
		return HCI_MODE_2 + tones;
	case CS_STEP_TYPE_MODE_3:
		return HCI_MODE_3 + tones;
	case CS_STEP_TYPE_MODE_3_SS_RTT:
		return HCI_MODE_3_SS_RTT + tones;
	default:
		return 0U;
	}
}

/* Offset of the antenna path permutation index within the HCI payload. */
static size_t type_permutation_offset(enum cs_step_type type) {
	switch (type) {
	case CS_STEP_TYPE_MODE_2:
		return HCI_MODE_2 - 1U;
	case CS_STEP_TYPE_MODE_3:
		return HCI_MODE_3 - 1U;
	case CS_STEP_TYPE_MODE_3_SS_RTT:
		return HCI_MODE_3_SS_RTT - 1U;
	default:
		return 0U;
	}
}

/* Size of the fixed part of a record body, before any tones. */
static size_t type_body_size(enum cs_step_type type) {
	switch (type) {
	case CS_STEP_TYPE_MODE_0_INITIATOR:
		return sizeof(struct cs_step_mode_0_initiator);
	case CS_STEP_TYPE_MODE_0_REFLECTOR:
		return sizeof(struct cs_step_mode_0_reflector);
	case CS_STEP_TYPE_MODE_1:
		return sizeof(struct cs_step_mode_1);
	case CS_STEP_TYPE_MODE_1_SS_RTT:
		return sizeof(struct cs_step_mode_1_ss_rtt);
	case CS_STEP_TYPE_MODE_2:
		return sizeof(struct cs_step_mode_2);
	case CS_STEP_TYPE_MODE_3:
		return sizeof(struct cs_step_mode_3);
	case CS_STEP_TYPE_MODE_3_SS_RTT:
		return sizeof(struct cs_step_mode_3_ss_rtt);
	default:
		return 0U;
	}
}

/* Total bytes a step record of this type occupies, header and tones included. */
static size_t type_record_size(enum cs_step_type type,
                               uint8_t num_tones) {
	return sizeof(struct cs_step_header) + type_body_size(type) +
	       (size_t)num_tones * sizeof(struct cs_step_tone);
}

int cs_step_data_read(const struct net_buf_simple *steps,
                      size_t *offset,
                      struct bt_le_cs_subevent_step *step) {
	const uint8_t *entry;

	if (steps == NULL || offset == NULL || step == NULL) {
		return -EINVAL;
	}
	if (*offset >= steps->len) {
		return -ENODATA;
	}
	if (steps->data == NULL || steps->len - *offset < HCI_STEP_PREFIX ||
	    steps->data[*offset + 2] > steps->len - *offset - HCI_STEP_PREFIX) {
		return -EBADMSG;
	}
	entry = steps->data + *offset;
	*step = (struct bt_le_cs_subevent_step){
		.mode = entry[0],
		.channel = entry[1],
		.data_len = entry[2],
		.data = entry + HCI_STEP_PREFIX,
	};
	*offset += HCI_STEP_PREFIX + step->data_len;
	return 0;
}

/* Decode a 24-bit HCI phase correction term into a byte-aligned IQ pair. */
static struct cs_step_iq parse_iq(const uint8_t *pct) {
	struct bt_le_cs_iq_sample sample = bt_le_cs_parse_pct(pct);

	return (struct cs_step_iq){ .i = sample.i, .q = sample.q };
}

/* Build the channel, packet quality, NADM, RSSI, time difference and antenna
 * prefix shared by every mode 1 and mode 3 layout. Written through a local
 * value and copied, so the caller may place it at any offset in the output.
 */
static struct cs_step_mode_1 parse_rtt_prefix(const struct bt_le_cs_subevent_step *step) {
	const uint8_t *data = step->data;

	return (struct cs_step_mode_1){
		.channel = step->channel,
		.aa_quality = NIBBLE_LOW(data[OFF_QUALITY]),
		.bit_errors = NIBBLE_HIGH(data[OFF_QUALITY]),
		.nadm = data[OFF_NADM],
		.rssi = (int8_t)data[OFF_RSSI],
		.time_difference = (int16_t)sys_get_le16(data + OFF_TIME_DIFFERENCE),
		.antenna = data[OFF_ANTENNA],
	};
}

/* Expand the tone array of a mode 2 or mode 3 step into the output buffer.
 * dst points at the first tone slot, which need not be aligned. The
 * permutation was checked by subevent_validate(), so every path resolves.
 */
static void parse_tones(const uint8_t *data,
                        enum cs_step_type type,
                        uint8_t num_antenna_paths,
                        uint8_t num_tones,
                        uint8_t permutation,
                        uint8_t *dst) {
	size_t hci_offset = type_hci_len(type, 0U);

	for (uint8_t i = 0; i < num_tones; i++) {
		const uint8_t *entry = data + hci_offset + (size_t)i * TONE_ENTRY_SIZE;
		struct cs_step_tone tone = {
			.iq = parse_iq(entry),
			.antenna_path = (uint8_t)bt_le_cs_get_antenna_path(num_antenna_paths, permutation, i),
			.quality = NIBBLE_LOW(entry[3]),
			.extension = NIBBLE_HIGH(entry[3]),
		};

		memcpy(dst + (size_t)i * sizeof(tone), &tone, sizeof(tone));
	}
}

/* Expand one step's HCI payload into a record body at dst. */
static void parse_body(const struct bt_le_cs_subevent_step *step,
                       enum cs_step_type type,
                       uint8_t num_antenna_paths,
                       uint8_t num_tones,
                       uint8_t *dst) {
	const uint8_t *data = step->data;
	uint8_t permutation = data[type_permutation_offset(type)];

	switch (type) {
	case CS_STEP_TYPE_MODE_0_INITIATOR: {
		struct cs_step_mode_0_initiator body = {
			.channel = step->channel,
			.aa_quality = NIBBLE_LOW(data[OFF_QUALITY]),
			.bit_errors = NIBBLE_HIGH(data[OFF_QUALITY]),
			.rssi = (int8_t)data[OFF_MODE_0_RSSI],
			.antenna = data[OFF_MODE_0_ANTENNA],
			.measured_freq_offset = sys_get_le16(data + OFF_MODE_0_FREQ_OFFSET),
		};

		memcpy(dst, &body, sizeof(body));
		break;
	}
	case CS_STEP_TYPE_MODE_0_REFLECTOR: {
		struct cs_step_mode_0_reflector body = {
			.channel = step->channel,
			.aa_quality = NIBBLE_LOW(data[OFF_QUALITY]),
			.bit_errors = NIBBLE_HIGH(data[OFF_QUALITY]),
			.rssi = (int8_t)data[OFF_MODE_0_RSSI],
			.antenna = data[OFF_MODE_0_ANTENNA],
		};

		memcpy(dst, &body, sizeof(body));
		break;
	}
	case CS_STEP_TYPE_MODE_1: {
		struct cs_step_mode_1 body = parse_rtt_prefix(step);

		memcpy(dst, &body, sizeof(body));
		break;
	}
	case CS_STEP_TYPE_MODE_1_SS_RTT: {
		struct cs_step_mode_1_ss_rtt body;
		struct cs_step_mode_1 prefix = parse_rtt_prefix(step);

		memcpy(&body, &prefix, sizeof(prefix));
		body.pct1 = parse_iq(data + OFF_PCT1);
		body.pct2 = parse_iq(data + OFF_PCT2);
		memcpy(dst, &body, sizeof(body));
		break;
	}
	case CS_STEP_TYPE_MODE_2: {
		struct cs_step_mode_2 body = {
			.channel = step->channel,
			.antenna_permutation_index = permutation,
			.num_tones = num_tones,
		};

		memcpy(dst, &body, sizeof(body));
		parse_tones(data, type, num_antenna_paths, num_tones, permutation, dst + sizeof(body));
		break;
	}
	case CS_STEP_TYPE_MODE_3: {
		struct cs_step_mode_3 body;
		struct cs_step_mode_1 prefix = parse_rtt_prefix(step);

		memcpy(&body, &prefix, sizeof(prefix));
		body.antenna_permutation_index = permutation;
		body.num_tones = num_tones;
		memcpy(dst, &body, sizeof(body));
		parse_tones(data, type, num_antenna_paths, num_tones, permutation, dst + sizeof(body));
		break;
	}
	case CS_STEP_TYPE_MODE_3_SS_RTT: {
		struct cs_step_mode_3_ss_rtt body;
		struct cs_step_mode_1 prefix = parse_rtt_prefix(step);

		memcpy(&body, &prefix, sizeof(prefix));
		body.pct1 = parse_iq(data + OFF_PCT1);
		body.pct2 = parse_iq(data + OFF_PCT2);
		body.antenna_permutation_index = permutation;
		body.num_tones = num_tones;
		memcpy(dst, &body, sizeof(body));
		parse_tones(data, type, num_antenna_paths, num_tones, permutation, dst + sizeof(body));
		break;
	}
	default:
		break;
	}
}

uint8_t cs_step_num_tones(uint8_t mode, uint8_t num_antenna_paths) {
	return (mode == CS_STEP_MODE_2 || mode == CS_STEP_MODE_3) ? (uint8_t)(num_antenna_paths + 1U) : 0U;
}

int cs_step_decode(const struct bt_le_cs_subevent_step *step,
                   const struct cs_subevent_parse_cfg *cfg,
                   uint8_t num_antenna_paths,
                   uint8_t index,
                   uint8_t *dst,
                   size_t size) {
	struct cs_step_header header;
	enum cs_step_type type;
	uint8_t num_tones;
	size_t record_size;
	int err;

	if (step == NULL || !cfg_valid(cfg) || num_antenna_paths > CS_STEP_MAX_ANTENNA_PATHS) {
		return -EINVAL;
	}
	err = type_resolve(step->mode, cfg, &type);
	if (err) {
		return err;
	}
	num_tones = type_num_tones(type, num_antenna_paths);
	/* The controller reports no antenna paths when no step measures phase
	 * (mode 1 only); a step with tones needs at least one.
	 */
	if (num_tones != 0U && num_antenna_paths < 1U) {
		return -EINVAL;
	}
	if (step->data_len != type_hci_len(type, num_tones) || (step->data_len && step->data == NULL)) {
		return -EBADMSG;
	}
	for (uint8_t i = 0; i < num_tones; i++) {
		if (bt_le_cs_get_antenna_path(num_antenna_paths, step->data[type_permutation_offset(type)],
		                              i) < 0) {
			return -EINVAL;
		}
	}
	record_size = type_record_size(type, num_tones);
	if (dst == NULL) {
		return (int)record_size;
	}
	if (size < record_size) {
		return -ENOMEM;
	}
	header = (struct cs_step_header){
		.type = (uint8_t)type,
		.size = (uint8_t)record_size,
		.index = index,
	};
	memcpy(dst, &header, sizeof(header));
	parse_body(step, type, num_antenna_paths, num_tones, dst + sizeof(header));
	return (int)record_size;
}

/* Check everything that could make a step fail to parse -- framing, mode,
 * length against the configured layout and antenna permutation -- so that
 * the write pass that follows can only stop for lack of room.
 */
static int subevent_validate(const struct net_buf_simple *steps,
                             const struct cs_subevent_parse_cfg *cfg,
                             uint8_t num_antenna_paths) {
	struct bt_le_cs_subevent_step step;
	size_t offset = 0;
	size_t count = 0;
	int err;

	if (steps == NULL || steps->len == 0U) {
		return 0;
	}
	while ((err = cs_step_data_read(steps, &offset, &step)) == 0) {
		/* num_steps and index are single bytes. */
		if (++count > UINT8_MAX) {
			return -EBADMSG;
		}
		err = cs_step_decode(&step, cfg, num_antenna_paths, 0U, NULL, 0U);
		if (err < 0) {
			return err;
		}
	}
	return err == -ENODATA ? 0 : err;
}

int cs_subevent_parse(const struct bt_conn_le_cs_subevent_result *result,
                      const struct cs_subevent_parse_cfg *cfg,
                      void *buf,
                      size_t buf_size) {
	const struct net_buf_simple *steps;
	struct cs_subevent subevent;
	struct bt_le_cs_subevent_step step;
	uint8_t *out = buf;
	size_t offset = 0;
	size_t written = sizeof(subevent);
	int err;

	if (result == NULL || buf == NULL || buf_size < sizeof(subevent) || !cfg_valid(cfg)) {
		return -EINVAL;
	}
	/* Zero is valid: no phase measurement (mode 1 only). The tone-bearing
	 * steps are checked against it one by one in subevent_validate().
	 */
	if (result->header.num_antenna_paths > CS_STEP_MAX_ANTENNA_PATHS) {
		return -EINVAL;
	}
	steps = result->step_data_buf;
	err = subevent_validate(steps, cfg, result->header.num_antenna_paths);
	if (err) {
		return err;
	}

	subevent = (struct cs_subevent){
		.config_id = result->header.config_id,
		.role = (uint8_t)cfg->role,
		.rtt_type = (uint8_t)cfg->rtt_type,
		.num_antenna_paths = result->header.num_antenna_paths,
		.reference_power_level = result->header.reference_power_level,
		.subevent_id = cfg->subevent_id,
		.event_id = result->header.start_acl_conn_event,
		.procedure_id = result->header.procedure_counter,
		.frequency_compensation = result->header.frequency_compensation,
		.procedure_done_status = (uint8_t)result->header.procedure_done_status,
		.subevent_done_status = (uint8_t)result->header.subevent_done_status,
		.procedure_abort_reason = (uint8_t)result->header.procedure_abort_reason,
		.subevent_abort_reason = (uint8_t)result->header.subevent_abort_reason,
		.abort_step = result->header.abort_step,
		.timestamp_us = cfg->timestamp_us != 0U ? cfg->timestamp_us : cs_subevent_timestamp_us(),
	};

	while (steps != NULL && cs_step_data_read(steps, &offset, &step) == 0) {
		int size = cs_step_decode(&step, cfg, subevent.num_antenna_paths, subevent.num_steps,
		                          out + written, buf_size - written);

		if (size < 0) {
			/* Validated above: only a full buffer stops the write pass. */
			err = -ENOMEM;
			break;
		}
		written += (size_t)size;
		subevent.num_steps++;
	}

	/* Written last, so size and num_steps describe exactly the steps above. */
	subevent.size = (uint16_t)written;
	memcpy(out, &subevent, sizeof(subevent));
	return err;
}

uint16_t cs_subevent_counter_next(struct cs_subevent_counter *counter,
                                  const struct bt_conn_le_cs_subevent_result *result) {
	if (counter == NULL || result == NULL) {
		return 0U;
	}
	if (!counter->started || counter->procedure_id != result->header.procedure_counter) {
		counter->started = true;
		counter->procedure_id = result->header.procedure_counter;
		counter->subevent_id = 0U;
	} else {
		counter->subevent_id++;
	}
	return counter->subevent_id;
}

uint64_t cs_subevent_timestamp_us(void) {
#if defined(CONFIG_NRF_GRTC_TIMER)
	/* The GRTC is the system timer on this SoC, so it ticks at the configured
	 * cycle rate. Convert to microseconds rather than assuming 1 MHz.
	 */
	BUILD_ASSERT(CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC >= 1000000 &&
	                     CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC % 1000000 == 0,
	             "GRTC tick rate must be a whole number of ticks per microsecond");
	return z_nrf_grtc_timer_read() / (CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC / 1000000U);
#else
	return k_ticks_to_us_floor64(k_uptime_ticks());
#endif
}

/* Step record at offset within the subevent, or NULL when it does not fit. */
static const struct cs_step_header *step_at(const struct cs_subevent *subevent,
                                            size_t offset) {
	const struct cs_step_header *step;

	if (offset >= subevent->size || subevent->size - offset < sizeof(*step)) {
		return NULL;
	}
	step = (const struct cs_step_header *)((const uint8_t *)subevent + offset);
	if (step->size < sizeof(*step) || step->size > subevent->size - offset) {
		return NULL;
	}
	return step;
}

const struct cs_step_header *cs_step_first(const struct cs_subevent *subevent) {
	if (subevent == NULL || subevent->num_steps == 0U) {
		return NULL;
	}
	return step_at(subevent, sizeof(*subevent));
}

const struct cs_step_header *cs_step_next(const struct cs_subevent *subevent,
                                          const struct cs_step_header *current) {
	if (subevent == NULL || current == NULL) {
		return NULL;
	}
	return step_at(subevent,
	               (size_t)((const uint8_t *)current - (const uint8_t *)subevent) + current->size);
}

const struct cs_step_tone *cs_step_tones(const struct cs_step_header *step,
                                         uint8_t *num_tones) {
	const uint8_t *body;
	const struct cs_step_tone *tones = NULL;
	uint8_t count = 0U;

	if (step == NULL) {
		goto out;
	}
	body = cs_step_body(step);

	switch ((enum cs_step_type)step->type) {
	case CS_STEP_TYPE_MODE_2: {
		const struct cs_step_mode_2 *mode_2 = (const struct cs_step_mode_2 *)body;

		tones = mode_2->tones;
		count = mode_2->num_tones;
		break;
	}
	case CS_STEP_TYPE_MODE_3: {
		const struct cs_step_mode_3 *mode_3 = (const struct cs_step_mode_3 *)body;

		tones = mode_3->tones;
		count = mode_3->num_tones;
		break;
	}
	case CS_STEP_TYPE_MODE_3_SS_RTT: {
		const struct cs_step_mode_3_ss_rtt *mode_3 = (const struct cs_step_mode_3_ss_rtt *)body;

		tones = mode_3->tones;
		count = mode_3->num_tones;
		break;
	}
	default:
		break;
	}

	/* The count is read back out of the record, so confirm it agrees with the
	 * size the record declares before handing out an array of that length.
	 */
	if (tones != NULL) {
		size_t used = (size_t)((const uint8_t *)tones - (const uint8_t *)step);

		if (step->size < used || (step->size - used) / sizeof(*tones) < count) {
			tones = NULL;
			count = 0U;
		}
	}

out:
	if (num_tones != NULL) {
		*num_tones = count;
	}
	return count != 0U ? tones : NULL;
}

/* True for the record types whose body starts with the mode 1 prefix. */
static bool type_has_rtt_prefix(enum cs_step_type type) {
	switch (type) {
	case CS_STEP_TYPE_MODE_1:
	case CS_STEP_TYPE_MODE_1_SS_RTT:
	case CS_STEP_TYPE_MODE_3:
	case CS_STEP_TYPE_MODE_3_SS_RTT:
		return true;
	default:
		return false;
	}
}

static void print_rssi(struct cs_print_buf *pb, int8_t rssi) {
	if (cs_step_rssi_valid(rssi)) {
		cs_print_append(pb, "%d dBm\n", rssi);
	} else {
		cs_print_append(pb, "unavailable\n");
	}
}

int cs_step_print(char *buf, size_t size, const struct cs_step_header *step) {
	struct cs_print_buf pb;
	enum cs_step_type type;
	const uint8_t *body;
	const struct cs_step_tone *tones;
	uint8_t num_tones;

	if (step == NULL || cs_print_init(&pb, buf, size)) {
		return -EINVAL;
	}
	type = (enum cs_step_type)step->type;
	body = cs_step_body(step);

	/* Every body starts with the channel, whatever its type. */
	cs_print_append(&pb, "CS step %u: type=%u channel=%u size=%u\n",
	                step->index, step->type, body[0], step->size);

	if (type == CS_STEP_TYPE_MODE_0_INITIATOR || type == CS_STEP_TYPE_MODE_0_REFLECTOR) {
		const struct cs_step_mode_0_reflector *mode_0 = (const struct cs_step_mode_0_reflector *)body;

		cs_print_append(&pb, "  packet: AA quality=%u bit errors=%u antenna=%u RSSI=",
		                mode_0->aa_quality,
		                mode_0->bit_errors,
		                mode_0->antenna);
		print_rssi(&pb, mode_0->rssi);
	}

	if (type == CS_STEP_TYPE_MODE_0_INITIATOR) {
		const struct cs_step_mode_0_initiator *mode_0 = (const struct cs_step_mode_0_initiator *)body;

		if (cs_step_freq_offset_valid(mode_0->measured_freq_offset)) {
			cs_print_append(&pb, "    measured frequency offset=%u (0.01 ppm)\n",
			                mode_0->measured_freq_offset);
		} else {
			cs_print_append(&pb, "    measured frequency offset=unavailable\n");
		}
	}

	if (type_has_rtt_prefix(type)) {
		const struct cs_step_mode_1 *rtt = (const struct cs_step_mode_1 *)body;

		cs_print_append(&pb, "  packet: AA quality=%u bit errors=%u antenna=%u RSSI=",
		                rtt->aa_quality,
		                rtt->bit_errors,
		                rtt->antenna);
		print_rssi(&pb, rtt->rssi);
		cs_print_append(&pb, "    NADM=%u time difference=", rtt->nadm);
		if (cs_step_time_difference_valid(rtt->time_difference)) {
			cs_print_append(&pb, "%d half-ns\n", rtt->time_difference);
		} else {
			cs_print_append(&pb, "unavailable\n");
		}
	}

	if (type == CS_STEP_TYPE_MODE_1_SS_RTT) {
		const struct cs_step_mode_1_ss_rtt *mode_1 = (const struct cs_step_mode_1_ss_rtt *)body;

		cs_print_append(&pb, "    packet PCT1: I=%d Q=%d\n", mode_1->pct1.i, mode_1->pct1.q);
		cs_print_append(&pb, "    packet PCT2: I=%d Q=%d\n", mode_1->pct2.i, mode_1->pct2.q);
	} else if (type == CS_STEP_TYPE_MODE_3_SS_RTT) {
		const struct cs_step_mode_3_ss_rtt *mode_3 = (const struct cs_step_mode_3_ss_rtt *)body;

		cs_print_append(&pb, "    packet PCT1: I=%d Q=%d\n", mode_3->pct1.i, mode_3->pct1.q);
		cs_print_append(&pb, "    packet PCT2: I=%d Q=%d\n", mode_3->pct2.i, mode_3->pct2.q);
	}

	tones = cs_step_tones(step, &num_tones);
	if (tones != NULL) {
		cs_print_append(&pb, "  tones=%u (includes extension slot)\n", num_tones);
		for (uint8_t i = 0; i < num_tones; i++) {
			cs_print_append(&pb, "    tone %u: path=%u I=%d Q=%d quality=%u extension=%u\n",
			                i,
			                tones[i].antenna_path,
			                tones[i].iq.i,
			                tones[i].iq.q,
			                tones[i].quality,
			                tones[i].extension);
		}
	}
	return cs_print_result(&pb);
}

int cs_subevent_header_print(char *buf, size_t size, const struct cs_subevent *subevent) {
	struct cs_print_buf pb;

	if (subevent == NULL || cs_print_init(&pb, buf, size)) {
		return -EINVAL;
	}

	cs_print_append(&pb, "CS subevent %u: procedure=%u event=%u config=%u role=%u rtt=%u paths=%u "
	                "steps=%u size=%u t=%llu us\n",
	                subevent->subevent_id,
	                subevent->procedure_id,
	                subevent->event_id,
	                subevent->config_id,
	                subevent->role,
	                subevent->rtt_type,
	                subevent->num_antenna_paths,
	                subevent->num_steps,
	                subevent->size,
	                (unsigned long long)subevent->timestamp_us);
	cs_print_append(&pb, "  status: procedure=%u subevent=%u abort reasons=%u/%u abort step=%u\n",
	                subevent->procedure_done_status,
	                subevent->subevent_done_status,
	                subevent->procedure_abort_reason,
	                subevent->subevent_abort_reason,
	                subevent->abort_step);
	cs_print_append(&pb, "  reference power=");
	if (cs_subevent_ref_power_level_valid(subevent->reference_power_level)) {
		cs_print_append(&pb, "%d dBm", subevent->reference_power_level);
	} else {
		cs_print_append(&pb, "unavailable");
	}
	cs_print_append(&pb, " frequency compensation=");
	if (cs_subevent_freq_compensation_valid(subevent->frequency_compensation)) {
		cs_print_append(&pb, "%u (0.01 ppm)\n", subevent->frequency_compensation);
	} else {
		cs_print_append(&pb, "unavailable\n");
	}
	return cs_print_result(&pb);
}
