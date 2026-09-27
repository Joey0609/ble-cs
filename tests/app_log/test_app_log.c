/* SPDX-License-Identifier: MIT */
/* app_log: consumer levels, formatting, truncation and the full queue. Built by
 * run.sh with CONFIG_APP_LOG_MESSAGE_MAX 64 and CONFIG_APP_LOG_QUEUE_DEPTH 4.
 */
#undef NDEBUG
#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "app_log/app_log.h"
#include "app_log/app_log_console.h"

APP_LOG_MODULE(test);

uint32_t test_uptime_ms;
char test_printk_out[512];

void printk(const char *fmt, ...) {
	va_list args;

	va_start(args, fmt);
	vsnprintf(test_printk_out, sizeof(test_printk_out), fmt, args);
	va_end(args);
}

#define CAPTURED_MAX 8

struct captured {
	unsigned int count;
	uint8_t level[CAPTURED_MAX];
	uint32_t timestamp_ms[CAPTURED_MAX];
	size_t len[CAPTURED_MAX];
	char text[CAPTURED_MAX][CONFIG_APP_LOG_MESSAGE_MAX + 1];
};

static struct captured console, protocol;

static void capture(struct captured *c, uint8_t level, uint32_t timestamp_ms, const char *text,
                    size_t len) {
	assert(c->count < CAPTURED_MAX);
	assert(len <= CONFIG_APP_LOG_MESSAGE_MAX && text[len] == '\0');
	c->level[c->count] = level;
	c->timestamp_ms[c->count] = timestamp_ms;
	c->len[c->count] = len;
	memcpy(c->text[c->count], text, len + 1);
	c->count++;
}

static void console_write(uint8_t level, uint32_t timestamp_ms, const char *text, size_t len) {
	capture(&console, level, timestamp_ms, text, len);
}

static void protocol_write(uint8_t level, uint32_t timestamp_ms, const char *text, size_t len) {
	capture(&protocol, level, timestamp_ms, text, len);
}

static void configure(uint8_t console_level, uint8_t protocol_level) {
	const struct app_log_config config = {console_level, protocol_level};

	assert(app_log_configure(&config) == 0);
}

static void reset(void) {
	app_log_flush();
	memset(&console, 0, sizeof(console));
	memset(&protocol, 0, sizeof(protocol));
	assert(app_log_sink_register(APP_LOG_SINK_CONSOLE, console_write) == 0);
	assert(app_log_sink_register(APP_LOG_SINK_PROTOCOL, protocol_write) == 0);
}

static unsigned int evaluations;

static int evaluated(void) {
	return (int)++evaluations;
}

static void test_defaults(void) {
	struct app_log_config config, defaults;

	app_log_config_get(&config);
	app_log_defaults(&defaults);
	assert(config.console_level == APP_LOG_LEVEL_INF && config.protocol_level == APP_LOG_LEVEL_WRN);
	assert(memcmp(&config, &defaults, sizeof(config)) == 0);

	/* At boot only the console is registered. */
	assert(app_log_enabled(APP_LOG_LEVEL_INF));
	assert(!app_log_enabled(APP_LOG_LEVEL_DBG));
	assert(!app_log_enabled(APP_LOG_LEVEL_OFF));
}

static void test_configure_checks(void) {
	const struct app_log_config too_high = {APP_LOG_LEVEL_MAX + 1, APP_LOG_LEVEL_ERR};
	const struct app_log_config too_high_protocol = {APP_LOG_LEVEL_ERR, APP_LOG_LEVEL_MAX + 1};
	struct app_log_config config;

	configure(APP_LOG_LEVEL_DBG, APP_LOG_LEVEL_OFF);
	assert(app_log_configure(NULL) == -EINVAL);
	assert(app_log_configure(&too_high) == -EINVAL);
	assert(app_log_configure(&too_high_protocol) == -EINVAL);
	app_log_config_get(&config);
	assert(config.console_level == APP_LOG_LEVEL_DBG && config.protocol_level == APP_LOG_LEVEL_OFF);
	assert(app_log_sink_register(APP_LOG_SINK_COUNT, console_write) == -EINVAL);
}

