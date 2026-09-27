/* SPDX-License-Identifier: MIT */
/* Stands in for <zephyr/kernel.h> in the cs_roles native tests. The Zephyr
 * Bluetooth headers need its types; cs_roles gets message queues and
 * semaphores that never block, and time from a clock the test advances.
 * No thread runs: the tests call the role and event threads' functions.
 */
#ifndef TEST_CS_ROLES_KERNEL_H_
#define TEST_CS_ROLES_KERNEL_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/slist.h>
#include <zephyr/sys/util.h>

typedef struct {
	int64_t ms;
} k_timeout_t;
#define K_NO_WAIT ((k_timeout_t){.ms = 0})
#define K_FOREVER ((k_timeout_t){.ms = -1})
#define K_MSEC(ms_) ((k_timeout_t){.ms = (ms_)})
#define K_TIMEOUT_EQ(a, b) ((a).ms == (b).ms)

/* Milliseconds since the test started; the test advances it. */
extern int64_t test_now_ms;
static inline int64_t k_uptime_ticks(void) {
	return test_now_ms * CONFIG_SYS_CLOCK_TICKS_PER_SEC / 1000;
}

typedef struct {
	int64_t ms;
} k_timepoint_t;
static inline k_timepoint_t sys_timepoint_calc(k_timeout_t timeout) {
	return (k_timepoint_t){.ms = timeout.ms < 0 ? INT64_MAX : test_now_ms + timeout.ms};
}
static inline int sys_timepoint_cmp(k_timepoint_t a, k_timepoint_t b) {
	return a.ms == b.ms ? 0 : (a.ms < b.ms ? -1 : 1);
}
static inline bool sys_timepoint_expired(k_timepoint_t timepoint) {
	return timepoint.ms <= test_now_ms;
}
static inline k_timeout_t sys_timepoint_timeout(k_timepoint_t timepoint) {
	if (timepoint.ms == INT64_MAX) {
		return K_FOREVER;
	}
	return (k_timeout_t){.ms = timepoint.ms > test_now_ms ? timepoint.ms - test_now_ms : 0};
}

struct k_lifo {
	void *head;
};
struct k_spinlock {
	int locked;
};
void k_lifo_put(struct k_lifo *lifo, void *data);

struct k_sem {
	unsigned int count;
	unsigned int limit;
};
static inline int k_sem_init(struct k_sem *sem, unsigned int initial, unsigned int limit) {
	sem->count = initial;
	sem->limit = limit;
	return 0;
}
static inline void k_sem_give(struct k_sem *sem) {
	if (sem->count < sem->limit) {
		sem->count++;
	}
}
/* Nothing else runs, so a semaphore that is not available now never will be. */
static inline int k_sem_take(struct k_sem *sem, k_timeout_t timeout) {
	(void)timeout;
	if (!sem->count) {
		return -11; /* -EAGAIN */
	}
	sem->count--;
	return 0;
}

/* A ring of fixed-size messages. */
struct k_msgq {
	char *buffer;
	size_t msg_size;
	uint32_t max_msgs;
	uint32_t used;
	uint32_t read;
};
#define K_MSGQ_DEFINE(name, size, count, align)                                            \
	static _Alignas(align) char name##_buffer[(count) * (size)];                        \
	struct k_msgq name = {.buffer = name##_buffer, .msg_size = (size), .max_msgs = (count)}
/* Timeout of the last k_msgq_put(): whether the caller would have waited for room. */
extern k_timeout_t test_msgq_put_timeout;
static inline int k_msgq_put(struct k_msgq *q, const void *data, k_timeout_t timeout) {
	test_msgq_put_timeout = timeout;
	if (q->used == q->max_msgs) {
		return -35; /* -ENOMSG */
	}
	memcpy(q->buffer + ((q->read + q->used) % q->max_msgs) * q->msg_size, data, q->msg_size);
	q->used++;
	return 0;
}
static inline int k_msgq_get(struct k_msgq *q, void *data, k_timeout_t timeout) {
	(void)timeout;
	if (!q->used) {
		return -35; /* -ENOMSG */
	}
	memcpy(data, q->buffer + q->read * q->msg_size, q->msg_size);
	q->read = (q->read + 1U) % q->max_msgs;
	q->used--;
	return 0;
}
static inline uint32_t k_msgq_num_free_get(struct k_msgq *q) {
	return q->max_msgs - q->used;
}
static inline uint32_t k_msgq_num_used_get(struct k_msgq *q) {
	return q->used;
}
static inline void k_msgq_purge(struct k_msgq *q) {
	q->used = 0U;
	q->read = 0U;
}

struct k_thread {
	int unused;
};
typedef struct k_thread *k_tid_t;
typedef void (*k_thread_entry_t)(void *, void *, void *);
#define K_THREAD_STACK_DEFINE(name, size) static char name[(size)]
#define K_THREAD_STACK_SIZEOF(name) sizeof(name)
#define K_PRIO_PREEMPT(prio) (prio)
/* The thread the test is pretending to run in; NULL for Bluetooth context. */
extern k_tid_t test_current_thread;
static inline k_tid_t k_current_get(void) { return test_current_thread; }
static inline k_tid_t k_thread_create(struct k_thread *thread, char *stack, size_t size,
                                      k_thread_entry_t entry, void *p1, void *p2, void *p3,
                                      int prio, uint32_t options, k_timeout_t delay) {
	(void)stack, (void)size, (void)entry, (void)p1, (void)p2, (void)p3;
	(void)prio, (void)options, (void)delay;
	return thread;
}
static inline int k_thread_name_set(k_tid_t thread, const char *name) {
	(void)thread, (void)name;
	return 0;
}

#endif /* TEST_CS_ROLES_KERNEL_H_ */
