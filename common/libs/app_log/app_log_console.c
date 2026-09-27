/* SPDX-License-Identifier: MIT */
#include <zephyr/sys/printk.h>
#include <zephyr/toolchain.h>

#include "app_log_console.h"

void app_log_console_write(uint8_t level, uint32_t timestamp_ms, const char *text, size_t len) {
	ARG_UNUSED(level);
	printk("[%u.%03u] %.*s\n", (unsigned int)(timestamp_ms / 1000U),
	       (unsigned int)(timestamp_ms % 1000U), (int)len, text);
}
