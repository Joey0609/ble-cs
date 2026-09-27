/* SPDX-License-Identifier: MIT */
/* cs_config.c: reflector data setting of the initiator record. */
#undef NDEBUG
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>

#include <cs_utils/cs_config.h>

/* Bluetooth stubs: only the creation parameters are recorded. */
static struct bt_le_cs_create_config_params created;
static unsigned int create_calls;

int bt_conn_le_param_update(struct bt_conn *conn, const struct bt_le_conn_param *param) {
	(void)conn;
	(void)param;
	return 0;
}

int bt_le_cs_set_default_settings(struct bt_conn *conn,
                                  const struct bt_le_cs_set_default_settings_param *params) {
	(void)conn;
	(void)params;
	return 0;
}

int bt_le_cs_set_procedure_parameters(struct bt_conn *conn,
                                      const struct bt_le_cs_set_procedure_parameters_param *params) {
	(void)conn;
	(void)params;
	return 0;
}

int bt_le_cs_create_config(struct bt_conn *conn, struct bt_le_cs_create_config_params *params,
                           enum bt_le_cs_create_config_context context) {
	(void)conn;
	(void)context;
	created = *params;
	create_calls++;
	return 0;
}

static void test_default_and_layout(void) {
	struct cs_initiator_config config;

	memset(&config, 0xa5, sizeof(config));
	assert(cs_initiator_config_get_default(&config) == 0);
	assert(config.peer_data == CS_CONFIG_PEER_DATA_RAS_REALTIME);
	/* The field took the place of the reserved byte: records written before
	 * it existed keep their size and read as RAS real-time.
	 */
	assert(offsetof(struct cs_initiator_config, peer_data) == 3U);
	assert(cs_initiator_config_check_peer_data(&config) == 0);
	/* T_PM follows the creation fields. */
	assert(config.t_pm_us == CS_CONFIG_T_PM_10_US);
	assert(sizeof(config) == 60U);
	assert(offsetof(struct cs_initiator_config, t_pm_us) == 59U);
}

static void test_setter(void) {
	struct cs_initiator_config config;

	assert(cs_initiator_config_get_default(&config) == 0);
	assert(cs_initiator_config_set_peer_data(NULL, CS_CONFIG_PEER_DATA_NONE) == -EINVAL);
	assert(cs_initiator_config_set_peer_data(&config, 2U) == -EINVAL);
	assert(cs_initiator_config_set_peer_data(&config, 0xffU) == -EINVAL);
	assert(config.peer_data == CS_CONFIG_PEER_DATA_RAS_REALTIME);

	/* The setter does not require IPT: the creation can still change. */
	assert(cs_initiator_config_set_peer_data(&config, CS_CONFIG_PEER_DATA_NONE) == 0);
	assert(config.peer_data == CS_CONFIG_PEER_DATA_NONE);
	assert(cs_initiator_config_set_peer_data(&config, CS_CONFIG_PEER_DATA_RAS_REALTIME) == 0);
	assert(config.peer_data == CS_CONFIG_PEER_DATA_RAS_REALTIME);
}

static void test_t_pm_setter(void) {
	struct cs_initiator_config config;

	assert(cs_initiator_config_get_default(&config) == 0);
	assert(cs_initiator_config_set_t_pm(NULL, CS_CONFIG_T_PM_40_US) == -EINVAL);
	assert(cs_initiator_config_set_t_pm(&config, 0U) == -EINVAL);
	assert(cs_initiator_config_set_t_pm(&config, 30U) == -EINVAL);
	assert(cs_initiator_config_set_t_pm(&config, 80U) == -EINVAL);
	assert(config.t_pm_us == CS_CONFIG_T_PM_10_US);
	assert(cs_initiator_config_set_t_pm(&config, CS_CONFIG_T_PM_20_US) == 0);
	assert(config.t_pm_us == CS_CONFIG_T_PM_20_US);
	assert(cs_initiator_config_set_t_pm(&config, CS_CONFIG_T_PM_40_US) == 0);
	assert(config.t_pm_us == CS_CONFIG_T_PM_40_US);
	assert(cs_initiator_config_set_t_pm(&config, CS_CONFIG_T_PM_10_US) == 0);
	assert(config.t_pm_us == CS_CONFIG_T_PM_10_US);
}

