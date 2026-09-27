/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief Application log with consumers selected at runtime.
 *
 * Every application and library in this repository logs through these macros.
 * A message reaches each registered consumer whose level admits it:
 * - console: printk, reaching the UART or RTT console (app_log_console.c);
 * - protocol: LOG_MESSAGE frames, registered by host_link while a host session
 *   is open (or by its report-only transport).
 *
 * The levels are part of the applied configuration (app_log_configure()),
 * changed without rebuilding. Kconfig only sizes the library.
 *
 * Callers check the level, format the message and queue it; they never block.
 * A log thread writes queued messages to the consumers. A message that finds
 * the queue full is dropped and counted, and the count is logged as one
 * warning once room returns. Thread context only, including Bluetooth
 * callbacks and work items; not from an ISR.
 */

#ifndef APP_LOG_H_
#define APP_LOG_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#if defined(__has_include)
#  if __has_include(<zephyr/toolchain.h>)
#    include <zephyr/toolchain.h>
#  else
#    define __printf_like(f, a) __attribute__((format(printf, f, a)))
#    define __maybe_unused __attribute__((__unused__))
#  endif
#else
#  include <zephyr/toolchain.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif

/** Levels in Zephyr numbering. A consumer at a level receives that level and the ones below it. */
enum app_log_level {
	APP_LOG_LEVEL_OFF = 0,
	APP_LOG_LEVEL_ERR = 1,
	APP_LOG_LEVEL_WRN = 2,
	APP_LOG_LEVEL_INF = 3,
	APP_LOG_LEVEL_DBG = 4,
};

/** Highest valid level. */
#define APP_LOG_LEVEL_MAX APP_LOG_LEVEL_DBG

/** Console level until a configuration is applied. */
#define APP_LOG_CONSOLE_LEVEL_DEFAULT APP_LOG_LEVEL_INF
/** Protocol level until a configuration is applied: the host keeps receiving abnormal situations. */
#define APP_LOG_PROTOCOL_LEVEL_DEFAULT APP_LOG_LEVEL_WRN

/** Consumer levels, each one of @ref app_log_level. */
struct app_log_config {
	uint8_t console_level;
	uint8_t protocol_level;
};

/** Log consumers. */
enum app_log_sink {
	/** printk; registered at boot. */
	APP_LOG_SINK_CONSOLE,
	/** LOG_MESSAGE frames; registered by host_link. */
	APP_LOG_SINK_PROTOCOL,
	APP_LOG_SINK_COUNT,
};

/**
 * @brief Consumer write function, called on the log thread (or in app_log_flush()).
 *
 * @param level        Level of the message.
 * @param timestamp_ms Uptime when the message was queued.
 * @param text         "<lvl> module: message", NUL-terminated.
 * @param len          Bytes of @p text, at most CONFIG_APP_LOG_MESSAGE_MAX.
 */
typedef void (*app_log_write_t)(uint8_t level, uint32_t timestamp_ms, const char *text, size_t len);

/** @brief Fill @p config with the defaults. */
static inline void app_log_defaults(struct app_log_config *config) {
	config->console_level = APP_LOG_CONSOLE_LEVEL_DEFAULT;
	config->protocol_level = APP_LOG_PROTOCOL_LEVEL_DEFAULT;
}

/**
 * @brief Set the consumer levels.
 * @retval 0 Applied.
 * @retval -EINVAL @p config is NULL or a level is above @ref APP_LOG_LEVEL_MAX; nothing changed.
 */
int app_log_configure(const struct app_log_config *config);

/** @brief Copy the current consumer levels. */
void app_log_config_get(struct app_log_config *config);

/**
 * @brief Register the write function of a consumer.
 *
 * @param write The consumer, or NULL to remove it. Without a consumer, its
 *              messages are discarded before they are formatted.
 * @retval 0 Registered.
 * @retval -EINVAL Unknown @p sink.
 */
int app_log_sink_register(enum app_log_sink sink, app_log_write_t write);

/** @brief True when a registered consumer admits a message at @p level. */
bool app_log_enabled(uint8_t level);

/**
 * @brief Format a message and queue it. Usually called through @ref APP_LOG_INF and its siblings.
 *
 * Text longer than CONFIG_APP_LOG_MESSAGE_MAX, prefix included, is truncated.
 */
__printf_like(3, 4) void app_log_printf(const char *module, uint8_t level, const char *fmt, ...);

/**
 * @brief Write every queued message from the calling thread.
 *
 * For a thread that is about to reset the device, and for tests.
 */
void app_log_flush(void);

/** @brief Messages dropped for a full queue since boot. */
uint32_t app_log_dropped(void);

/**
 * @brief Name the module of the messages logged in this file.
 *
 * Once per source file, before the first APP_LOG_* call. Files of one library
 * may share a name.
 */
#define APP_LOG_MODULE(name) static const char app_log_module_[] __maybe_unused = #name

/** Log an error, a warning, information or debug detail with printf rules. */
#define APP_LOG_ERR(...) APP_LOG_(APP_LOG_LEVEL_ERR, __VA_ARGS__)
/** @copydoc APP_LOG_ERR */
#define APP_LOG_WRN(...) APP_LOG_(APP_LOG_LEVEL_WRN, __VA_ARGS__)
/** @copydoc APP_LOG_ERR */
#define APP_LOG_INF(...) APP_LOG_(APP_LOG_LEVEL_INF, __VA_ARGS__)
/** @copydoc APP_LOG_ERR */
#define APP_LOG_DBG(...) APP_LOG_(APP_LOG_LEVEL_DBG, __VA_ARGS__)

/* The arguments are not evaluated when no consumer admits the level. */
#define APP_LOG_(level_, ...)                                          \
	do {                                                               \
		if (app_log_enabled(level_)) {                                 \
			app_log_printf(app_log_module_, (level_), __VA_ARGS__);    \
		}                                                              \
	} while (0)

#ifdef __cplusplus
}
#endif

#endif /* APP_LOG_H_ */
