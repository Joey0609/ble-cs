/* SPDX-License-Identifier: MIT */
/* Drains the record queue, formats each record with the cs_utils printers and
 * writes the text to USB CDC. This is the only thread that formats reports,
 * so it owns the static buffers below.
 */
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <cs_utils/cs_capabilities.h>
#include <cs_utils/cs_config.h>
#include <cs_utils/cs_reports.h>
#include <cs_utils/cs_results.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

#include "cdc_out.h"
#include "cs_events.h"
#include "record_queue.h"
#include "report_printer.h"

LOG_MODULE_REGISTER(report_printer, LOG_LEVEL_INF);

/* How often DTR is rechecked while no record arrives. */
#define HOST_POLL K_MSEC(200)

#define TEXT_SIZE                                                                        \
	MAX(128, MAX(MAX(CS_INITIATOR_CONFIG_PRINT_SIZE, CS_CAPABILITIES_PRINT_SIZE),     \
	    MAX(MAX(CS_FAE_TABLE_PRINT_SIZE, CS_CONFIG_COMPLETE_PRINT_SIZE),             \
	        MAX(CS_PROCEDURE_ENABLE_COMPLETE_PRINT_SIZE,                             \
	            MAX(CS_SUBEVENT_HEADER_PRINT_SIZE, CS_STEP_PRINT_SIZE)))))

static char text[TEXT_SIZE];
static uint8_t record[MAX(CS_EVENTS_SUBEVENT_BUF_SIZE, CS_FAE_TABLE_ENTRIES)];

/* Session records are kept so a host that opens the port later still gets them. */
static struct cs_initiator_config session_config;
static struct cs_capabilities session_capabilities;
static bool session_config_valid;
static bool session_capabilities_valid;
static struct cs_config_connection session_connection_params;
static bool session_connection_params_valid;

static struct report_printer_stats stats;
static K_MUTEX_DEFINE(stats_lock);

static void count(uint32_t *counter) {
	k_mutex_lock(&stats_lock, K_FOREVER);
	(*counter)++;
	k_mutex_unlock(&stats_lock);
}

/* Write one printer result. Truncated text is still written. */
static bool emit(int len) {
	if (len == -ENOSPC) {
		LOG_WRN("Report text truncated");
		count(&stats.format_errors);
		len = (int)strlen(text);
	} else if (len < 0) {
		LOG_ERR("Report formatting failed (err %d)", len);
		count(&stats.format_errors);
		return false;
	}
	return cdc_out_write(text, (size_t)len) == 0;
}

/* Records are copied out of the queue into a byte buffer, so they are read
 * back through memcpy into typed locals rather than cast in place.
 */
#define COPY_RECORD(type, dst, len) \
	((len) == sizeof(type) ? (memcpy(&(dst), record, sizeof(type)), true) : false)

static bool malformed(enum record_kind kind, size_t len) {
	LOG_ERR("Malformed record: kind %u, %zu bytes", (unsigned int)kind, len);
	count(&stats.format_errors);
	return false;
}

static bool print_subevent(size_t len) {
	const struct cs_subevent *subevent = (const struct cs_subevent *)record;

	if (len < sizeof(*subevent) || subevent->size != len) {
		return malformed(RECORD_SUBEVENT, len);
	}
	if (!emit(cs_subevent_header_print(text, sizeof(text), subevent))) {
		return false;
	}
	for (const struct cs_step_header *step = cs_step_first(subevent); step != NULL;
	     step = cs_step_next(subevent, step)) {
		if (!emit(cs_step_print(text, sizeof(text), step))) {
			return false;
		}
	}
	return true;
}

static bool print_connection_params(void) {
	int len = snprintk(text, sizeof(text),
	                   "Negotiated ACL parameters: interval %u us, latency %u events, timeout %u ms\n",
	                   session_connection_params.interval_min * 1250U,
	                   session_connection_params.latency,
	                   session_connection_params.timeout * 10U);

	return emit(len);
}

