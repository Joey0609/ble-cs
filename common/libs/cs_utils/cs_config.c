/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <stddef.h>
#include <string.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/bluetooth/hci.h>

#include "cs_config.h"
#include "cs_print_internal.h"

/* Records are stored and transmitted as raw bytes; the header offsets a reader
 * relies on are part of the contract.
 */
BUILD_ASSERT(offsetof(struct cs_reflector_config, role) == 0U);
BUILD_ASSERT(offsetof(struct cs_reflector_config, size) == 1U);
BUILD_ASSERT(offsetof(struct cs_initiator_config, role) == 0U);
BUILD_ASSERT(offsetof(struct cs_initiator_config, size) == 1U);

/* Stored encodings are cast to Zephyr enums when applied, so they must match.
 * Compare as int: the two sides are distinct enum types.
 */
#define ENCODING_MATCHES(ours, zephyr) BUILD_ASSERT((int)(ours) == (int)(zephyr))

BUILD_ASSERT(CS_FAE_TABLE_ENTRIES ==
             sizeof(((struct bt_hci_evt_le_cs_read_remote_fae_table_complete *)0)->remote_fae_table));

ENCODING_MATCHES(CS_CONFIG_ROLE_INITIATOR, BT_CONN_LE_CS_ROLE_INITIATOR);
ENCODING_MATCHES(CS_CONFIG_ROLE_REFLECTOR, BT_CONN_LE_CS_ROLE_REFLECTOR);
ENCODING_MATCHES(CS_CONFIG_MAX_TX_POWER_MAX, BT_HCI_OP_LE_CS_MAX_MAX_TX_POWER);
ENCODING_MATCHES(CS_CONFIG_MAX_TX_POWER_MIN, BT_HCI_OP_LE_CS_MIN_MAX_TX_POWER);
ENCODING_MATCHES(CS_CONFIG_SYNC_ANTENNA_ONE, BT_LE_CS_ANTENNA_SELECTION_OPT_ONE);
ENCODING_MATCHES(CS_CONFIG_SYNC_ANTENNA_FOUR, BT_LE_CS_ANTENNA_SELECTION_OPT_FOUR);
ENCODING_MATCHES(CS_CONFIG_SYNC_ANTENNA_REPETITIVE, BT_LE_CS_ANTENNA_SELECTION_OPT_REPETITIVE);
ENCODING_MATCHES(CS_CONFIG_SYNC_ANTENNA_NO_RECOMMENDATION, BT_LE_CS_ANTENNA_SELECTION_OPT_NO_RECOMMENDATION);
ENCODING_MATCHES(CS_CONFIG_TONE_ANTENNA_A1_B1, BT_LE_CS_TONE_ANTENNA_CONFIGURATION_A1_B1);
ENCODING_MATCHES(CS_CONFIG_TONE_ANTENNA_A2_B2, BT_LE_CS_TONE_ANTENNA_CONFIGURATION_A2_B2);
ENCODING_MATCHES(CS_CONFIG_PROCEDURE_PHY_1M, BT_LE_CS_PROCEDURE_PHY_1M);
ENCODING_MATCHES(CS_CONFIG_PROCEDURE_PHY_CODED_S2, BT_LE_CS_PROCEDURE_PHY_CODED_S2);
ENCODING_MATCHES(CS_CONFIG_PEER_ANTENNA_1, BT_LE_CS_PROCEDURE_PREFERRED_PEER_ANTENNA_1);
ENCODING_MATCHES(CS_CONFIG_PEER_ANTENNA_4, BT_LE_CS_PROCEDURE_PREFERRED_PEER_ANTENNA_4);
ENCODING_MATCHES(CS_CONFIG_SNR_CONTROL_18DB, BT_LE_CS_SNR_CONTROL_18dB);
ENCODING_MATCHES(CS_CONFIG_SNR_CONTROL_30DB, BT_LE_CS_SNR_CONTROL_30dB);
ENCODING_MATCHES(CS_CONFIG_SNR_CONTROL_NOT_USED, BT_LE_CS_SNR_CONTROL_NOT_USED);
ENCODING_MATCHES(CS_CONFIG_MODE_1, BT_CONN_LE_CS_MAIN_MODE_1_NO_SUB_MODE);
ENCODING_MATCHES(CS_CONFIG_MODE_2, BT_CONN_LE_CS_MAIN_MODE_2_NO_SUB_MODE);
ENCODING_MATCHES(CS_CONFIG_MODE_3, BT_CONN_LE_CS_MAIN_MODE_3_NO_SUB_MODE);
ENCODING_MATCHES(CS_CONFIG_MODE_2_SUB_MODE_1, BT_CONN_LE_CS_MAIN_MODE_2_SUB_MODE_1);
ENCODING_MATCHES(CS_CONFIG_MODE_2_SUB_MODE_3, BT_CONN_LE_CS_MAIN_MODE_2_SUB_MODE_3);
ENCODING_MATCHES(CS_CONFIG_MODE_3_SUB_MODE_2, BT_CONN_LE_CS_MAIN_MODE_3_SUB_MODE_2);
ENCODING_MATCHES(CS_CONFIG_RTT_TYPE_AA_ONLY, BT_CONN_LE_CS_RTT_TYPE_AA_ONLY);
ENCODING_MATCHES(CS_CONFIG_RTT_TYPE_128_BIT_RANDOM, BT_CONN_LE_CS_RTT_TYPE_128_BIT_RANDOM);
ENCODING_MATCHES(CS_CONFIG_SYNC_PHY_1M, BT_CONN_LE_CS_SYNC_1M_PHY);
ENCODING_MATCHES(CS_CONFIG_SYNC_PHY_2M_2BT, BT_CONN_LE_CS_SYNC_2M_2BT_PHY);
ENCODING_MATCHES(CS_CONFIG_CHSEL_TYPE_3B, BT_CONN_LE_CS_CHSEL_TYPE_3B);
ENCODING_MATCHES(CS_CONFIG_CHSEL_TYPE_3C, BT_CONN_LE_CS_CHSEL_TYPE_3C);
ENCODING_MATCHES(CS_CONFIG_CH3C_SHAPE_HAT, BT_CONN_LE_CS_CH3C_SHAPE_HAT);
ENCODING_MATCHES(CS_CONFIG_CH3C_SHAPE_X, BT_CONN_LE_CS_CH3C_SHAPE_X);
ENCODING_MATCHES(CS_CONFIG_CREATION_CONTEXT_LOCAL_ONLY, BT_LE_CS_CREATE_CONFIG_CONTEXT_LOCAL_ONLY);
ENCODING_MATCHES(CS_CONFIG_CREATION_CONTEXT_LOCAL_AND_REMOTE, BT_LE_CS_CREATE_CONFIG_CONTEXT_LOCAL_AND_REMOTE);
BUILD_ASSERT(CS_CONFIG_CHANNEL_MAP_SIZE == sizeof(((struct bt_le_cs_create_config_params *)0)->channel_map));

