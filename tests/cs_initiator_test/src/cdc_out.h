/* SPDX-License-Identifier: MIT */
#ifndef CDC_OUT_H_
#define CDC_OUT_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/** Transfer counters, for the debug UART. */
struct cdc_out_stats {
	/** Bytes accepted into the transmit buffer. */
	uint64_t bytes;
	/** Writes cut short because the host deasserted DTR. */
	uint32_t aborted_writes;
};

/**
 * @brief Register the CDC ACM transmit callback.
 * @retval 0 Ready.
 * @retval -ENODEV The CDC ACM device is not ready.
 * @return Other negative error from the UART driver.
 */
int cdc_out_init(void);

/** @brief Whether a host has the port open (DTR asserted). */
bool cdc_out_host_ready(void);

/** @brief Discard text not yet handed to the CDC ACM FIFO. */
void cdc_out_discard(void);

/**
 * @brief Queue @p len bytes for the host, waiting while the buffer is full.
 *
 * Call from one thread only. Never call from a Bluetooth callback.
 *
 * @retval 0 Every byte queued.
 * @retval -EPIPE The host closed the port; the rest was not queued.
 */
int cdc_out_write(const char *data, size_t len);

/** @brief Copy the transfer counters. */
void cdc_out_stats_get(struct cdc_out_stats *stats);

#endif /* CDC_OUT_H_ */