static bool print_record(enum record_kind kind, size_t len) {
	switch (kind) {
	case RECORD_REMOTE_CAPABILITIES: {
		struct cs_capabilities caps;

		if (!COPY_RECORD(struct cs_capabilities, caps, len)) {
			return malformed(kind, len);
		}
		return emit(cs_capabilities_print(text, sizeof(text), &caps));
	}
	case RECORD_CONNECTION_PARAMETERS:
		return malformed(kind, len);
	case RECORD_FAE_TABLE:
		if (len != CS_FAE_TABLE_ENTRIES) {
			return malformed(kind, len);
		}
		return emit(cs_fae_table_print(text, sizeof(text), (const int8_t *)record));
	case RECORD_CONFIG_COMPLETE: {
		struct cs_config_complete result;

		if (!COPY_RECORD(struct cs_config_complete, result, len)) {
			return malformed(kind, len);
		}
		return emit(cs_config_complete_print(text, sizeof(text), &result));
	}
	case RECORD_PROCEDURE_ENABLE_COMPLETE: {
		struct cs_procedure_enable_complete result;

		if (!COPY_RECORD(struct cs_procedure_enable_complete, result, len)) {
			return malformed(kind, len);
		}
		return emit(cs_procedure_enable_complete_print(text, sizeof(text), &result));
	}
	case RECORD_SUBEVENT:
		return print_subevent(len);
	default:
		return malformed(kind, len);
	}
}

static void print_session(void) {
	if (session_config_valid) {
		(void)emit(cs_initiator_config_print(text, sizeof(text), &session_config));
	}
	if (session_capabilities_valid) {
		(void)emit(cs_capabilities_print(text, sizeof(text), &session_capabilities));
	}
	if (session_connection_params_valid) {
		(void)print_connection_params();
	}
}

/* Returns true for records that describe the session rather than an event. */
static bool remember_session(enum record_kind kind, size_t len) {
	if (kind == RECORD_INITIATOR_CONFIG) {
		session_config_valid = COPY_RECORD(struct cs_initiator_config, session_config, len);
		return true;
	}
	if (kind == RECORD_LOCAL_CAPABILITIES) {
		session_capabilities_valid =
			COPY_RECORD(struct cs_capabilities, session_capabilities, len);
		return true;
	}
	if (kind == RECORD_CONNECTION_PARAMETERS) {
		if (!COPY_RECORD(struct cs_config_connection, session_connection_params, len)) {
			session_connection_params_valid = false;
		} else {
			session_connection_params_valid = session_connection_params.interval_min != 0U;
		}
		return true;
	}
	return false;
}

static void printer_thread(void *p1, void *p2, void *p3) {
	bool host_ready = false;
	int err;

	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);

	err = cdc_out_init();
	if (err) {
		LOG_ERR("USB CDC output unavailable (err %d); reports disabled", err);
		return;
	}

	for (;;) {
		enum record_kind kind;
		int len = record_queue_get(&kind, record, sizeof(record), HOST_POLL);
		bool session = len >= 0 && remember_session(kind, (size_t)len);
		bool ready = cdc_out_host_ready();

		if (ready != host_ready) {
			host_ready = ready;
			LOG_INF("USB host %s", ready ? "attached" : "detached");
			cdc_out_discard();
			if (ready) {
				/* Includes a session record taken just now. */
				print_session();
				if (session) {
					continue;
				}
			}
		}
		if (len == -ENOSPC) {
			LOG_ERR("Record larger than the printer buffer");
			count(&stats.format_errors);
			continue;
		}
		if (len < 0) {
			continue;
		}
		if (!ready) {
			count(&stats.discarded);
			continue;
		}
		if (session) {
			print_session();
		} else if (print_record(kind, (size_t)len)) {
			count(&stats.printed);
		}
	}
}

K_THREAD_DEFINE(report_printer, 2048, printer_thread, NULL, NULL, NULL,
                CONFIG_CS_INITIATOR_TEST_PRINTER_PRIORITY, 0, 0);

void report_printer_stats_get(struct report_printer_stats *out) {
	k_mutex_lock(&stats_lock, K_FOREVER);
	*out = stats;
	k_mutex_unlock(&stats_lock);
}