/* Immutable defaults shared internally; every public record owns its copy. */
static const struct cs_config_connection default_connection = {
	.interval_min = 6,
	.interval_max = 6,
	.latency = 0,
	.timeout = 400,
};

static const struct cs_config_default_settings default_settings = {
	.cs_sync_antenna_selection = CS_CONFIG_SYNC_ANTENNA_REPETITIVE,
	.max_tx_power = CS_CONFIG_MAX_TX_POWER_MAX,
};

static const struct cs_config_procedure default_procedure = {
	.max_procedure_len = 10,
	.min_procedure_interval = 1,
	.max_procedure_interval = 4,
	.max_procedure_count = 0,
	.min_subevent_len = 6000,
	.max_subevent_len = 6000,
	.tone_antenna_config_selection = CS_CONFIG_TONE_ANTENNA_A1_B1,
	.phy = CS_CONFIG_PROCEDURE_PHY_1M,
	.tx_power_delta = CS_CONFIG_TX_POWER_DELTA_NONE,
	.preferred_peer_antenna = CS_CONFIG_PEER_ANTENNA_1,
	.snr_control_initiator = CS_CONFIG_SNR_CONTROL_NOT_USED,
	.snr_control_reflector = CS_CONFIG_SNR_CONTROL_NOT_USED,
};

static bool connection_valid(const struct cs_config_connection *connection) {
	return connection && connection->interval_min >= 6 && connection->interval_max <= 3200 &&
	       connection->interval_min <= connection->interval_max && connection->latency <= 499 &&
	       connection->timeout >= 10 && connection->timeout <= 3200 &&
	       (uint32_t)connection->timeout * 4 > (uint32_t)connection->interval_max * (connection->latency + 1);
}

