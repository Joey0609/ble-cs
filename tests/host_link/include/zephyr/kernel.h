/* SPDX-License-Identifier: MIT */
/* Test-only kernel subset for host_link.c: no threads, no work queue. The test
 * drives the host link thread's functions directly.
 */
#ifndef TEST_HOST_LINK_KERNEL_H_
#define TEST_HOST_LINK_KERNEL_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define MIN(a, b) ((a) < (b) ? (a) : (b))
#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))
#define ARG_UNUSED(x) (void)(x)
#define BUILD_ASSERT(expr, ...) _Static_assert(expr, "" __VA_ARGS__)
/* Only used with CONFIG_ symbols the test defines as 0 or 1. */
#define IS_ENABLED(config) (config)

typedef struct {
	int64_t ms;
} k_timeout_t;
#define K_NO_WAIT ((k_timeout_t){.ms = 0})
#define K_MSEC(ms_) ((k_timeout_t){.ms = (ms_)})

struct k_sem {
	unsigned int count;
};
#define K_SEM_DEFINE(name, initial, limit) struct k_sem name = {.count = (initial)}
static inline int k_sem_take(struct k_sem *sem, k_timeout_t timeout) {
	(void)timeout;
	if (!sem->count) {
		return -11; /* -EAGAIN */
	}
	sem->count--;
	return 0;
}

struct k_thread {
	int unused;
};
typedef void (*k_thread_entry_t)(void *, void *, void *);
#define K_THREAD_STACK_DEFINE(name, size) static char name[(size)]
#define K_THREAD_STACK_SIZEOF(name) sizeof(name)
static inline void *k_thread_create(struct k_thread *thread, char *stack, size_t size,
                                    k_thread_entry_t entry, void *p1, void *p2, void *p3,
                                    int prio, uint32_t options, k_timeout_t delay) {
	(void)stack, (void)size, (void)entry, (void)p1, (void)p2, (void)p3;
	(void)prio, (void)options, (void)delay;
	return thread;
}
static inline int k_thread_name_set(struct k_thread *thread, const char *name) {
	(void)thread, (void)name;
	return 0;
}

struct k_work {
	int unused;
};
struct k_work_delayable {
	void (*handler)(struct k_work *work);
};
#define K_WORK_DELAYABLE_DEFINE(name, handler_) struct k_work_delayable name = {.handler = (handler_)}
static inline int k_work_schedule(struct k_work_delayable *work, k_timeout_t delay) {
	(void)work, (void)delay;
	return 0;
}

#endif /* TEST_HOST_LINK_KERNEL_H_ */
