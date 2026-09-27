/* SPDX-License-Identifier: MIT */
/* Interrupt-driven CDC ACM transmitter, following usb_acm_rate_test. */
#include <errno.h>
#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/ring_buffer.h>

#include "cdc_out.h"

/* How long a writer waits for the FIFO to drain before rechecking DTR. */
#define WRITE_WAIT K_MSEC(100)

static const struct device *const cdc = DEVICE_DT_GET(DT_NODELABEL(cdc_acm_uart0));

RING_BUF_DECLARE(tx_ring, CONFIG_CS_INITIATOR_TEST_CDC_TX_BUF_SIZE);

/* The CDC ACM callback runs on its workqueue, so both sides are threads. */
static K_MUTEX_DEFINE(tx_lock);
static K_SEM_DEFINE(tx_drained, 0, 1);

static struct cdc_out_stats stats;

static void transmit_ready(const struct device *dev, void *user_data) {
	uint8_t *data;
	uint32_t claimed;
	int sent;
	bool empty;

	ARG_UNUSED(user_data);
	if (!uart_irq_update(dev) || !uart_irq_tx_ready(dev)) {
		return;
	}

	k_mutex_lock(&tx_lock, K_FOREVER);
	claimed = ring_buf_get_claim(&tx_ring, &data, CONFIG_CS_INITIATOR_TEST_CDC_TX_BUF_SIZE);
	sent = claimed ? uart_fifo_fill(dev, data, (int)claimed) : 0;
	(void)ring_buf_get_finish(&tx_ring, sent > 0 ? (uint32_t)sent : 0U);
	empty = ring_buf_is_empty(&tx_ring);
	if (empty) {
		/* Disable while holding the lock so a concurrent write re-enables it. */
		uart_irq_tx_disable(dev);
	}
	k_mutex_unlock(&tx_lock);

	if (sent > 0 || empty) {
		k_sem_give(&tx_drained);
	}
}

int cdc_out_init(void) {
	if (!device_is_ready(cdc)) {
		return -ENODEV;
	}
	return uart_irq_callback_user_data_set(cdc, transmit_ready, NULL);
}

bool cdc_out_host_ready(void) {
	uint32_t dtr = 0;

	return uart_line_ctrl_get(cdc, UART_LINE_CTRL_DTR, &dtr) == 0 && dtr != 0U;
}

void cdc_out_discard(void) {
	k_mutex_lock(&tx_lock, K_FOREVER);
	ring_buf_reset(&tx_ring);
	k_mutex_unlock(&tx_lock);
}

int cdc_out_write(const char *data, size_t len) {
	while (len > 0U) {
		uint32_t queued;

		if (!cdc_out_host_ready()) {
			k_mutex_lock(&tx_lock, K_FOREVER);
			stats.aborted_writes++;
			k_mutex_unlock(&tx_lock);
			return -EPIPE;
		}

		k_mutex_lock(&tx_lock, K_FOREVER);
		queued = ring_buf_put(&tx_ring, (const uint8_t *)data, (uint32_t)MIN(len, UINT32_MAX));
		stats.bytes += queued;
		if (queued > 0U) {
			uart_irq_tx_enable(cdc);
		}
		k_mutex_unlock(&tx_lock);

		data += queued;
		len -= queued;
		if (len > 0U) {
			(void)k_sem_take(&tx_drained, WRITE_WAIT);
		}
	}
	return 0;
}

void cdc_out_stats_get(struct cdc_out_stats *out) {
	k_mutex_lock(&tx_lock, K_FOREVER);
	*out = stats;
	k_mutex_unlock(&tx_lock);
}
