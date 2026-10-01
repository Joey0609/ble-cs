/* SPDX-License-Identifier: MIT */
/* Control events -> queue -> event thread -> cs_role_callbacks, and local HCI
 * subevent streaming. Subevents are never queued.
 */
#include <errno.h>
#include <string.h>
#include <zephyr/kernel.h>

#include "app_log/app_log.h"
#include "cs_role_internal.h"

APP_LOG_MODULE(cs_roles);

enum event_type {
	EVENT_STATE,
	EVENT_CAPABILITIES,
	EVENT_CONFIGURATION,
	EVENT_PROCEDURE,
	EVENT_FAE,
	EVENT_RAS_LOST,
	EVENT_PROCEDURES_COMPLETE,
};

/* Small by design: no subevent data, so a full queue of them costs little RAM. */
struct event {
	uint8_t type;
	union {
		struct {
			uint8_t state;
			uint8_t failure;
			uint8_t stop_reason;
			uint8_t hci_status;
			int error;
		} state;
		struct cs_capabilities capabilities;
		struct cs_config_complete configuration;
		struct cs_procedure_enable_complete procedure;
		struct {
			uint8_t hci_status;
			int8_t entries[CS_FAE_TABLE_ENTRIES];
		} fae;
		struct {
			uint16_t procedure_counter;
			int error;
		} ras_lost;
		uint16_t procedures_completed;
	};
};
BUILD_ASSERT(sizeof(struct event) <= 128, "Control events stay small");

K_MSGQ_DEFINE(events, sizeof(struct event), CONFIG_APP_CS_ROLES_EVENT_QUEUE_DEPTH, 4);
K_THREAD_STACK_DEFINE(event_stack, CONFIG_APP_CS_ROLES_EVENT_STACK_SIZE);
static struct k_thread event_thread;
static const struct cs_role_callbacks *callbacks;

/* RAS-lost events merged for lack of queue room: count and latest procedure. */
static atomic_t lost_merged;
static atomic_t lost_merged_counter;

static void deliver(const struct event *event) {
	switch (event->type) {
	case EVENT_STATE:
		if (callbacks->state) {
			callbacks->state(event->state.state, event->state.failure,
			                 event->state.stop_reason, event->state.hci_status,
			                 event->state.error);
		}
		break;
	case EVENT_CAPABILITIES:
		if (callbacks->capabilities) {
			callbacks->capabilities(&event->capabilities);
		}
		break;
	case EVENT_CONFIGURATION:
		if (callbacks->configuration) {
			callbacks->configuration(&event->configuration);
		}
		break;
	case EVENT_PROCEDURE:
		if (callbacks->procedure) {
			callbacks->procedure(&event->procedure);
		}
		break;
	case EVENT_FAE:
		if (callbacks->fae_table) {
			callbacks->fae_table(event->fae.hci_status, CS_FAE_TABLE_LSB_DENOMINATOR,
			                     event->fae.hci_status ? NULL : event->fae.entries);
		}
		break;
	case EVENT_RAS_LOST:
		if (callbacks->ras_data_lost) {
			callbacks->ras_data_lost(event->ras_lost.procedure_counter, event->ras_lost.error);
		}
		break;
	case EVENT_PROCEDURES_COMPLETE:
		if (callbacks->procedures_complete) {
			callbacks->procedures_complete(event->procedures_completed);
		}
		break;
	default:
		break;
	}
}

/* Deliver one queued event, then one RAS-lost event for those merged meanwhile. */
static void deliver_queued(const struct event *event) {
	atomic_val_t merged;

	deliver(event);
	merged = atomic_clear(&lost_merged);
	if (merged) {
		const struct event lost = {
			.type = EVENT_RAS_LOST,
			.ras_lost = { (uint16_t)atomic_get(&lost_merged_counter), -ENOBUFS },
		};

		APP_LOG_WRN("%ld RAS data lost events merged: event queue full", (long)merged);
		deliver(&lost);
	}
}

static void event_loop(void *p1, void *p2, void *p3) {
	struct event event;

	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);
	for (;;) {
		(void)k_msgq_get(&events, &event, K_FOREVER);
		deliver_queued(&event);
	}
}

void cs_role_events_init(const struct cs_role_callbacks *new_callbacks) {
	callbacks = new_callbacks;
	k_thread_create(&event_thread, event_stack, K_THREAD_STACK_SIZEOF(event_stack), event_loop,
	                NULL, NULL, NULL, K_PRIO_PREEMPT(CONFIG_APP_CS_ROLES_EVENT_PRIORITY), 0,
	                K_NO_WAIT);
	k_thread_name_set(&event_thread, "cs_role_events");
}

bool cs_role_is_event_thread(void) {
	return k_current_get() == &event_thread;
}

/* Only the role thread waits for room: Bluetooth context never does. The event
 * thread never waits for the role thread, so the wait is bounded by the
 * application's callbacks.
 */
static void post(const struct event *event) {
	if (k_msgq_put(&events, event, cs_role_is_role_thread() ? K_FOREVER : K_NO_WAIT) != 0) {
		APP_LOG_WRN("Control event %u dropped: event queue full", event->type);
	}
}

void cs_role_notify(enum cs_role_state state, enum cs_role_failure_stage failure,
                    enum cs_role_stop_reason stop_reason, uint8_t hci_status, int error) {
	struct event event = {
		.type = EVENT_STATE,
		.state = { state, failure, stop_reason, hci_status, error },
	};

	post(&event);
}

