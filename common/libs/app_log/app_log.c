/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <stdarg.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/printk.h>

#include "app_log.h"
#include "app_log_console.h"

BUILD_ASSERT(CONFIG_APP_LOG_MESSAGE_MAX <= UINT16_MAX);

/* One queued message. The first word belongs to the FIFO. */
struct record {
	void *fifo_reserved;
	uint32_t timestamp_ms;
	uint8_t level;
	uint16_t len;
	char text[CONFIG_APP_LOG_MESSAGE_MAX + 1];
};

K_MEM_SLAB_DEFINE_STATIC(record_slab, sizeof(struct record), CONFIG_APP_LOG_QUEUE_DEPTH,
                         sizeof(void *));
static K_FIFO_DEFINE(record_fifo);
/* Consumers see one message at a time, from the log thread or app_log_flush(). */
static K_MUTEX_DEFINE(write_lock);

/* Read without a lock by every caller; each is a single aligned word or byte. */
static app_log_write_t volatile sinks[APP_LOG_SINK_COUNT] = {
	[APP_LOG_SINK_CONSOLE] = app_log_console_write,
};
static volatile uint8_t sink_levels[APP_LOG_SINK_COUNT] = {
	[APP_LOG_SINK_CONSOLE] = APP_LOG_CONSOLE_LEVEL_DEFAULT,
	[APP_LOG_SINK_PROTOCOL] = APP_LOG_PROTOCOL_LEVEL_DEFAULT,
};

/* Drops not yet announced, and all drops since boot. */
static atomic_t dropped_pending;
static atomic_t dropped_total;

static const char *const level_tags[] = {
	[APP_LOG_LEVEL_ERR] = "err",
	[APP_LOG_LEVEL_WRN] = "wrn",
	[APP_LOG_LEVEL_INF] = "inf",
	[APP_LOG_LEVEL_DBG] = "dbg",
};

static bool admits(enum app_log_sink sink, uint8_t level) {
	return sinks[sink] != NULL && level <= sink_levels[sink];
}

int app_log_configure(const struct app_log_config *config) {
	if (!config || config->console_level > APP_LOG_LEVEL_MAX ||
	    config->protocol_level > APP_LOG_LEVEL_MAX) {
		return -EINVAL;
	}
	sink_levels[APP_LOG_SINK_CONSOLE] = config->console_level;
	sink_levels[APP_LOG_SINK_PROTOCOL] = config->protocol_level;
	return 0;
}

void app_log_config_get(struct app_log_config *config) {
	config->console_level = sink_levels[APP_LOG_SINK_CONSOLE];
	config->protocol_level = sink_levels[APP_LOG_SINK_PROTOCOL];
}

int app_log_sink_register(enum app_log_sink sink, app_log_write_t write) {
	if ((unsigned int)sink >= APP_LOG_SINK_COUNT) {
		return -EINVAL;
	}
	sinks[sink] = write;
	return 0;
}

bool app_log_enabled(uint8_t level) {
	if (level == APP_LOG_LEVEL_OFF || level > APP_LOG_LEVEL_MAX) {
		return false;
	}
	for (int sink = 0; sink < APP_LOG_SINK_COUNT; sink++) {
		if (admits(sink, level)) {
			return true;
		}
	}
	return false;
}

void app_log_printf(const char *module, uint8_t level, const char *fmt, ...) {
	struct record *record;
	void *block;
	va_list args;
	int prefix, text;

	__ASSERT(!k_is_in_isr(), "app_log: not from an ISR");
	if (level == APP_LOG_LEVEL_OFF || level > APP_LOG_LEVEL_MAX) {
		return;
	}
	if (k_mem_slab_alloc(&record_slab, &block, K_NO_WAIT) != 0) {
		atomic_inc(&dropped_pending);
		atomic_inc(&dropped_total);
		return;
	}
	record = block;
	record->timestamp_ms = k_uptime_get_32();
	record->level = level;

	prefix = snprintk(record->text, sizeof(record->text), "<%s> %s: ", level_tags[level], module);
	prefix = CLAMP(prefix, 0, CONFIG_APP_LOG_MESSAGE_MAX);
	va_start(args, fmt);
	text = vsnprintk(&record->text[prefix], sizeof(record->text) - prefix, fmt, args);
	va_end(args);
	record->len = (uint16_t)MIN(prefix + MAX(text, 0), CONFIG_APP_LOG_MESSAGE_MAX);
	k_fifo_put(&record_fifo, record);
}

/* write_lock held. */
static void write_sinks(uint8_t level, uint32_t timestamp_ms, const char *text, size_t len) {
	for (int sink = 0; sink < APP_LOG_SINK_COUNT; sink++) {
		app_log_write_t write = sinks[sink];

		if (write && level <= sink_levels[sink]) {
			write(level, timestamp_ms, text, len);
		}
	}
}

/* write_lock held: a record was just freed, so the queue has room again. */
static void announce_drops(void) {
	static char text[CONFIG_APP_LOG_MESSAGE_MAX + 1];
	atomic_val_t count = atomic_clear(&dropped_pending);
	int len;

	if (count == 0 || !app_log_enabled(APP_LOG_LEVEL_WRN)) {
		return;
	}
	len = snprintk(text, sizeof(text), "<wrn> app_log: %u messages dropped: queue full",
	               (unsigned int)count);
	write_sinks(APP_LOG_LEVEL_WRN, k_uptime_get_32(), text,
	            (size_t)CLAMP(len, 0, CONFIG_APP_LOG_MESSAGE_MAX));
}

static bool process(k_timeout_t timeout) {
	struct record *record = k_fifo_get(&record_fifo, timeout);

	if (!record) {
		return false;
	}
	k_mutex_lock(&write_lock, K_FOREVER);
	write_sinks(record->level, record->timestamp_ms, record->text, record->len);
	k_mem_slab_free(&record_slab, record);
	announce_drops();
	k_mutex_unlock(&write_lock);
	return true;
}

void app_log_flush(void) {
	while (process(K_NO_WAIT)) {
	}
}

uint32_t app_log_dropped(void) {
	return (uint32_t)atomic_get(&dropped_total);
}

static void log_thread(void *p1, void *p2, void *p3) {
	ARG_UNUSED(p1);
	ARG_UNUSED(p2);
	ARG_UNUSED(p3);
	for (;;) {
		(void)process(K_FOREVER);
	}
}

K_THREAD_DEFINE(app_log_thread, CONFIG_APP_LOG_THREAD_STACK_SIZE, log_thread, NULL, NULL, NULL,
                CONFIG_APP_LOG_THREAD_PRIORITY, 0, 0);
