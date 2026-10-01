/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <string.h>

#include <bluetooth/gatt_dm.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/net_buf.h>
#include <zephyr/sys/byteorder.h>
#include <zephyr/sys/crc.h>

#include "app_log/app_log.h"
#include "bt_stubs.h"

/* Kernel stub state (include/zephyr/kernel.h). */
int64_t test_now_ms;
k_tid_t test_current_thread;
k_timeout_t test_msgq_put_timeout;

struct bt_conn test_conn;
enum test_cmd test_cmds[64];
size_t test_cmd_count;
int test_cmd_err[CMD_COUNT];
struct bt_le_cs_create_config_params test_created;
uint8_t test_disable_config_id;
bt_ras_rreq_ranging_data_received_t test_ras_data_cb;
uint8_t test_ras_antenna_paths_mask = 0x01U;
int test_rrsp_alloc_result;
uint16_t test_att_mtu = 23U;

void test_cmds_clear(void) {
	test_cmd_count = 0U;
}

size_t test_cmd_calls(enum test_cmd cmd) {
	size_t calls = 0U;

	for (size_t i = 0; i < test_cmd_count; i++) {
		calls += test_cmds[i] == cmd;
	}
	return calls;
}

bool test_cmds_equal(const enum test_cmd *cmds, size_t count) {
	return count == test_cmd_count && memcmp(cmds, test_cmds, count * sizeof(cmds[0])) == 0;
}

static int command(enum test_cmd cmd) {
	if (test_cmd_count < ARRAY_SIZE(test_cmds)) {
		test_cmds[test_cmd_count++] = cmd;
	}
	return test_cmd_err[cmd];
}

/* app_log: nothing is formatted. */

bool app_log_enabled(uint8_t level) {
	ARG_UNUSED(level);
	return false;
}

void app_log_printf(const char *module, uint8_t level, const char *fmt, ...) {
	ARG_UNUSED(module);
	ARG_UNUSED(level);
	ARG_UNUSED(fmt);
}

/* Connections. */

struct bt_conn *bt_conn_ref(struct bt_conn *conn) {
	conn->refs++;
	return conn;
}

void bt_conn_unref(struct bt_conn *conn) {
	conn->refs--;
}

uint16_t bt_gatt_get_mtu(struct bt_conn *conn) {
	ARG_UNUSED(conn);
	return test_att_mtu;
}

uint8_t bt_conn_index(const struct bt_conn *conn) {
	ARG_UNUSED(conn);
	return 0U;
}

int bt_conn_disconnect(struct bt_conn *conn, uint8_t reason) {
	ARG_UNUSED(conn);
	ARG_UNUSED(reason);
	return command(CMD_DISCONNECT);
}

int bt_conn_le_param_update(struct bt_conn *conn, const struct bt_le_conn_param *param) {
	ARG_UNUSED(conn);
	ARG_UNUSED(param);
	return command(CMD_PARAM_UPDATE);
}

/* Channel Sounding. */

int bt_le_cs_read_local_supported_capabilities(struct bt_conn_le_cs_capabilities *ret) {
	memset(ret, 0, sizeof(*ret));
	return 0;
}

int bt_le_cs_read_local_supported_capabilities_v2(struct bt_conn_le_cs_capabilities *ret) {
	return bt_le_cs_read_local_supported_capabilities(ret);
}

int bt_le_cs_set_default_settings(struct bt_conn *conn,
                                  const struct bt_le_cs_set_default_settings_param *params) {
	ARG_UNUSED(conn);
	ARG_UNUSED(params);
	return command(CMD_DEFAULT_SETTINGS);
}

int bt_le_cs_read_remote_supported_capabilities(struct bt_conn *conn) {
	ARG_UNUSED(conn);
	return command(CMD_REMOTE_CAPABILITIES);
}

int bt_le_cs_read_remote_fae_table(struct bt_conn *conn) {
	ARG_UNUSED(conn);
	return command(CMD_REMOTE_FAE);
}

uint8_t test_t_pm_us;
uint8_t test_t_pm_status;

uint8_t cs_role_controller_t_pm_set(uint8_t t_pm_us) {
	test_t_pm_us = t_pm_us;
	(void)command(CMD_T_PM);
	return test_t_pm_status;
}

int bt_le_cs_create_config(struct bt_conn *conn, struct bt_le_cs_create_config_params *params,
                           enum bt_le_cs_create_config_context context) {
	ARG_UNUSED(conn);
	ARG_UNUSED(context);
	test_created = *params;
	return command(CMD_CREATE_CONFIG);
}

int bt_le_cs_security_enable(struct bt_conn *conn) {
	ARG_UNUSED(conn);
	return command(CMD_CS_SECURITY);
}

