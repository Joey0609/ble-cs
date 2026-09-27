/* SPDX-License-Identifier: MIT */
/* Stands in for <zephyr/kernel.h> so the Zephyr Bluetooth headers build on the
 * host: they need only these kernel types, and cs_utils calls no kernel API.
 */
#ifndef TEST_ZEPHYR_KERNEL_H_
#define TEST_ZEPHYR_KERNEL_H_

#include <stdint.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/slist.h>
#include <zephyr/sys/util.h>

typedef struct {
	int64_t ticks;
} k_timeout_t;

struct k_lifo {
	void *head;
};

struct k_spinlock {
	int locked;
};

void k_lifo_put(struct k_lifo *lifo, void *data);

#endif /* TEST_ZEPHYR_KERNEL_H_ */