static bool default_settings_valid(const struct cs_config_default_settings *settings) {
	return settings && settings->max_tx_power >= CS_CONFIG_MAX_TX_POWER_MIN &&
	       settings->max_tx_power <= CS_CONFIG_MAX_TX_POWER_MAX;
}

static bool channel_map_valid(const uint8_t channel_map[CS_CONFIG_CHANNEL_MAP_SIZE]) {
	if (!channel_map || (channel_map[0] & 0x03) || (channel_map[2] & 0x80) || (channel_map[3] & 0x03) ||
	    (channel_map[9] & 0xe0)) {
		return false;
	}
	unsigned int count = 0;
	for (unsigned int channel = 0; channel < 80; channel++) {
		count += (channel_map[channel / 8] >> (channel % 8)) & 1U;
	}
	return count >= 15;
}

/* Preferred_Peer_Antenna names peer antennas 1-4 and must set at least as many
 * bits as the peer uses in the tone antenna configuration: B for an initiator,
 * A for a reflector. Whether those antennas exist is known only after
 * connecting (cs_roles checks it at remote capabilities).
 */
static bool procedure_valid(const struct cs_config_procedure *procedure, bool initiator) {
	/* (initiator, reflector) antennas per tone antenna configuration index. */
	static const uint8_t tone_antennas[][2] = {
		{1, 1}, {2, 1}, {3, 1}, {4, 1}, {1, 2}, {1, 3}, {1, 4}, {2, 2},
	};
	uint8_t mask = procedure->preferred_peer_antenna;
	unsigned int bits = 0;

	if (procedure->tone_antenna_config_selection >= ARRAY_SIZE(tone_antennas) || mask == 0U ||
	    (mask & ~0x0FU) != 0U) {
		return false;
	}
	for (; mask; mask >>= 1) {
		bits += mask & 1U;
	}
	return bits >= tone_antennas[procedure->tone_antenna_config_selection][initiator ? 1 : 0];
}

static bool creation_context_valid(uint8_t context) {
	return context == CS_CONFIG_CREATION_CONTEXT_LOCAL_ONLY ||
	       context == CS_CONFIG_CREATION_CONTEXT_LOCAL_AND_REMOTE;
}

static bool peer_data_valid(uint8_t peer_data) {
	return peer_data == CS_CONFIG_PEER_DATA_RAS_REALTIME || peer_data == CS_CONFIG_PEER_DATA_NONE;
}

static bool t_pm_valid(uint8_t t_pm_us) {
	return t_pm_us == CS_CONFIG_T_PM_10_US || t_pm_us == CS_CONFIG_T_PM_20_US ||
	       t_pm_us == CS_CONFIG_T_PM_40_US;
}

int cs_reflector_config_get_default(struct cs_reflector_config *config) {
	if (!config) {
		return -EINVAL;
	}
	*config = (struct cs_reflector_config){
		.role = CS_CONFIG_ROLE_REFLECTOR,
		.size = sizeof(struct cs_reflector_config),
		.config_id = 0,
		.connection = default_connection,
		.defaults = default_settings,
		.procedure = default_procedure,
	};
	return 0;
}

int cs_reflector_config_set_connection(struct cs_reflector_config *config,
                                       const struct cs_config_connection *connection) {
	if (!config || !connection_valid(connection)) {
		return -EINVAL;
	}
	config->connection = *connection;
	return 0;
}

int cs_reflector_config_set_default_settings(struct cs_reflector_config *config,
                                             const struct cs_config_default_settings *settings) {
	if (!config || !default_settings_valid(settings)) {
		return -EINVAL;
	}
	config->defaults = *settings;
	return 0;
}

int cs_reflector_config_set_procedure(struct cs_reflector_config *config,
                                      const struct cs_config_procedure *procedure) {
	if (!config || !procedure || !procedure_valid(procedure, false)) {
		return -EINVAL;
	}
	config->procedure = *procedure;
	return 0;
}

int cs_reflector_config_set_config_id(struct cs_reflector_config *config,
                                      uint8_t id) {
	if (!config || id > CS_CONFIG_ID_MAX) {
		return -EINVAL;
	}
	config->config_id = id;
	return 0;
}

