/* SPDX-License-Identifier: MIT */
/* CS callbacks. Each one packs or parses its event with cs_utils and queues
 * the record; formatting happens later in the report printer. Only status and
 * errors are logged here.
 */
#include <cs_utils/cs_capabilities.h>
#include <cs_utils/cs_config.h>
#include <cs_utils/cs_results.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/logging/log.h>
#include <zephyr/sys/atomic.h>

#include "cs_events.h"
#include "record_queue.h"

LOG_MODULE_REGISTER(cs_events, LOG_LEVEL_INF);

/* Step reports say nothing about the layout they use, so the role and RTT
 * type of each configuration are cached from its creation event.
 */
static struct {
	enum bt_conn_le_cs_role role;
	enum bt_conn_le_cs_rtt_type rtt_type;
	bool valid;
} layouts[CS_CONFIG_ID_MAX + 1U];

/* All callbacks run on the Bluetooth RX thread, which owns these. */
static struct cs_subevent_counter subevent_counter;
static uint8_t subevent_buf[CS_EVENTS_SUBEVENT_BUF_SIZE];

static atomic_t subevents;
static atomic_t truncated;
static atomic_t parse_errors;
static atomic_t procedures_complete;
static atomic_t procedures_aborted;

static void queue(enum record_kind kind, const void *data, size_t len) {
	/* A full queue is counted by the queue and reported with its stats. */
	(void)record_queue_put(kind, data, len);
}

static void remote_capabilities_cb(struct bt_conn *conn, uint8_t status,
                                   struct bt_conn_le_cs_capabilities *params) {
	struct cs_capabilities record;

	if (status) {
		LOG_ERR("CS capability exchange failed (HCI status 0x%02x)", status);
		return;
	}
	LOG_INF("CS capability exchange complete");
	if (cs_capabilities_pack(&record, conn, params, 0) == 0) {
		queue(RECORD_REMOTE_CAPABILITIES, &record, record.size);
	}
}

static void remote_fae_table_cb(struct bt_conn *conn, uint8_t status,
                                struct bt_conn_le_cs_fae_table *params) {
	ARG_UNUSED(conn);
	if (status || !params || !params->remote_fae_table) {
		LOG_ERR("CS FAE table exchange failed (HCI status 0x%02x)", status);
		return;
	}
	LOG_INF("CS FAE table exchange complete");
	queue(RECORD_FAE_TABLE, params->remote_fae_table, CS_FAE_TABLE_ENTRIES);
}

static void config_complete_cb(struct bt_conn *conn, uint8_t status,
                               struct bt_conn_le_cs_config *config) {
	struct cs_config_complete record;

	if (cs_config_complete_pack(&record, conn, status, config, 0) == 0) {
		queue(RECORD_CONFIG_COMPLETE, &record, record.size);
	}
	if (status) {
		LOG_ERR("CS configuration failed (HCI status 0x%02x)", status);
		return;
	}
	if (config->id > CS_CONFIG_ID_MAX) {
		LOG_ERR("CS configuration ID %u out of range", config->id);
		return;
	}
	layouts[config->id].role = config->role;
	layouts[config->id].rtt_type = config->rtt_type;
	layouts[config->id].valid = true;
	LOG_INF("CS configuration %u created", config->id);
}

static void config_removed_cb(struct bt_conn *conn, uint8_t config_id) {
	ARG_UNUSED(conn);
	if (config_id <= CS_CONFIG_ID_MAX) {
		layouts[config_id].valid = false;
	}
	LOG_INF("CS configuration %u removed", config_id);
}

static void security_enable_cb(struct bt_conn *conn, uint8_t status) {
	ARG_UNUSED(conn);
	if (status) {
		LOG_ERR("CS security enable failed (HCI status 0x%02x)", status);
	} else {
		LOG_INF("CS security enabled");
	}
}

static void procedure_enable_cb(struct bt_conn *conn, uint8_t status,
                                struct bt_conn_le_cs_procedure_enable_complete *params) {
	struct cs_procedure_enable_complete record;

	if (cs_procedure_enable_complete_pack(&record, conn, status, params, 0) == 0) {
		queue(RECORD_PROCEDURE_ENABLE_COMPLETE, &record, record.size);
	}
	if (status) {
		LOG_ERR("CS procedure enable failed (HCI status 0x%02x)", status);
		return;
	}
	LOG_INF("CS procedures %s for configuration %u",
	        params->state ? "enabled" : "disabled", params->config_id);
}

