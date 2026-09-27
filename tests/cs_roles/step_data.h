/* SPDX-License-Identifier: MIT */
/* HCI subevent results for the subevent tests: steps of every mode with
 * deterministic contents, in the layout cs_utils decodes (Core 6.0, Vol 4,
 * Part E, 7.7.65.44).
 */
#ifndef TEST_CS_ROLES_STEP_DATA_H_
#define TEST_CS_ROLES_STEP_DATA_H_

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include <zephyr/bluetooth/conn.h>
#include <zephyr/net_buf.h>

#define TEST_STEP_DATA_SIZE 4096U
/* Bytes of one tone entry: PCT (3) and quality (1). */
#define TEST_TONE_SIZE 4U

struct test_subevent {
	struct bt_conn_le_cs_subevent_result result;
	struct net_buf_simple buf;
	uint8_t data[TEST_STEP_DATA_SIZE];
	uint32_t seed;
};

static inline bool test_sounding(enum bt_conn_le_cs_rtt_type rtt_type) {
	return rtt_type == BT_CONN_LE_CS_RTT_TYPE_32_BIT_SOUNDING ||
	       rtt_type == BT_CONN_LE_CS_RTT_TYPE_96_BIT_SOUNDING;
}

/* Antenna path permutations for @p paths antenna paths (Core 6.0, Vol 6, Part H, 4.7.5). */
static inline uint8_t test_permutations(uint8_t paths) {
	static const uint8_t count[] = {0, 1, 2, 6, 24};

	return count[paths];
}

static inline void test_subevent_init(struct test_subevent *se, uint8_t paths,
                                      uint16_t procedure_counter, uint32_t seed) {
	memset(se, 0, sizeof(*se));
	se->buf = (struct net_buf_simple){.data = se->data, .size = sizeof(se->data), .__buf = se->data};
	se->seed = seed;
	se->result = (struct bt_conn_le_cs_subevent_result){
		.header = {
			.config_id = 1,
			.start_acl_conn_event = (uint16_t)(0x1234 + seed),
			.procedure_counter = procedure_counter,
			.frequency_compensation = (uint16_t)(0x0100 + seed),
			.reference_power_level = -12,
			.procedure_done_status = BT_CONN_LE_CS_PROCEDURE_COMPLETE,
			.subevent_done_status = BT_CONN_LE_CS_SUBEVENT_COMPLETE,
			.procedure_abort_reason = BT_CONN_LE_CS_PROCEDURE_NOT_ABORTED,
			.subevent_abort_reason = BT_CONN_LE_CS_SUBEVENT_NOT_ABORTED,
			.num_antenna_paths = paths,
			.abort_step = 0xFF,
		},
		.step_data_buf = &se->buf,
	};
}

static inline uint8_t test_next_byte(struct test_subevent *se) {
	se->seed = se->seed * 1103515245U + 12345U;
	return (uint8_t)(se->seed >> 16);
}

/* HCI payload length of a step of @p mode. */
static inline uint8_t test_step_len(uint8_t mode, enum bt_conn_le_cs_role role,
                                    enum bt_conn_le_cs_rtt_type rtt_type, uint8_t paths) {
	uint8_t tones = (uint8_t)((paths + 1U) * TEST_TONE_SIZE);

	switch (mode) {
	case 0:
		return role == BT_CONN_LE_CS_ROLE_INITIATOR ? 5U : 3U;
	case 1:
		return test_sounding(rtt_type) ? 14U : 6U;
	case 2:
		return (uint8_t)(1U + tones);
	default:
		return (uint8_t)((test_sounding(rtt_type) ? 15U : 7U) + tones);
	}
}

/* Append one step of @p mode; @p len overrides the payload length when nonzero. */
static inline void test_add_step(struct test_subevent *se, uint8_t mode,
                                 enum bt_conn_le_cs_role role, enum bt_conn_le_cs_rtt_type rtt_type,
                                 uint8_t len) {
	uint8_t paths = se->result.header.num_antenna_paths;
	uint8_t hci_len = test_step_len(mode, role, rtt_type, paths);
	uint8_t *entry = se->data + se->buf.len;

	if (!len) {
		len = hci_len;
	}
	assert(se->buf.len + 3U + len <= sizeof(se->data));
	entry[0] = mode;
	entry[1] = (uint8_t)(2U + test_next_byte(se) % 75U);
	entry[2] = len;
	for (uint8_t i = 0; i < len; i++) {
		entry[3 + i] = test_next_byte(se);
	}
	if ((mode == 2U || mode == 3U) && len == hci_len) {
		/* The permutation index comes right before the tones. */
		uint8_t offset = (uint8_t)(hci_len - (paths + 1U) * TEST_TONE_SIZE - 1U);

		entry[3 + offset] = (uint8_t)(test_next_byte(se) % test_permutations(paths));
	}
	se->buf.len += 3U + len;
	se->result.header.num_steps_reported++;
}

#endif /* TEST_CS_ROLES_STEP_DATA_H_ */