int cs_initiator_config_get_default(struct cs_initiator_config *config) {
	if (!config) {
		return -EINVAL;
	}
	*config = (struct cs_initiator_config){
		.role = CS_CONFIG_ROLE_INITIATOR,
		.size = sizeof(struct cs_initiator_config),
		.config_id = 0,
		.peer_data = CS_CONFIG_PEER_DATA_RAS_REALTIME,
		.t_pm_us = CS_CONFIG_T_PM_10_US,
		.connection = default_connection,
		.defaults = default_settings,
		.procedure = default_procedure,
		.creation = {
			.mode = CS_CONFIG_MODE_2_SUB_MODE_1,
			.min_main_mode_steps = 2,
			.max_main_mode_steps = 10,
			.main_mode_repetition = 0,
			.mode_0_steps = 1,
			.rtt_type = CS_CONFIG_RTT_TYPE_AA_ONLY,
			.cs_sync_phy = CS_CONFIG_SYNC_PHY_1M,
			.channel_map_repetition = 1,
			.channel_selection_type = CS_CONFIG_CHSEL_TYPE_3B,
			.ch3c_shape = CS_CONFIG_CH3C_SHAPE_HAT,
			.ch3c_jump = 2,
			.context = CS_CONFIG_CREATION_CONTEXT_LOCAL_AND_REMOTE,
		},
	};
	/* Match the checked-in connected initiator example: 36 CS channels. */
	for (uint8_t channel = 26; channel < 62; channel++) {
		config->creation.channel_map[channel / 8] |= (uint8_t)(1U << (channel % 8));
	}
	return 0;
}

int cs_initiator_config_set_connection(struct cs_initiator_config *config,
                                       const struct cs_config_connection *connection) {
	if (!config || !connection_valid(connection)) {
		return -EINVAL;
	}
	config->connection = *connection;
	return 0;
}

int cs_initiator_config_set_default_settings(struct cs_initiator_config *config,
                                             const struct cs_config_default_settings *settings) {
	if (!config || !default_settings_valid(settings)) {
		return -EINVAL;
	}
	config->defaults = *settings;
	return 0;
}

int cs_initiator_config_set_procedure(struct cs_initiator_config *config,
                                      const struct cs_config_procedure *procedure) {
	if (!config || !procedure || !procedure_valid(procedure, true)) {
		return -EINVAL;
	}
	config->procedure = *procedure;
	return 0;
}

int cs_initiator_config_set_config_id(struct cs_initiator_config *config,
                                      uint8_t id) {
	if (!config || id > CS_CONFIG_ID_MAX) {
		return -EINVAL;
	}
	config->config_id = id;
	return 0;
}

int cs_initiator_config_set_creation(struct cs_initiator_config *config,
                                     const struct cs_config_creation *creation) {
	if (!config || !creation || !channel_map_valid(creation->channel_map) ||
	    !creation_context_valid(creation->context)) {
		return -EINVAL;
	}
	config->creation = *creation;
	return 0;
}

int cs_initiator_config_enable_ipt(struct cs_initiator_config *config) {
	if (!config) {
		return -EINVAL;
	}
	config->creation.cs_enhancements_1 |= CS_CONFIG_ENHANCEMENTS_1_IPT;
	return 0;
}

int cs_initiator_config_disable_ipt(struct cs_initiator_config *config) {
	if (!config) {
		return -EINVAL;
	}
	config->creation.cs_enhancements_1 &= (uint8_t)~CS_CONFIG_ENHANCEMENTS_1_IPT;
	return 0;
}

int cs_initiator_config_set_channel_map(struct cs_initiator_config *config,
                                        const uint8_t channel_map[CS_CONFIG_CHANNEL_MAP_SIZE]) {
	if (!config || !channel_map_valid(channel_map)) {
		return -EINVAL;
	}
	/* Allow passing the record's own map back to the setter. */
	memmove(config->creation.channel_map, channel_map, sizeof(config->creation.channel_map));
	return 0;
}

int cs_initiator_config_set_creation_context(struct cs_initiator_config *config,
                                             uint8_t context) {
	if (!config || !creation_context_valid(context)) {
		return -EINVAL;
	}
	config->creation.context = context;
	return 0;
}