int bt_le_cs_set_procedure_parameters(struct bt_conn *conn,
                                      const struct bt_le_cs_set_procedure_parameters_param *params) {
	ARG_UNUSED(conn);
	ARG_UNUSED(params);
	return command(CMD_PROCEDURE_PARAMETERS);
}

int bt_le_cs_procedure_enable(struct bt_conn *conn,
                              const struct bt_le_cs_procedure_enable_param *params) {
	ARG_UNUSED(conn);
	if (params->enable == BT_CONN_LE_CS_PROCEDURES_DISABLED) {
		test_disable_config_id = params->config_id;
		return command(CMD_PROCEDURE_DISABLE);
	}
	return command(CMD_PROCEDURE_ENABLE);
}

/* As zephyr/subsys/bluetooth/host/cs.c: the step decoders need the real values. */

struct bt_le_cs_iq_sample bt_le_cs_parse_pct(const uint8_t pct[3]) {
	uint32_t pct_u32 = sys_get_le24(pct);
	uint16_t i_u16 = pct_u32 & BT_HCI_LE_CS_PCT_I_MASK;
	uint16_t q_u16 = (pct_u32 & BT_HCI_LE_CS_PCT_Q_MASK) >> 12;
	int16_t i = (i_u16 ^ BIT(11)) - BIT(11);
	int16_t q = (q_u16 ^ BIT(11)) - BIT(11);

	return (struct bt_le_cs_iq_sample){.i = i, .q = q};
}

#define A1 (0)
#define A2 (1)
#define A3 (2)
#define A4 (3)

/* Bluetooth Core Specification 6.0, Table 4.13, Antenna Path Permutation for N_AP=2.
 * The last element corresponds to extension slot
 */
static const uint8_t antenna_path_lut_n_ap_2[2][3] = {
	{A1, A2, A2},
	{A2, A1, A1},
};

/* Bluetooth Core Specification 6.0, Table 4.14, Antenna Path Permutation for N_AP=3.
 * The last element corresponds to extension slot
 */
static const uint8_t antenna_path_lut_n_ap_3[6][4] = {
	{A1, A2, A3, A3},
	{A2, A1, A3, A3},
	{A1, A3, A2, A2},
	{A3, A1, A2, A2},
	{A3, A2, A1, A1},
	{A2, A3, A1, A1},
};

/* Bluetooth Core Specification 6.0, Table 4.15, Antenna Path Permutation for N_AP=4.
 * The last element corresponds to extension slot
 */
static const uint8_t antenna_path_lut_n_ap_4[24][5] = {
	{A1, A2, A3, A4, A4},
	{A2, A1, A3, A4, A4},
	{A1, A3, A2, A4, A4},
	{A3, A1, A2, A4, A4},
	{A3, A2, A1, A4, A4},
	{A2, A3, A1, A4, A4},
	{A1, A2, A4, A3, A3},
	{A2, A1, A4, A3, A3},
	{A1, A4, A2, A3, A3},
	{A4, A1, A2, A3, A3},
	{A4, A2, A1, A3, A3},
	{A2, A4, A1, A3, A3},
	{A1, A4, A3, A2, A2},
	{A4, A1, A3, A2, A2},
	{A1, A3, A4, A2, A2},
	{A3, A1, A4, A2, A2},
	{A3, A4, A1, A2, A2},
	{A4, A3, A1, A2, A2},
	{A4, A2, A3, A1, A1},
	{A2, A4, A3, A1, A1},
	{A4, A3, A2, A1, A1},
	{A3, A4, A2, A1, A1},
	{A3, A2, A4, A1, A1},
	{A2, A3, A4, A1, A1},
};
int bt_le_cs_get_antenna_path(uint8_t n_ap,
			      uint8_t antenna_path_permutation_index,
			      uint8_t tone_index)
{
	switch (n_ap) {
	case 1:
	{
		uint8_t antenna_path_permutations = 1;
		uint8_t num_tones = n_ap + 1; /* one additional tone extension slot */

		if (antenna_path_permutation_index >= antenna_path_permutations ||
		    tone_index >= num_tones) {
			return -EINVAL;
		}
		return A1;
	}
	case 2:
	{
		if (antenna_path_permutation_index >= ARRAY_SIZE(antenna_path_lut_n_ap_2) ||
		    tone_index >= ARRAY_SIZE(antenna_path_lut_n_ap_2[0])) {
			return -EINVAL;
		}
		return antenna_path_lut_n_ap_2[antenna_path_permutation_index][tone_index];
	}
	case 3:
	{
		if (antenna_path_permutation_index >= ARRAY_SIZE(antenna_path_lut_n_ap_3) ||
		    tone_index >= ARRAY_SIZE(antenna_path_lut_n_ap_3[0])) {
			return -EINVAL;
		}
		return antenna_path_lut_n_ap_3[antenna_path_permutation_index][tone_index];
	}
	case 4:
	{
		if (antenna_path_permutation_index >= ARRAY_SIZE(antenna_path_lut_n_ap_4) ||
		    tone_index >= ARRAY_SIZE(antenna_path_lut_n_ap_4[0])) {
			return -EINVAL;
		}
		return antenna_path_lut_n_ap_4[antenna_path_permutation_index][tone_index];
	}
	default:
		return -EINVAL;
	}
}

