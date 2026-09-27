/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>

#include "cs_print_internal.h"

int cs_print_init(struct cs_print_buf *pb, char *buf, size_t size) {
	if (!buf || size == 0U) {
		return -EINVAL;
	}
	*pb = (struct cs_print_buf){.buf = buf, .size = size};
	buf[0] = '\0';
	return 0;
}

void cs_print_append(struct cs_print_buf *pb, const char *fmt, ...) {
	va_list args;
	int written;
	size_t space;

	if (pb->overflow) {
		return;
	}
	space = pb->size - pb->len;
	va_start(args, fmt);
	written = vsnprintf(pb->buf + pb->len, space, fmt, args);
	va_end(args);

	if (written < 0 || (size_t)written >= space) {
		/* vsnprintf has already NUL-terminated the prefix that fits. */
		pb->overflow = true;
		pb->len = pb->size - 1U;
		pb->buf[pb->len] = '\0';
		return;
	}
	pb->len += (size_t)written;
}

int cs_print_result(const struct cs_print_buf *pb) {
	return pb->overflow ? -ENOSPC : (int)pb->len;
}