int cs_initiator_config_set_peer_data(struct cs_initiator_config *config,
                                      uint8_t peer_data) {
	if (!config || !peer_data_valid(peer_data)) {
		return -EINVAL;
	}
	config->peer_data = peer_data;
	return 0;
}

int cs_initiator_config_check_peer_data(const struct cs_initiator_config *config) {
	if (!config || !peer_data_valid(config->peer_data)) {
		return -EINVAL;
	}
	if (config->peer_data == CS_CONFIG_PEER_DATA_NONE &&
	    !(config->creation.cs_enhancements_1 & CS_CONFIG_ENHANCEMENTS_1_IPT)) {
		return -EINVAL;
	}
	return 0;
}

int cs_initiator_config_set_t_pm(struct cs_initiator_config *config, uint8_t t_pm_us) {
	if (!config || !t_pm_valid(t_pm_us)) {
		return -EINVAL;
	}
	config->t_pm_us = t_pm_us;
	return 0;
}

/* Zephyr parameter structures are populated only here, when a record is applied. */

static int apply_connection(const struct cs_config_connection *connection, struct bt_conn *conn) {
	const struct bt_le_conn_param param = {
		.interval_min = connection->interval_min,
		.interval_max = connection->interval_max,
		.latency = connection->latency,
		.timeout = connection->timeout,
	};
	return bt_conn_le_param_update(conn, &param);
}

static int apply_default_settings(uint8_t role, const struct cs_config_default_settings *defaults,
                                  struct bt_conn *conn) {
	const struct bt_le_cs_set_default_settings_param param = {
		.enable_initiator_role = role == CS_CONFIG_ROLE_INITIATOR,
		.enable_reflector_role = role == CS_CONFIG_ROLE_REFLECTOR,
		.cs_sync_antenna_selection = (enum bt_le_cs_sync_antenna_selection_opt)defaults->cs_sync_antenna_selection,
		.max_tx_power = defaults->max_tx_power,
	};
	return bt_le_cs_set_default_settings(conn, &param);
}

static int apply_procedure(uint8_t config_id, const struct cs_config_procedure *procedure,
                           struct bt_conn *conn) {
	const struct bt_le_cs_set_procedure_parameters_param param = {
		.config_id = config_id,
		.max_procedure_len = procedure->max_procedure_len,
		.min_procedure_interval = procedure->min_procedure_interval,
		.max_procedure_interval = procedure->max_procedure_interval,
		.max_procedure_count = procedure->max_procedure_count,
		.min_subevent_len = procedure->min_subevent_len,
		.max_subevent_len = procedure->max_subevent_len,
		.tone_antenna_config_selection =
			(enum bt_conn_le_cs_tone_antenna_config_selection)procedure->tone_antenna_config_selection,
		.phy = (enum bt_le_cs_procedure_phy)procedure->phy,
		.tx_power_delta = procedure->tx_power_delta,
		.preferred_peer_antenna = procedure->preferred_peer_antenna,
		.snr_control_initiator = (enum bt_le_cs_snr_control)procedure->snr_control_initiator,
		.snr_control_reflector = (enum bt_le_cs_snr_control)procedure->snr_control_reflector,
	};
	return bt_le_cs_set_procedure_parameters(conn, &param);
}

int cs_reflector_config_apply_connection(const struct cs_reflector_config *config,
                                         struct bt_conn *conn) {
	if (!config || !conn) {
		return -EINVAL;
	}
	return apply_connection(&config->connection, conn);
}

int cs_reflector_config_apply_default_settings(const struct cs_reflector_config *config,
                                               struct bt_conn *conn) {
	if (!config || !conn) {
		return -EINVAL;
	}
	return apply_default_settings(CS_CONFIG_ROLE_REFLECTOR, &config->defaults, conn);
}

int cs_reflector_config_apply_procedure(const struct cs_reflector_config *config,
                                        struct bt_conn *conn) {
	if (!config || !conn) {
		return -EINVAL;
	}
	return apply_procedure(config->config_id, &config->procedure, conn);
}

int cs_initiator_config_apply_connection(const struct cs_initiator_config *config,
                                         struct bt_conn *conn) {
	if (!config || !conn) {
		return -EINVAL;
	}
	return apply_connection(&config->connection, conn);
}

