/* SPDX-License-Identifier: MIT */
#ifndef RECORD_QUEUE_H_
#define RECORD_QUEUE_H_

#include <stddef.h>
#include <stdint.h>
#include <zephyr/kernel.h>

/** What a queued record holds; names the cs_utils printer that formats it. */
enum record_kind {
	/** struct cs_reflector_config applied by this test. */
	RECORD_REFLECTOR_CONFIG,
	/** struct cs_capabilities of the local controller. */
	RECORD_LOCAL_CAPABILITIES,
	/** struct cs_capabilities of the connected peer. */
	RECORD_REMOTE_CAPABILITIES,
	/** struct cs_config_connection with the negotiated ACL parameters. */
	RECORD_CONNECTION_PARAMETERS,
	/** CS_FAE_TABLE_ENTRIES int8_t entries of the peer's FAE table. */
	RECORD_FAE_TABLE,
	/** struct cs_config_complete. */
	RECORD_CONFIG_COMPLETE,
	/** struct cs_procedure_enable_complete. */
	RECORD_PROCEDURE_ENABLE_COMPLETE,
	/** struct cs_subevent followed by its step records. */
	RECORD_SUBEVENT,
};

/** Queue counters, for the debug UART. */
struct record_queue_stats {
	/** Records accepted. */
	uint32_t queued;
	/** Records dropped because the queue was full. */
	uint32_t dropped;
	/** Most bytes ever held at once. */
	uint32_t high_water;
	/** Capacity in bytes. */
	uint32_t capacity;
};

/**
 * @brief Copy a record into the queue without waiting.
 *
 * Safe from any thread, including Bluetooth callbacks. Not for ISRs.
 *
 * @retval 0 Queued.
 * @retval -ENOMEM Queue full; the record was dropped and counted.
 * @retval -EINVAL Record larger than UINT16_MAX bytes.
 */
int record_queue_put(enum record_kind kind, const void *data, size_t len);

/**
 * @brief Take the oldest record.
 *
 * @param[out] kind Kind of the record taken.
 * @param[out] buf Destination for the record bytes.
 * @param[in] size Capacity of @p buf.
 * @param[in] timeout How long to wait for a record.
 * @return Record length in bytes.
 * @retval -EAGAIN No record arrived within @p timeout.
 * @retval -ENOSPC Record larger than @p size; it was discarded.
 */
int record_queue_get(enum record_kind *kind, void *buf, size_t size, k_timeout_t timeout);

/** @brief Copy the queue counters. */
void record_queue_stats_get(struct record_queue_stats *stats);

#endif /* RECORD_QUEUE_H_ */