void cs_role_event_capabilities(const struct cs_capabilities *record) {
	struct event event = { .type = EVENT_CAPABILITIES, .capabilities = *record };

	post(&event);
}

void cs_role_event_configuration(const struct cs_config_complete *record) {
	struct event event = { .type = EVENT_CONFIGURATION, .configuration = *record };

	post(&event);
}

void cs_role_event_procedure(const struct cs_procedure_enable_complete *record) {
	struct event event = { .type = EVENT_PROCEDURE, .procedure = *record };

	post(&event);
}

void cs_role_event_fae(uint8_t hci_status, const int8_t *entries) {
	struct event event = { .type = EVENT_FAE, .fae.hci_status = hci_status };

	if (!hci_status && entries) {
		memcpy(event.fae.entries, entries, sizeof(event.fae.entries));
	}
	post(&event);
}

void cs_role_event_procedures_complete(uint16_t procedures_completed) {
	struct event event = {
		.type = EVENT_PROCEDURES_COMPLETE,
		.procedures_completed = procedures_completed,
	};

	post(&event);
}

void cs_role_event_ras_lost(uint16_t procedure_counter, int error) {
	struct event event = {
		.type = EVENT_RAS_LOST,
		.ras_lost = { procedure_counter, error },
	};

	/* One per procedure at most, but unbounded over time: leave room for the
	 * events that describe state.
	 */
	if (k_msgq_num_free_get(&events) <= CONFIG_APP_CS_ROLES_EVENT_RESERVE ||
	    k_msgq_put(&events, &event, K_NO_WAIT) != 0) {
		atomic_set(&lost_merged_counter, procedure_counter);
		atomic_inc(&lost_merged);
	}
}

/* Subevent streaming. The callbacks are optional as a set. */
static bool stream_open;

int cs_role_stream_begin(const struct cs_subevent *header, uint16_t num_tones) {
	int err = callbacks->subevent_begin ? callbacks->subevent_begin(header, num_tones) : -ENOTSUP;

	stream_open = err == 0;
	return err;
}

void cs_role_stream_step(const struct cs_step_header *step) {
	if (stream_open && callbacks->subevent_step) {
		callbacks->subevent_step(step);
	}
}

void cs_role_stream_end(bool complete) {
	if (callbacks->subevent_end) {
		callbacks->subevent_end(complete);
	}
	stream_open = false;
}

void cs_role_stream_hci(const struct bt_conn_le_cs_subevent_result *result,
                        enum bt_conn_le_cs_role role) {
	uint8_t id = result->header.config_id;
	struct cs_subevent_parse_cfg cfg;
	struct cs_subevent header;
	struct bt_le_cs_subevent_step step;
	uint8_t paths = result->header.num_antenna_paths;
	uint16_t num_tones = 0U;
	uint8_t num_steps = 0U;
	size_t size = sizeof(header);
	size_t offset = 0U;
	bool complete = true;

	/* No antenna paths is valid: the controller reports 0 without phase
	 * measurement (mode 1 only).
	 */
	if (id > CS_CONFIG_ID_MAX || !(atomic_get(&cs_role_data.layouts) & BIT(id)) ||
	    paths > CS_STEP_MAX_ANTENNA_PATHS) {
		return;
	}
	cfg = (struct cs_subevent_parse_cfg){
		.role = role,
		.rtt_type = (enum bt_conn_le_cs_rtt_type)cs_role_data.rtt_types[id],
		.subevent_id = cs_subevent_counter_next(&cs_role_data.counter, result),
	};

	/* Pass 1: count what decodes, so the header can state it. */
	while (result->step_data_buf) {
		int err = cs_step_data_read(result->step_data_buf, &offset, &step);

		if (err == -ENODATA) {
			break;
		}
		int record = err ? err : cs_step_decode(&step, &cfg, paths, num_steps, NULL, 0U);

		if (record < 0 || num_steps == UINT8_MAX) {
			complete = false;
			break;
		}
		size += (size_t)record;
		num_tones += cs_step_num_tones(step.mode, paths);
		num_steps++;
	}

	header = (struct cs_subevent){
		.size = (uint16_t)size,
		.num_steps = num_steps,
		.config_id = id,
		.role = (uint8_t)role,
		.rtt_type = (uint8_t)cfg.rtt_type,
		.num_antenna_paths = paths,
		.reference_power_level = result->header.reference_power_level,
		.subevent_id = cfg.subevent_id,
		.event_id = result->header.start_acl_conn_event,
		.procedure_id = result->header.procedure_counter,
		.frequency_compensation = result->header.frequency_compensation,
		.procedure_done_status = (uint8_t)result->header.procedure_done_status,
		.subevent_done_status = (uint8_t)result->header.subevent_done_status,
		.procedure_abort_reason = (uint8_t)result->header.procedure_abort_reason,
		.subevent_abort_reason = (uint8_t)result->header.subevent_abort_reason,
		.abort_step = result->header.abort_step,
		.timestamp_us = cs_subevent_timestamp_us(),
	};
	if (cs_role_stream_begin(&header, num_tones) == 0) {
		/* Pass 2: the same steps, one decoded record at a time. */
		uint8_t record[CS_STEP_MAX_SIZE];

		offset = 0U;
		for (uint8_t i = 0U; i < num_steps; i++) {
			(void)cs_step_data_read(result->step_data_buf, &offset, &step);
			(void)cs_step_decode(&step, &cfg, paths, i, record, sizeof(record));
			cs_role_stream_step((const struct cs_step_header *)record);
		}
	}
	cs_role_stream_end(complete);
}