int cs_initiator_config_apply_default_settings(const struct cs_initiator_config *config,
                                               struct bt_conn *conn) {
	if (!config || !conn) {
		return -EINVAL;
	}
	return apply_default_settings(CS_CONFIG_ROLE_INITIATOR, &config->defaults, conn);
}

int cs_initiator_config_apply_procedure(const struct cs_initiator_config *config,
                                        struct bt_conn *conn) {
	if (!config || !conn) {
		return -EINVAL;
	}
	return apply_procedure(config->config_id, &config->procedure, conn);
}

int cs_initiator_config_apply_creation(const struct cs_initiator_config *config,
                                       struct bt_conn *conn) {
	if (!config || !conn) {
		return -EINVAL;
	}
	/* The T_PM itself goes to the controller from cs_roles, before this call. */
	if (!t_pm_valid(config->t_pm_us)) {
		return -EINVAL;
	}
	const struct cs_config_creation *creation = &config->creation;
	struct bt_le_cs_create_config_params param = {
		.id = config->config_id,
		.mode = (enum bt_conn_le_cs_mode)creation->mode,
		.min_main_mode_steps = creation->min_main_mode_steps,
		.max_main_mode_steps = creation->max_main_mode_steps,
		.main_mode_repetition = creation->main_mode_repetition,
		.mode_0_steps = creation->mode_0_steps,
		.role = BT_CONN_LE_CS_ROLE_INITIATOR,
		.rtt_type = (enum bt_conn_le_cs_rtt_type)creation->rtt_type,
		.cs_sync_phy = (enum bt_conn_le_cs_sync_phy)creation->cs_sync_phy,
		.channel_map_repetition = creation->channel_map_repetition,
		.channel_selection_type = (enum bt_conn_le_cs_chsel_type)creation->channel_selection_type,
		.ch3c_shape = (enum bt_conn_le_cs_ch3c_shape)creation->ch3c_shape,
		.ch3c_jump = creation->ch3c_jump,
		.cs_enhancements_1 = creation->cs_enhancements_1,
	};
	memcpy(param.channel_map, creation->channel_map, sizeof(param.channel_map));
	return bt_le_cs_create_config(conn, &param, (enum bt_le_cs_create_config_context)creation->context);
}

static void print_local_config(struct cs_print_buf *pb, uint8_t role, uint8_t size, uint8_t config_id,
                               const struct cs_config_connection *connection,
                               const struct cs_config_default_settings *defaults,
                               const struct cs_config_procedure *procedure) {
	cs_print_append(pb, "  header: role %u, size %u bytes, config ID %u\n",
	                (unsigned int)role, (unsigned int)size, (unsigned int)config_id);
	cs_print_append(pb, "  connection: interval %u-%u us, latency %u events, timeout %u ms\n",
	                (unsigned int)connection->interval_min * 1250U,
	                (unsigned int)connection->interval_max * 1250U,
	                (unsigned int)connection->latency,
	                (unsigned int)connection->timeout * 10U);
	cs_print_append(pb, "  defaults: sync antenna %u, max TX power %d dBm\n",
	                (unsigned int)defaults->cs_sync_antenna_selection,
	                (int)defaults->max_tx_power);
	cs_print_append(pb, "  procedure: max duration %u us, interval %u-%u ACL events\n",
	                (unsigned int)procedure->max_procedure_len * 625U,
	                (unsigned int)procedure->min_procedure_interval,
	                (unsigned int)procedure->max_procedure_interval);
	cs_print_append(pb, "    max count %u (0=unlimited), subevent %u-%u us\n",
	                (unsigned int)procedure->max_procedure_count,
	                (unsigned int)procedure->min_subevent_len,
	                (unsigned int)procedure->max_subevent_len);
	cs_print_append(pb, "    tone antenna config %u, PHY %u, preferred peer antenna mask 0x%02x\n",
	                (unsigned int)procedure->tone_antenna_config_selection,
	                (unsigned int)procedure->phy,
	                (unsigned int)procedure->preferred_peer_antenna);
	if (procedure->tx_power_delta == CS_CONFIG_TX_POWER_DELTA_NONE) {
		cs_print_append(pb, "    TX power delta: no recommendation (0x80)\n");
	} else {
		cs_print_append(pb, "    TX power delta: %d dB\n", (int)procedure->tx_power_delta);
	}
	cs_print_append(pb, "    SNR control: initiator %u, reflector %u\n",
	                (unsigned int)procedure->snr_control_initiator,
	                (unsigned int)procedure->snr_control_reflector);
}

