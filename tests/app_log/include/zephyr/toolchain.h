/* SPDX-License-Identifier: MIT */
/* Test-only subset of the Zephyr toolchain macros app_log uses. */
#ifndef TEST_TOOLCHAIN_H_
#define TEST_TOOLCHAIN_H_

#define __printf_like(f, a) __attribute__((format(printf, f, a)))
#define __maybe_unused __attribute__((__unused__))
#define ARG_UNUSED(x) (void)(x)
#define BUILD_ASSERT(expr, ...) _Static_assert(expr, "" __VA_ARGS__)

#endif /* TEST_TOOLCHAIN_H_ */
