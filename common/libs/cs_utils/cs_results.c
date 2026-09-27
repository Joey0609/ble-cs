/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <stddef.h>
#include <string.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/bluetooth/hci_types.h>

#include "cs_print_internal.h"
#include "cs_results.h"
#include "cs_reports.h"

/* Records are transmitted as raw bytes; the header offsets a reader relies on
 * are part of the contract.
 */
BUILD_ASSERT(offsetof(struct cs_config_complete, type) == 0U);
BUILD_ASSERT(offsetof(struct cs_config_complete, size) == 1U);
BUILD_ASSERT(offsetof(struct cs_config_complete, timestamp_us) == 4U);
BUILD_ASSERT(offsetof(struct cs_procedure_enable_complete, type) == 0U);
BUILD_ASSERT(offsetof(struct cs_procedure_enable_complete, size) == 1U);
BUILD_ASSERT(offsetof(struct cs_procedure_enable_complete, timestamp_us) == 4U);
BUILD_ASSERT((int)CS_RESULT_PROCEDURES_DISABLED == (int)BT_CONN_LE_CS_PROCEDURES_DISABLED);
BUILD_ASSERT((int)CS_RESULT_PROCEDURES_ENABLED == (int)BT_CONN_LE_CS_PROCEDURES_ENABLED);
BUILD_ASSERT(CS_CONFIG_CHANNEL_MAP_SIZE == sizeof(((struct bt_conn_le_cs_config *)0)->channel_map));

int cs_config_complete_pack(struct cs_config_complete *dst,
                            const struct bt_conn *conn,
                            uint8_t status,
                            const struct bt_conn_le_cs_config *src,
                            uint64_t timestamp_us) {
	if (!dst || !conn || (status == 0 && !src)) {
		return -EINVAL;
	}
	*dst = (struct cs_config_complete){
		.type = CS_RESULT_TYPE_CONFIG_COMPLETE,
		.size = sizeof(struct cs_config_complete),
		.conn_index = bt_conn_index(conn),
		.status = status,
		.timestamp_us = timestamp_us ? timestamp_us : cs_subevent_timestamp_us(),
	};
	if (status != 0) {
		return 0;
	}
	dst->config_id = src->id;
	dst->mode = (uint8_t)src->mode;
	dst->min_main_mode_steps = src->min_main_mode_steps;
	dst->max_main_mode_steps = src->max_main_mode_steps;
	dst->main_mode_repetition = src->main_mode_repetition;
	dst->mode_0_steps = src->mode_0_steps;
	dst->role = (uint8_t)src->role;
	dst->rtt_type = (uint8_t)src->rtt_type;
	dst->cs_sync_phy = (uint8_t)src->cs_sync_phy;
	dst->channel_map_repetition = src->channel_map_repetition;
	dst->channel_selection_type = (uint8_t)src->channel_selection_type;
	dst->ch3c_shape = (uint8_t)src->ch3c_shape;
	dst->ch3c_jump = src->ch3c_jump;
	dst->cs_enhancements_1 = src->cs_enhancements_1;
	dst->t_ip1_time_us = src->t_ip1_time_us;
	dst->t_ip2_time_us = src->t_ip2_time_us;
	dst->t_fcs_time_us = src->t_fcs_time_us;
	dst->t_pm_time_us = src->t_pm_time_us;
	memcpy(dst->channel_map, src->channel_map, sizeof(dst->channel_map));
	return 0;
}

int cs_procedure_enable_complete_pack(struct cs_procedure_enable_complete *dst,
                                      const struct bt_conn *conn,
                                      uint8_t status,
                                      const struct bt_conn_le_cs_procedure_enable_complete *src,
                                      uint64_t timestamp_us) {
	if (!dst || !conn || (status == 0 && !src)) {
		return -EINVAL;
	}
	*dst = (struct cs_procedure_enable_complete){
		.type = CS_RESULT_TYPE_PROCEDURE_ENABLE_COMPLETE,
		.size = sizeof(struct cs_procedure_enable_complete),
		.conn_index = bt_conn_index(conn),
		.status = status,
		.timestamp_us = timestamp_us ? timestamp_us : cs_subevent_timestamp_us(),
	};
	if (status != 0) {
		return 0;
	}
	dst->config_id = src->config_id;
	dst->state = (uint8_t)src->state;
	/* Core v6.3 Vol 4 Part E 7.7.65.43: a disable event's remaining parameters are ignored. */
	if (dst->state == CS_RESULT_PROCEDURES_DISABLED) {
		return 0;
	}
	dst->subevent_len = src->subevent_len;
	dst->subevent_interval = src->subevent_interval;
	dst->event_interval = src->event_interval;
	dst->procedure_interval = src->procedure_interval;
	dst->procedure_count = src->procedure_count;
	dst->max_procedure_len = src->max_procedure_len;
	dst->tone_antenna_config_selection = (uint8_t)src->tone_antenna_config_selection;
	dst->selected_tx_power = src->selected_tx_power;
	dst->subevents_per_event = src->subevents_per_event;
	return 0;
}