static void test_thresholds(void) {
	reset();
	configure(APP_LOG_LEVEL_INF, APP_LOG_LEVEL_WRN);
	test_uptime_ms = 1234;
	APP_LOG_ERR("error %d", 1);
	APP_LOG_WRN("warning %d", 2);
	APP_LOG_INF("info %d", 3);
	APP_LOG_DBG("debug %d", evaluated());
	assert(evaluations == 0U);
	app_log_flush();

	assert(console.count == 3U && protocol.count == 2U);
	assert(strcmp(console.text[0], "<err> test: error 1") == 0);
	assert(console.level[0] == APP_LOG_LEVEL_ERR && console.timestamp_ms[0] == 1234U);
	assert(strcmp(console.text[1], "<wrn> test: warning 2") == 0);
	assert(strcmp(console.text[2], "<inf> test: info 3") == 0);
	assert(console.len[2] == strlen("<inf> test: info 3"));
	assert(strcmp(protocol.text[0], "<err> test: error 1") == 0);
	assert(strcmp(protocol.text[1], "<wrn> test: warning 2") == 0);

	/* Each consumer has its own threshold. */
	reset();
	configure(APP_LOG_LEVEL_OFF, APP_LOG_LEVEL_DBG);
	APP_LOG_DBG("debug %d", evaluated());
	assert(evaluations == 1U);
	app_log_flush();
	assert(console.count == 0U && protocol.count == 1U);
	assert(strcmp(protocol.text[0], "<dbg> test: debug 1") == 0);

	/* Both off: no message is formatted. */
	reset();
	configure(APP_LOG_LEVEL_OFF, APP_LOG_LEVEL_OFF);
	for (uint8_t level = APP_LOG_LEVEL_OFF; level <= APP_LOG_LEVEL_MAX; level++) {
		assert(!app_log_enabled(level));
	}
	APP_LOG_ERR("error %d", evaluated());
	assert(evaluations == 1U);

	/* A level of its own is never a message level. */
	configure(APP_LOG_LEVEL_DBG, APP_LOG_LEVEL_DBG);
	app_log_printf("test", APP_LOG_LEVEL_OFF, "off");
	app_log_printf("test", APP_LOG_LEVEL_MAX + 1, "too high");
	app_log_flush();
	assert(console.count == 0U && protocol.count == 0U);
}

static void test_missing_protocol_consumer(void) {
	reset();
	assert(app_log_sink_register(APP_LOG_SINK_PROTOCOL, NULL) == 0);
	configure(APP_LOG_LEVEL_OFF, APP_LOG_LEVEL_DBG);
	assert(!app_log_enabled(APP_LOG_LEVEL_ERR));
	APP_LOG_ERR("error %d", evaluated());
	assert(evaluations == 1U);
	app_log_flush();
	assert(console.count == 0U && protocol.count == 0U);

	/* The console still receives its messages. */
	configure(APP_LOG_LEVEL_WRN, APP_LOG_LEVEL_DBG);
	APP_LOG_WRN("warning");
	app_log_flush();
	assert(console.count == 1U && protocol.count == 0U);
}

static void test_truncation(void) {
	char expected[CONFIG_APP_LOG_MESSAGE_MAX + 1];
	char long_text[2 * CONFIG_APP_LOG_MESSAGE_MAX];

	reset();
	configure(APP_LOG_LEVEL_INF, APP_LOG_LEVEL_OFF);
	memset(long_text, 'x', sizeof(long_text) - 1U);
	long_text[sizeof(long_text) - 1U] = '\0';
	APP_LOG_INF("%s", long_text);
	app_log_flush();

	assert(console.count == 1U && console.len[0] == CONFIG_APP_LOG_MESSAGE_MAX);
	snprintf(expected, sizeof(expected), "<inf> test: %s", long_text);
	assert(strcmp(console.text[0], expected) == 0);

	/* A module name longer than a message still ends in bounds. */
	app_log_printf("a_module_name_that_is_longer_than_the_whole_message_text_allows_for",
	               APP_LOG_LEVEL_INF, "text");
	app_log_flush();
	assert(console.count == 2U && console.len[1] == CONFIG_APP_LOG_MESSAGE_MAX);
}

static void test_full_queue(void) {
	uint32_t dropped = app_log_dropped();

	reset();
	configure(APP_LOG_LEVEL_INF, APP_LOG_LEVEL_WRN);
	for (int i = 0; i < CONFIG_APP_LOG_QUEUE_DEPTH + 2; i++) {
		APP_LOG_WRN("message %d", i);
	}
	assert(app_log_dropped() == dropped + 2U);
	app_log_flush();

	/* The first freed record makes room: the count follows it as one warning. */
	assert(console.count == CONFIG_APP_LOG_QUEUE_DEPTH + 1U);
	assert(strcmp(console.text[0], "<wrn> test: message 0") == 0);
	assert(strcmp(console.text[1], "<wrn> app_log: 2 messages dropped: queue full") == 0);
	assert(console.level[1] == APP_LOG_LEVEL_WRN);
	assert(strcmp(console.text[2], "<wrn> test: message 1") == 0);
	assert(strcmp(console.text[CONFIG_APP_LOG_QUEUE_DEPTH], "<wrn> test: message 3") == 0);
	assert(protocol.count == console.count);
	assert(strcmp(protocol.text[1], console.text[1]) == 0);

	/* The queue is usable again, and the warning is not repeated. */
	APP_LOG_WRN("after");
	app_log_flush();
	assert(console.count == CONFIG_APP_LOG_QUEUE_DEPTH + 2U);
	assert(strcmp(console.text[CONFIG_APP_LOG_QUEUE_DEPTH + 1], "<wrn> test: after") == 0);
}

static void test_console_format(void) {
	app_log_console_write(APP_LOG_LEVEL_INF, 61234U, "<inf> m: text", 13U);
	assert(strcmp(test_printk_out, "[61.234] <inf> m: text\n") == 0);
	/* Only len bytes are printed. */
	app_log_console_write(APP_LOG_LEVEL_INF, 5U, "<inf> m: text", 8U);
	assert(strcmp(test_printk_out, "[0.005] <inf> m:\n") == 0);
}

int main(void) {
	test_defaults();
	test_configure_checks();
	test_thresholds();
	test_missing_protocol_consumer();
	test_truncation();
	test_full_queue();
	test_console_format();
	puts("app_log tests passed");
	return 0;
}
