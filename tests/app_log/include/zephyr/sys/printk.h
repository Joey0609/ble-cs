/* SPDX-License-Identifier: MIT */
/* Test-only printk: vsnprintk and snprintk follow the C library; printk output is captured. */
#ifndef TEST_PRINTK_H_
#define TEST_PRINTK_H_

#include <stdio.h>

#include <zephyr/toolchain.h>

#define snprintk snprintf
#define vsnprintk vsnprintf

/* Last printk output, for the console consumer test. */
extern char test_printk_out[512];
__printf_like(1, 2) void printk(const char *fmt, ...);

#endif /* TEST_PRINTK_H_ */