static void test_procedure_antennas(void) {
	struct cs_initiator_config initiator;
	struct cs_reflector_config reflector;
	struct cs_config_procedure procedure;

	assert(cs_initiator_config_get_default(&initiator) == 0);
	assert(cs_reflector_config_get_default(&reflector) == 0);
	procedure = initiator.procedure;

	/* A1:B2: the initiator names two reflector antennas, the reflector one initiator antenna. */
	procedure.tone_antenna_config_selection = CS_CONFIG_TONE_ANTENNA_A1_B2;
	procedure.preferred_peer_antenna = CS_CONFIG_PEER_ANTENNA_3;
	assert(cs_initiator_config_set_procedure(&initiator, &procedure) == -EINVAL);
	assert(initiator.procedure.preferred_peer_antenna == CS_CONFIG_PEER_ANTENNA_1);
	assert(cs_reflector_config_set_procedure(&reflector, &procedure) == 0);
	procedure.preferred_peer_antenna = CS_CONFIG_PEER_ANTENNA_1 | CS_CONFIG_PEER_ANTENNA_2;
	assert(cs_initiator_config_set_procedure(&initiator, &procedure) == 0);
	assert(initiator.procedure.preferred_peer_antenna == procedure.preferred_peer_antenna);

	/* A2:B1 the other way round. */
	procedure.tone_antenna_config_selection = CS_CONFIG_TONE_ANTENNA_A2_B1;
	procedure.preferred_peer_antenna = CS_CONFIG_PEER_ANTENNA_4;
	assert(cs_initiator_config_set_procedure(&initiator, &procedure) == 0);
	assert(cs_reflector_config_set_procedure(&reflector, &procedure) == -EINVAL);

	/* No antenna, bits above antenna 4, and an undefined configuration. */
	procedure.tone_antenna_config_selection = CS_CONFIG_TONE_ANTENNA_A1_B1;
	procedure.preferred_peer_antenna = 0U;
	assert(cs_initiator_config_set_procedure(&initiator, &procedure) == -EINVAL);
	assert(cs_reflector_config_set_procedure(&reflector, &procedure) == -EINVAL);
	procedure.preferred_peer_antenna = CS_CONFIG_PEER_ANTENNA_1 | 0x10U;
	assert(cs_initiator_config_set_procedure(&initiator, &procedure) == -EINVAL);
	procedure.preferred_peer_antenna = CS_CONFIG_PEER_ANTENNA_1;
	procedure.tone_antenna_config_selection = CS_CONFIG_TONE_ANTENNA_A2_B2 + 1U;
	assert(cs_initiator_config_set_procedure(&initiator, &procedure) == -EINVAL);
}

static void test_check(void) {
	struct cs_initiator_config config;
	struct cs_config_creation creation;

	assert(cs_initiator_config_check_peer_data(NULL) == -EINVAL);
	assert(cs_initiator_config_get_default(&config) == 0);

	/* None needs the IPT request. */
	assert(cs_initiator_config_set_peer_data(&config, CS_CONFIG_PEER_DATA_NONE) == 0);
	assert(cs_initiator_config_check_peer_data(&config) == -EINVAL);
	assert(cs_initiator_config_enable_ipt(&config) == 0);
	assert(cs_initiator_config_check_peer_data(&config) == 0);

	/* Clearing IPT afterwards makes the record invalid again. */
	assert(cs_initiator_config_disable_ipt(&config) == 0);
	assert(cs_initiator_config_check_peer_data(&config) == -EINVAL);
	assert(cs_initiator_config_enable_ipt(&config) == 0);
	creation = config.creation;
	creation.cs_enhancements_1 = 0U;
	assert(cs_initiator_config_set_creation(&config, &creation) == 0);
	assert(cs_initiator_config_check_peer_data(&config) == -EINVAL);

	/* RAS works with and without IPT. */
	assert(cs_initiator_config_set_peer_data(&config, CS_CONFIG_PEER_DATA_RAS_REALTIME) == 0);
	assert(cs_initiator_config_check_peer_data(&config) == 0);
	assert(cs_initiator_config_enable_ipt(&config) == 0);
	assert(cs_initiator_config_check_peer_data(&config) == 0);

	/* A direct field write bypasses the setter, not the check. */
	config.peer_data = 2U;
	assert(cs_initiator_config_check_peer_data(&config) == -EINVAL);
}