/* NCS GATT discovery manager and RAS. */

struct bt_conn *bt_gatt_dm_conn_get(struct bt_gatt_dm *dm) {
	ARG_UNUSED(dm);
	return &test_conn;
}

int bt_gatt_dm_data_release(struct bt_gatt_dm *dm) {
	ARG_UNUSED(dm);
	return 0;
}

int bt_gatt_dm_start(struct bt_conn *conn, const struct bt_uuid *svc_uuid,
                     const struct bt_gatt_dm_cb *cb, void *context) {
	ARG_UNUSED(conn);
	ARG_UNUSED(svc_uuid);
	ARG_UNUSED(cb);
	ARG_UNUSED(context);
	return command(CMD_GATT_DM_START);
}

int bt_ras_rreq_alloc_and_assign_handles(struct bt_gatt_dm *dm, struct bt_conn *conn) {
	ARG_UNUSED(dm);
	ARG_UNUSED(conn);
	return 0;
}

void bt_ras_rreq_free(struct bt_conn *conn) {
	ARG_UNUSED(conn);
	(void)command(CMD_RREQ_FREE);
}

int bt_ras_rreq_read_features(struct bt_conn *conn, bt_ras_rreq_features_read_cb_t cb) {
	ARG_UNUSED(conn);
	ARG_UNUSED(cb);
	return command(CMD_RREQ_FEATURES);
}

int bt_ras_rreq_realtime_rd_subscribe(struct bt_conn *conn, struct net_buf_simple *ranging_data_out,
                                      bt_ras_rreq_ranging_data_received_t data_received_cb) {
	ARG_UNUSED(conn);
	ARG_UNUSED(ranging_data_out);
	test_ras_data_cb = data_received_cb;
	return command(CMD_RREQ_SUBSCRIBE);
}

int bt_ras_rreq_realtime_rd_unsubscribe(struct bt_conn *conn) {
	ARG_UNUSED(conn);
	return command(CMD_RREQ_UNSUBSCRIBE);
}

/* One subevent without steps: enough for a procedure to be streamed. */
void bt_ras_rreq_rd_subevent_data_parse(struct net_buf_simple *peer_ranging_data_buf,
                                        struct net_buf_simple *local_step_data_buf,
                                        enum bt_conn_le_cs_role cs_role,
                                        bt_ras_rreq_ranging_header_cb_t ranging_header_cb,
                                        bt_ras_rreq_subevent_header_cb_t subevent_header_cb,
                                        bt_ras_rreq_step_data_cb_t step_data_cb, void *user_data) {
	struct ras_ranging_header ranging = {.antenna_paths_mask = test_ras_antenna_paths_mask};
	struct ras_subevent_header subevent = {0};

	ARG_UNUSED(local_step_data_buf);
	ARG_UNUSED(cs_role);
	ARG_UNUSED(step_data_cb);
	peer_ranging_data_buf->len = 0U;
	if (ranging_header_cb(&ranging, user_data)) {
		(void)subevent_header_cb(&subevent, user_data);
	}
}

int bt_ras_rrsp_alloc(struct bt_conn *conn) {
	int err;

	ARG_UNUSED(conn);
	err = command(CMD_RRSP_ALLOC);
	return err ? err : test_rrsp_alloc_result;
}

void bt_ras_rrsp_free(struct bt_conn *conn) {
	ARG_UNUSED(conn);
	(void)command(CMD_RRSP_FREE);
}

void *net_buf_simple_add_mem(struct net_buf_simple *buf, const void *mem, size_t len) {
	void *tail = buf->data + buf->len;

	memcpy(tail, mem, len);
	buf->len += len;
	return tail;
}

/* CRC-32/IEEE as zephyr/subsys/crc/crc32_sw.c, which does not build with Apple clang
 * (__weak is an Objective-C keyword there).
 */
uint32_t crc32_ieee_update(uint32_t crc, const uint8_t *data, size_t len) {
	crc = ~crc;
	for (size_t i = 0; i < len; i++) {
		crc ^= data[i];
		for (int bit = 0; bit < 8; bit++) {
			crc = (crc >> 1) ^ (0xEDB88320U & (0U - (crc & 1U)));
		}
	}
	return ~crc;
}

uint32_t crc32_ieee(const uint8_t *data, size_t len) {
	return crc32_ieee_update(0U, data, len);
}
