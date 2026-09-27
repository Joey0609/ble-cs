/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <zephyr/sys/ring_buffer.h>

#include "record_queue.h"

/* Every record is stored as this header followed by len bytes. */
struct entry_header {
	uint16_t len;
	uint8_t kind;
	uint8_t reserved;
};

RING_BUF_DECLARE(queue, CONFIG_CS_INITIATOR_TEST_RECORD_QUEUE_SIZE);

/* Producers and the consumer are all threads; a mutex keeps interrupts,
 * including the radio's, enabled while a subevent is copied.
 */
static K_MUTEX_DEFINE(queue_lock);
static K_SEM_DEFINE(queue_entries, 0, K_SEM_MAX_LIMIT);

static struct record_queue_stats stats = {
	.capacity = CONFIG_CS_INITIATOR_TEST_RECORD_QUEUE_SIZE,
};

int record_queue_put(enum record_kind kind, const void *data, size_t len) {
	const struct entry_header header = {.len = (uint16_t)len, .kind = (uint8_t)kind};

	if (len > UINT16_MAX) {
		return -EINVAL;
	}

	k_mutex_lock(&queue_lock, K_FOREVER);
	if (ring_buf_space_get(&queue) < sizeof(header) + len) {
		stats.dropped++;
		k_mutex_unlock(&queue_lock);
		return -ENOMEM;
	}
	(void)ring_buf_put(&queue, (const uint8_t *)&header, sizeof(header));
	(void)ring_buf_put(&queue, data, (uint32_t)len);
	stats.queued++;
	stats.high_water = MAX(stats.high_water, ring_buf_size_get(&queue));
	k_mutex_unlock(&queue_lock);

	k_sem_give(&queue_entries);
	return 0;
}

int record_queue_get(enum record_kind *kind, void *buf, size_t size, k_timeout_t timeout) {
	struct entry_header header;
	int ret;

	if (k_sem_take(&queue_entries, timeout)) {
		return -EAGAIN;
	}

	k_mutex_lock(&queue_lock, K_FOREVER);
	(void)ring_buf_get(&queue, (uint8_t *)&header, sizeof(header));
	if (header.len > size) {
		(void)ring_buf_get(&queue, NULL, header.len);
		ret = -ENOSPC;
	} else {
		(void)ring_buf_get(&queue, buf, header.len);
		*kind = (enum record_kind)header.kind;
		ret = header.len;
	}
	k_mutex_unlock(&queue_lock);
	return ret;
}

void record_queue_stats_get(struct record_queue_stats *out) {
	k_mutex_lock(&queue_lock, K_FOREVER);
	*out = stats;
	k_mutex_unlock(&queue_lock);
}