static void test_apply_keeps_ipt(void) {
	struct cs_initiator_config config;
	struct bt_conn *conn = (struct bt_conn *)&config;

	create_calls = 0U;
	assert(cs_initiator_config_get_default(&config) == 0);
	assert(cs_initiator_config_enable_ipt(&config) == 0);
	assert(cs_initiator_config_set_peer_data(&config, CS_CONFIG_PEER_DATA_NONE) == 0);
	assert(cs_initiator_config_apply_creation(&config, conn) == 0);
	assert(create_calls == 1U);
	assert(created.cs_enhancements_1 == CS_CONFIG_ENHANCEMENTS_1_IPT);
	assert(created.role == BT_CONN_LE_CS_ROLE_INITIATOR);
}

static void test_apply_rejects_invalid_t_pm(void) {
	struct cs_initiator_config config;
	struct bt_conn *conn = (struct bt_conn *)&config;

	assert(cs_initiator_config_get_default(&config) == 0);
	config.t_pm_us = 30U;
	assert(cs_initiator_config_apply_creation(&config, conn) == -EINVAL);
}

static void test_print(void) {
	struct cs_initiator_config config;
	char buf[CS_INITIATOR_CONFIG_PRINT_SIZE];

	assert(cs_initiator_config_get_default(&config) == 0);
	assert(cs_initiator_config_print(buf, sizeof(buf), &config) > 0);
	assert(strstr(buf, "  reflector data: RAS real-time (0)\n") != NULL);
	assert(strstr(buf, "  preferred T_PM: 10 us\n") != NULL);

	assert(cs_initiator_config_enable_ipt(&config) == 0);
	assert(cs_initiator_config_set_peer_data(&config, CS_CONFIG_PEER_DATA_NONE) == 0);
	assert(cs_initiator_config_print(buf, sizeof(buf), &config) > 0);
	assert(strstr(buf, "  reflector data: none (initiator only) (1)\n") != NULL);

	/* The longest output still fits: all 72 usable channels, wide values. */
	static const uint8_t all_channels[CS_CONFIG_CHANNEL_MAP_SIZE] = {
		0xfc, 0xff, 0x7f, 0xfc, 0xff, 0xff, 0xff, 0xff, 0xff, 0x1f,
	};
	assert(cs_initiator_config_set_channel_map(&config, all_channels) == 0);
	config.peer_data = 0xffU;
	config.t_pm_us = UINT8_MAX;
	config.procedure.max_procedure_count = UINT16_MAX;
	config.procedure.min_subevent_len = UINT32_MAX;
	config.procedure.max_subevent_len = UINT32_MAX;
	config.procedure.tx_power_delta = -127;
	int len = cs_initiator_config_print(buf, sizeof(buf), &config);

	assert(len > 0 && (size_t)len < sizeof(buf));
	assert(strstr(buf, "  reflector data: unknown (255)\n") != NULL);
}

int main(void) {
	test_default_and_layout();
	test_setter();
	test_t_pm_setter();
	test_procedure_antennas();
	test_check();
	test_apply_keeps_ipt();
	test_apply_rejects_invalid_t_pm();
	test_print();
	printf("cs_utils config tests passed\n");
	return 0;
}
