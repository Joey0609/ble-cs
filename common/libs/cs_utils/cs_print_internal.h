/* SPDX-License-Identifier: MIT */
/**
 * @file cs_print_internal.h
 * @brief Bounded text formatting shared by the cs_utils printers. Not public API.
 */
#ifndef CS_PRINT_INTERNAL_H_
#define CS_PRINT_INTERNAL_H_

#include <stdbool.h>
#include <stddef.h>
#include <zephyr/toolchain.h>

/**
 * @brief Caller-owned output text accumulated by successive appends.
 *
 * Once an append does not fit, the buffer keeps the NUL-terminated prefix that
 * did fit and every later append is ignored.
 */
struct cs_print_buf {
	char *buf;
	size_t size;
	size_t len;
	bool overflow;
};

/**
 * @brief Start formatting into @p buf.
 * @retval 0 Ready; @p buf holds an empty string.
 * @retval -EINVAL @p buf is NULL or @p size is zero.
 */
int cs_print_init(struct cs_print_buf *pb, char *buf, size_t size);

/** @brief Append printf-formatted text, unless an earlier append overflowed. */
void cs_print_append(struct cs_print_buf *pb, const char *fmt, ...) __printf_like(2, 3);

/**
 * @brief Result a printer returns.
 * @return Characters written, excluding the NUL, or -ENOSPC after an overflow.
 */
int cs_print_result(const struct cs_print_buf *pb);

#endif /* CS_PRINT_INTERNAL_H_ */