static void print_header(struct cs_print_buf *pb, const char *name, uint8_t size,
                         uint8_t conn_index, uint8_t status, uint64_t timestamp_us) {
	cs_print_append(pb, "%s (HCI encodings): size %u bytes, conn %u, status 0x%02x, time %llu us\n",
	                name, (unsigned int)size, (unsigned int)conn_index, (unsigned int)status,
	                (unsigned long long)timestamp_us);
}

int cs_config_complete_print(char *buf, size_t size, const struct cs_config_complete *record) {
	struct cs_print_buf pb;

	if (!record || cs_print_init(&pb, buf, size)) {
		return -EINVAL;
	}
	print_header(&pb, "CS config complete", record->size, record->conn_index, record->status,
	             record->timestamp_us);
	if (record->status != 0) {
		return cs_print_result(&pb);
	}
	cs_print_append(&pb, "  ID %u, role %u, mode 0x%02x, RTT type %u, sync PHY %u, enhancements 0x%02x\n",
	                (unsigned int)record->config_id,
	                (unsigned int)record->role,
	                (unsigned int)record->mode,
	                (unsigned int)record->rtt_type,
	                (unsigned int)record->cs_sync_phy,
	                (unsigned int)record->cs_enhancements_1);
	cs_print_append(&pb, "  main steps %u-%u, main repetition %u, mode-0 steps %u\n",
	                (unsigned int)record->min_main_mode_steps,
	                (unsigned int)record->max_main_mode_steps,
	                (unsigned int)record->main_mode_repetition,
	                (unsigned int)record->mode_0_steps);
	cs_print_append(&pb, "  T_IP1 %u us, T_IP2 %u us, T_FCS %u us, T_PM %u us\n",
	                (unsigned int)record->t_ip1_time_us,
	                (unsigned int)record->t_ip2_time_us,
	                (unsigned int)record->t_fcs_time_us,
	                (unsigned int)record->t_pm_time_us);
	cs_print_append(&pb, "  channel map repetition %u, selection %u, 3c shape %u, 3c jump %u\n",
	                (unsigned int)record->channel_map_repetition,
	                (unsigned int)record->channel_selection_type,
	                (unsigned int)record->ch3c_shape,
	                (unsigned int)record->ch3c_jump);
	cs_print_append(&pb, "  channel map (byte 0 first):");
	for (unsigned int i = 0; i < sizeof(record->channel_map); i++) {
		cs_print_append(&pb, " %02x", (unsigned int)record->channel_map[i]);
	}
	cs_print_append(&pb, "\n  enabled CS channels (frequency = 2402 + index MHz):");
	unsigned int count = 0;
	for (unsigned int channel = 0; channel < 80; channel++) {
		if (record->channel_map[channel / 8] & (1U << (channel % 8))) {
			cs_print_append(&pb, " %u", channel);
			count++;
		}
	}
	cs_print_append(&pb, " (%u total)\n", count);
	return cs_print_result(&pb);
}

int cs_procedure_enable_complete_print(char *buf, size_t size,
                                       const struct cs_procedure_enable_complete *record) {
	struct cs_print_buf pb;

	if (!record || cs_print_init(&pb, buf, size)) {
		return -EINVAL;
	}
	print_header(&pb, "CS procedure enable complete", record->size, record->conn_index,
	             record->status, record->timestamp_us);
	if (record->status != 0) {
		return cs_print_result(&pb);
	}
	if (record->state == CS_RESULT_PROCEDURES_DISABLED) {
		cs_print_append(&pb, "  ID %u, procedures disabled\n", (unsigned int)record->config_id);
		return cs_print_result(&pb);
	}
	cs_print_append(&pb, "  ID %u, state %u, tone antenna config %u\n",
	                (unsigned int)record->config_id,
	                (unsigned int)record->state,
	                (unsigned int)record->tone_antenna_config_selection);
	if (record->selected_tx_power == CS_RESULT_TX_POWER_UNAVAILABLE) {
		cs_print_append(&pb, "  selected TX power: unavailable (0x7f)\n");
	} else {
		cs_print_append(&pb, "  selected TX power: %d dBm\n", (int)record->selected_tx_power);
	}
	cs_print_append(&pb, "  subevent %u us, %u per event, subevent interval %u us\n",
	                (unsigned int)record->subevent_len,
	                (unsigned int)record->subevents_per_event,
	                (unsigned int)record->subevent_interval * 625U);
	cs_print_append(&pb, "  event interval %u, procedure interval %u ACL events\n",
	                (unsigned int)record->event_interval,
	                (unsigned int)record->procedure_interval);
	cs_print_append(&pb, "  procedure count %u (0=until disabled), max duration %u us\n",
	                (unsigned int)record->procedure_count,
	                (unsigned int)record->max_procedure_len * 625U);
	return cs_print_result(&pb);
}