static void count_outcome(const struct bt_conn_le_cs_subevent_result *result) {
	const uint8_t config_id = result->header.config_id;

	if (result->header.procedure_done_status == BT_CONN_LE_CS_PROCEDURE_COMPLETE) {
		atomic_inc(&procedures_complete);
	} else if (result->header.procedure_done_status == BT_CONN_LE_CS_PROCEDURE_ABORTED) {
		atomic_inc(&procedures_aborted);
		LOG_WRN("CS procedure %u (config %u) aborted: reason %u",
		        result->header.procedure_counter, config_id,
		        result->header.procedure_abort_reason);
	}
	if (result->header.subevent_done_status == BT_CONN_LE_CS_SUBEVENT_ABORTED) {
		LOG_WRN("CS subevent of procedure %u aborted: reason %u at step %u",
		        result->header.procedure_counter, result->header.subevent_abort_reason,
		        result->header.abort_step);
	}
}

static void subevent_result_cb(struct bt_conn *conn, struct bt_conn_le_cs_subevent_result *result) {
	const uint8_t config_id = result->header.config_id;
	const struct cs_subevent *record = (const struct cs_subevent *)subevent_buf;
	struct cs_subevent_parse_cfg cfg;
	int err;

	ARG_UNUSED(conn);
	atomic_inc(&subevents);
	count_outcome(result);

	/* Take the index for every report so later subevents keep their numbers. */
	cfg.subevent_id = cs_subevent_counter_next(&subevent_counter, result);
	cfg.timestamp_us = 0;

	if (config_id > CS_CONFIG_ID_MAX || !layouts[config_id].valid) {
		atomic_inc(&parse_errors);
		LOG_WRN("No cached layout for CS configuration %u", config_id);
		return;
	}
	cfg.role = layouts[config_id].role;
	cfg.rtt_type = layouts[config_id].rtt_type;

	err = cs_subevent_parse(result, &cfg, subevent_buf, sizeof(subevent_buf));
	if (err == -ENOMEM) {
		atomic_inc(&truncated);
	} else if (err) {
		atomic_inc(&parse_errors);
		LOG_WRN("CS subevent of procedure %u not parsed (err %d)",
		        result->header.procedure_counter, err);
		return;
	}
	queue(RECORD_SUBEVENT, record, record->size);
}

static void disconnected_cb(struct bt_conn *conn, uint8_t reason) {
	ARG_UNUSED(conn);
	ARG_UNUSED(reason);
	/* Configurations and procedure counters belong to the connection. */
	for (size_t i = 0; i < ARRAY_SIZE(layouts); i++) {
		layouts[i].valid = false;
	}
	subevent_counter = (struct cs_subevent_counter){0};
}

/* Registered alongside RAS and main.c; Zephyr calls every registration. */
BT_CONN_CB_DEFINE(cs_event_callbacks) = {
	.disconnected = disconnected_cb,
	.le_cs_read_remote_capabilities_complete = remote_capabilities_cb,
	.le_cs_read_remote_fae_table_complete = remote_fae_table_cb,
	.le_cs_config_complete = config_complete_cb,
	.le_cs_config_removed = config_removed_cb,
	.le_cs_security_enable_complete = security_enable_cb,
	.le_cs_procedure_enable_complete = procedure_enable_cb,
	.le_cs_subevent_data_available = subevent_result_cb,
};

void cs_events_stats_get(struct cs_events_stats *stats) {
	*stats = (struct cs_events_stats){
		.subevents = (uint32_t)atomic_get(&subevents),
		.truncated = (uint32_t)atomic_get(&truncated),
		.parse_errors = (uint32_t)atomic_get(&parse_errors),
		.procedures_complete = (uint32_t)atomic_get(&procedures_complete),
		.procedures_aborted = (uint32_t)atomic_get(&procedures_aborted),
	};
}