int cs_reflector_config_print(char *buf, size_t size, const struct cs_reflector_config *config) {
	struct cs_print_buf pb;

	if (!config || cs_print_init(&pb, buf, size)) {
		return -EINVAL;
	}
	cs_print_append(&pb, "CS reflector configuration (requested; HCI encodings):\n");
	print_local_config(&pb, config->role, config->size, config->config_id,
	                   &config->connection, &config->defaults, &config->procedure);
	return cs_print_result(&pb);
}

int cs_initiator_config_print(char *buf, size_t size, const struct cs_initiator_config *config) {
	struct cs_print_buf pb;

	if (!config || cs_print_init(&pb, buf, size)) {
		return -EINVAL;
	}
	const struct cs_config_creation *creation = &config->creation;
	cs_print_append(&pb, "CS initiator configuration (requested; HCI encodings):\n");
	print_local_config(&pb, config->role, config->size, config->config_id,
	                   &config->connection, &config->defaults, &config->procedure);
	cs_print_append(&pb, "  reflector data: %s (%u)\n",
	                config->peer_data == CS_CONFIG_PEER_DATA_RAS_REALTIME ? "RAS real-time" :
	                config->peer_data == CS_CONFIG_PEER_DATA_NONE ? "none (initiator only)" :
	                "unknown",
	                (unsigned int)config->peer_data);
	cs_print_append(&pb, "  preferred T_PM: %u us\n", (unsigned int)config->t_pm_us);
	cs_print_append(&pb, "  creation: context %u, mode 0x%02x\n",
	                (unsigned int)creation->context,
	                (unsigned int)creation->mode);
	cs_print_append(&pb, "    main steps %u-%u, main repetition %u, mode-0 steps %u\n",
	                (unsigned int)creation->min_main_mode_steps,
	                (unsigned int)creation->max_main_mode_steps,
	                (unsigned int)creation->main_mode_repetition,
	                (unsigned int)creation->mode_0_steps);
	cs_print_append(&pb, "    RTT type %u, sync PHY %u, enhancements 0x%02x\n",
	                (unsigned int)creation->rtt_type,
	                (unsigned int)creation->cs_sync_phy,
	                (unsigned int)creation->cs_enhancements_1);
	cs_print_append(&pb, "    channel map repetition %u, selection %u, 3c shape %u, 3c jump %u\n",
	                (unsigned int)creation->channel_map_repetition,
	                (unsigned int)creation->channel_selection_type,
	                (unsigned int)creation->ch3c_shape,
	                (unsigned int)creation->ch3c_jump);
	cs_print_append(&pb, "    channel map (byte 0 first):");
	for (unsigned int i = 0; i < sizeof(creation->channel_map); i++) {
		cs_print_append(&pb, " %02x", (unsigned int)creation->channel_map[i]);
	}
	cs_print_append(&pb, "\n    enabled CS channels (frequency = 2402 + index MHz):");
	unsigned int count = 0;
	for (unsigned int channel = 0; channel < 80; channel++) {
		if (creation->channel_map[channel / 8] & (1U << (channel % 8))) {
			cs_print_append(&pb, " %u", channel);
			count++;
		}
	}
	cs_print_append(&pb, " (%u total)\n", count);
	return cs_print_result(&pb);
}

int cs_fae_table_print(char *buf, size_t size, const int8_t *entries) {
	struct cs_print_buf pb;

	if (!entries || cs_print_init(&pb, buf, size)) {
		return -EINVAL;
	}
	cs_print_append(&pb, "CS FAE table (%u entries, raw signed HCI values):\n",
	                (unsigned int)CS_FAE_TABLE_ENTRIES);
	for (unsigned int row = 0; row < CS_FAE_TABLE_ENTRIES; row += 8) {
		cs_print_append(&pb, "  entries %02u-%02u:", row, row + 7);
		for (unsigned int column = 0; column < 8; column++) {
			cs_print_append(&pb, " %4d", (int)entries[row + column]);
		}
		cs_print_append(&pb, "\n");
	}
	return cs_print_result(&pb);
}
