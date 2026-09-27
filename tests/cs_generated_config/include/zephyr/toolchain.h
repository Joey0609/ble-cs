/* SPDX-License-Identifier: MIT */
#ifndef TEST_TOOLCHAIN_H_
#define TEST_TOOLCHAIN_H_
/* Apple clang predefines __weak for Objective-C garbage collection. */
#undef __weak
#define __weak __attribute__((__weak__))
/* For app_log.h. */
#define __printf_like(f, a) __attribute__((format(printf, f, a)))
#define __maybe_unused __attribute__((__unused__))
#endif
