/* SPDX-License-Identifier: MIT */
/* Console consumer of app_log; not part of the API. */
#ifndef APP_LOG_CONSOLE_H_
#define APP_LOG_CONSOLE_H_

#include <stddef.h>
#include <stdint.h>

/* printk of one message with its timestamp: "[s.mmm] <lvl> module: text". */
void app_log_console_write(uint8_t level, uint32_t timestamp_ms, const char *text, size_t len);

#endif /* APP_LOG_CONSOLE_H_ */
