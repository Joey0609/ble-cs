/* SPDX-License-Identifier: MIT */
/* Test-only kernel subset for app_log.c: a fixed block pool, a FIFO and no
 * threads. The test drains the queue with app_log_flush().
 */
#ifndef TEST_KERNEL_H_
#define TEST_KERNEL_H_

#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/toolchain.h>

#define MIN(a, b) ((a) < (b) ? (a) : (b))
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define CLAMP(v, lo, hi) MIN(MAX((v), (lo)), (hi))
#define __ASSERT(cond, msg) assert((cond) && (msg))

typedef struct {
	bool forever;
} k_timeout_t;
#define K_NO_WAIT ((k_timeout_t){.forever = false})
#define K_FOREVER ((k_timeout_t){.forever = true})

static inline bool k_is_in_isr(void) { return false; }

/* Uptime the test sets. */
extern uint32_t test_uptime_ms;
static inline uint32_t k_uptime_get_32(void) { return test_uptime_ms; }

#define TEST_SLAB_BLOCKS_MAX 64
struct k_mem_slab {
	char *buffer;
	size_t block_size;
	unsigned int num_blocks;
	bool used[TEST_SLAB_BLOCKS_MAX];
};
#define K_MEM_SLAB_DEFINE_STATIC(name, size, count, align)                               \
	_Static_assert((count) <= TEST_SLAB_BLOCKS_MAX, "test slab size");                 \
	static _Alignas(align) char name##_buffer[(count) * (size)];                        \
	static struct k_mem_slab name = {.buffer = name##_buffer, .block_size = (size),      \
	                                 .num_blocks = (count)}

static inline int k_mem_slab_alloc(struct k_mem_slab *slab, void **mem, k_timeout_t timeout) {
	(void)timeout;
	for (unsigned int i = 0; i < slab->num_blocks; i++) {
		if (!slab->used[i]) {
			slab->used[i] = true;
			*mem = slab->buffer + i * slab->block_size;
			return 0;
		}
	}
	return -12; /* -ENOMEM */
}

static inline void k_mem_slab_free(struct k_mem_slab *slab, void *mem) {
	slab->used[((char *)mem - slab->buffer) / slab->block_size] = false;
}

/* Items start with a reserved pointer, as with the Zephyr FIFO. */
struct k_fifo {
	void *head;
	void *tail;
};
#define K_FIFO_DEFINE(name) struct k_fifo name = {0}

static inline void k_fifo_put(struct k_fifo *fifo, void *data) {
	*(void **)data = NULL;
	if (fifo->tail) {
		*(void **)fifo->tail = data;
	} else {
		fifo->head = data;
	}
	fifo->tail = data;
}

static inline void *k_fifo_get(struct k_fifo *fifo, k_timeout_t timeout) {
	void *data = fifo->head;

	/* Nothing can arrive while the only thread waits. */
	assert(data || !timeout.forever);
	if (data) {
		fifo->head = *(void **)data;
		if (!fifo->head) {
			fifo->tail = NULL;
		}
	}
	return data;
}

struct k_mutex {
	int locked;
};
#define K_MUTEX_DEFINE(name) struct k_mutex name = {0}
static inline int k_mutex_lock(struct k_mutex *mutex, k_timeout_t timeout) {
	(void)timeout;
	assert(!mutex->locked);
	mutex->locked = 1;
	return 0;
}
static inline int k_mutex_unlock(struct k_mutex *mutex) {
	mutex->locked = 0;
	return 0;
}

/* No threads: the thread function is only referenced. */
#define K_THREAD_DEFINE(name, stack, entry, p1, p2, p3, prio, options, delay) \
	void (*const name##_entry)(void *, void *, void *) = entry

#endif /* TEST_KERNEL_H_ */
