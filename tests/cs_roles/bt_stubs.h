/* SPDX-License-Identifier: MIT */
/* Bluetooth, NCS RAS / GATT DM and app_log stubs of the cs_roles native tests.
 * Every command the libraries issue is logged; the tests deliver the
 * completions themselves.
 */
#ifndef TEST_CS_ROLES_BT_STUBS_H_
#define TEST_CS_ROLES_BT_STUBS_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <bluetooth/services/ras.h>
#include <zephyr/bluetooth/conn.h>

enum test_cmd {
	CMD_PARAM_UPDATE,
	CMD_DEFAULT_SETTINGS,
	CMD_REMOTE_CAPABILITIES,
	CMD_REMOTE_FAE,
	CMD_T_PM,
	CMD_CREATE_CONFIG,
	CMD_CS_SECURITY,
	CMD_PROCEDURE_PARAMETERS,
	CMD_PROCEDURE_ENABLE,
	CMD_PROCEDURE_DISABLE,
	CMD_DISCONNECT,
	CMD_GATT_DM_START,
	CMD_RREQ_FEATURES,
	CMD_RREQ_SUBSCRIBE,
	CMD_RREQ_UNSUBSCRIBE,
	CMD_RREQ_FREE,
	CMD_RRSP_ALLOC,
	CMD_RRSP_FREE,
	CMD_COUNT,
};

struct bt_conn {
	int refs;
};

/* The one connection of the tests. */
extern struct bt_conn test_conn;

/* Commands in issue order since test_cmds_clear(). */
extern enum test_cmd test_cmds[64];
extern size_t test_cmd_count;
/* Return value of the next calls of each command; 0 by default. */
extern int test_cmd_err[CMD_COUNT];
/* Arguments of the last calls. */
extern struct bt_le_cs_create_config_params test_created;
extern uint8_t test_disable_config_id;
/* cs_role_controller_t_pm_set() argument of the last call, and its HCI status. */
extern uint8_t test_t_pm_us;
extern uint8_t test_t_pm_status;
extern bt_ras_rreq_ranging_data_received_t test_ras_data_cb;
/* Antenna paths mask of the ranging header the RAS parser stub delivers. */
extern uint8_t test_ras_antenna_paths_mask;
/* bt_ras_rrsp_alloc() result when test_cmd_err is 0; -EALREADY models automatic allocation. */
extern int test_rrsp_alloc_result;
extern uint16_t test_att_mtu;

void test_cmds_clear(void);
/* Number of times @p cmd was issued. */
size_t test_cmd_calls(enum test_cmd cmd);
/* True when the log is exactly @p cmds. */
bool test_cmds_equal(const enum test_cmd *cmds, size_t count);
/* Replaces cs_role_controller.c: logs CMD_T_PM. */
uint8_t cs_role_controller_t_pm_set(uint8_t t_pm_us);

#endif /* TEST_CS_ROLES_BT_STUBS_H_ */
