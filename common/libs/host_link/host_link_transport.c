/* SPDX-License-Identifier: MIT */
/* Interrupt-driven UART transport (USB CDC ACM or a hardware UART), following
 * the test apps' cdc_out.c.
 */
#include <errno.h>
#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/ring_buffer.h>

#include "host_link_transport.h"

/* How long a writer waits for the FIFO to drain before rechecking DTR. */
#define WRITE_WAIT_MS 100

/* Compile-time bounds on every wait in this file; nothing here waits forever. */
BUILD_ASSERT(CONFIG_APP_HOST_LINK_RESPONSE_TIMEOUT_MS > 0 &&
                     CONFIG_APP_HOST_LINK_RESPONSE_TIMEOUT_MS <= HOST_LINK_TRANSPORT_MAX_WAIT_MS,
             "The response wait must be bounded");
BUILD_ASSERT(CONFIG_APP_HOST_LINK_REPORT_TIMEOUT_MS <= CONFIG_APP_HOST_LINK_RESPONSE_TIMEOUT_MS,
             "A report never waits longer than a response");

BUILD_ASSERT(DT_HAS_CHOSEN(app_host_link_uart),
		     "The report transport needs a devicetree chosen node app,host-link-uart");

static const struct device *const uart = DEVICE_DT_GET(DT_CHOSEN(app_host_link_uart));

RING_BUF_DECLARE(rx_ring, CONFIG_APP_HOST_LINK_RX_BUF_SIZE);
RING_BUF_DECLARE(tx_ring, CONFIG_APP_HOST_LINK_TX_BUF_SIZE);

/* Spinlocks never sleep: the UART callback and senders only hold them for ring
 * buffer bookkeeping, so no caller can be blocked indefinitely by another.
 */
static struct k_spinlock rx_lock;
static struct k_spinlock tx_lock;
static K_SEM_DEFINE(tx_drained, 0, 1);

static struct k_sem *rx_ready;
static struct host_link_transport_stats stats;

/* Streamed frame writer (host_link_transport_frame_begin()), under tx_lock. */
static struct {
	bool busy;
	/* Bumped by host_link_transport_discard(); a frame spanning a reset is abandoned. */
	uint32_t generation;
	uint32_t frame_generation;
	size_t remaining;
} writer;

static void receive(const struct device *dev) {
	uint8_t buf[64];
	int len;
	bool received = false;

	while ((len = uart_fifo_read(dev, buf, sizeof(buf))) > 0) {
		K_SPINLOCK(&rx_lock) {
			uint32_t stored = ring_buf_put(&rx_ring, buf, (uint32_t)len);

			stats.rx_bytes += len;
			stats.rx_overruns += (uint32_t)len - stored;
		}
		received = true;
	}

	if (received) {
		k_sem_give(rx_ready);
	}
}

static void transmit(const struct device *dev) {
	uint8_t *data;
	uint32_t claimed;
	int sent;
	bool empty;
	k_spinlock_key_t key = k_spin_lock(&tx_lock);

	/* The CDC ACM and UARTE FIFO calls neither sleep nor wait. */
	claimed = ring_buf_get_claim(&tx_ring, &data, CONFIG_APP_HOST_LINK_TX_BUF_SIZE);
	sent = claimed ? uart_fifo_fill(dev, data, (int)claimed) : 0;
	(void)ring_buf_get_finish(&tx_ring, sent > 0 ? (uint32_t)sent : 0U);
	empty = ring_buf_is_empty(&tx_ring);
	if (empty) {
		/* Disable while holding the lock so a concurrent send re-enables it. */
		uart_irq_tx_disable(dev);
	}
	k_spin_unlock(&tx_lock, key);

	if (sent > 0 || empty) {
		k_sem_give(&tx_drained);
	}
}

static void uart_callback(const struct device *dev, void *user_data) {
	ARG_UNUSED(user_data);

	while (uart_irq_update(dev) && uart_irq_is_pending(dev)) {
		if (uart_irq_rx_ready(dev)) {
			receive(dev);
		}
		if (uart_irq_tx_ready(dev)) {
			transmit(dev);
		}
	}
}

int host_link_transport_init(struct k_sem *rx_sem) {
	int err;

	if (!device_is_ready(uart)) {
		return -ENODEV;
	}
	rx_ready = rx_sem;
	err = uart_irq_callback_user_data_set(uart, uart_callback, NULL);
	if (err) {
		return err;
	}
	uart_irq_rx_enable(uart);
	return 0;
}

bool host_link_transport_host_ready(void) {
#if defined(CONFIG_APP_HOST_LINK_DTR)
	uint32_t dtr = 0;

	return uart_line_ctrl_get(uart, UART_LINE_CTRL_DTR, &dtr) == 0 && dtr != 0U;
#else
	/* No DTR: the port is always treated as open; CLOSE_SESSION ends a session. */
	return true;
#endif
}

size_t host_link_transport_read(uint8_t *data, size_t len) {
	uint32_t read = 0U;

	K_SPINLOCK(&rx_lock) {
		read = ring_buf_get(&rx_ring, data, (uint32_t)MIN(len, UINT32_MAX));
	}
	return read;
}

void host_link_transport_discard(void) {
	K_SPINLOCK(&rx_lock) {
		ring_buf_reset(&rx_ring);
	}
	K_SPINLOCK(&tx_lock) {
		ring_buf_reset(&tx_ring);
		writer.generation++;
	}
}

static int32_t wait_ms(enum host_link_transport_wait wait) {
	return wait == HOST_LINK_TRANSPORT_WAIT_REPORT ? CONFIG_APP_HOST_LINK_REPORT_TIMEOUT_MS
	                                               : CONFIG_APP_HOST_LINK_RESPONSE_TIMEOUT_MS;
}

/* Queue the frame if the host is there and it fits; never waits. */
static int try_queue(const uint8_t *frame, size_t len) {
	int err = -EAGAIN;

	if (!host_link_transport_host_ready()) {
		return -EPIPE;
	}
	K_SPINLOCK(&tx_lock) {
		if (!writer.busy && ring_buf_space_get(&tx_ring) >= len) {
			(void)ring_buf_put(&tx_ring, frame, (uint32_t)len);
			stats.tx_frames++;
			uart_irq_tx_enable(uart);
			err = 0;
		}
	}
	return err;
}

int host_link_transport_send(const uint8_t *frame, size_t len, enum host_link_transport_wait wait) {
	/* The deadline is fixed on entry, so retries never extend the wait. */
	k_timepoint_t end = sys_timepoint_calc(k_is_in_isr() ? K_NO_WAIT : K_MSEC(wait_ms(wait)));
	int err = len > CONFIG_APP_HOST_LINK_TX_BUF_SIZE ? -EMSGSIZE : try_queue(frame, len);

	while (err == -EAGAIN && !sys_timepoint_expired(end)) {
		k_timeout_t remaining = sys_timepoint_timeout(end);

		if (remaining.ticks > K_MSEC(WRITE_WAIT_MS).ticks) {
			remaining = K_MSEC(WRITE_WAIT_MS);
		}
		(void)k_sem_take(&tx_drained, remaining);
		err = try_queue(frame, len);
	}
	if (err) {
		K_SPINLOCK(&tx_lock) {
			stats.tx_dropped++;
		}
	}
	return err;
}

int host_link_transport_frame_begin(size_t len) {
	int err = -EAGAIN;

	if (len > CONFIG_APP_HOST_LINK_TX_BUF_SIZE) {
		err = -EMSGSIZE;
	} else if (!host_link_transport_host_ready()) {
		err = -EPIPE;
	} else {
		K_SPINLOCK(&tx_lock) {
			/* Only the writer puts while it is held and the UART only frees
			 * room, so the room checked here stays available.
			 */
			if (!writer.busy && ring_buf_space_get(&tx_ring) >= len) {
				writer.busy = true;
				writer.remaining = len;
				writer.frame_generation = writer.generation;
				err = 0;
			}
		}
	}
	if (err) {
		K_SPINLOCK(&tx_lock) {
			stats.tx_dropped++;
		}
	}
	return err;
}

void host_link_transport_frame_write(const uint8_t *data, size_t len) {
	K_SPINLOCK(&tx_lock) {
		if (writer.busy && writer.frame_generation == writer.generation &&
		    len <= writer.remaining) {
			(void)ring_buf_put(&tx_ring, data, (uint32_t)len);
			writer.remaining -= len;
		}
	}
}

int host_link_transport_frame_end(void) {
	int err = 0;

	K_SPINLOCK(&tx_lock) {
		if (writer.remaining != 0U || writer.frame_generation != writer.generation) {
			err = -EIO;
			stats.tx_dropped++;
		} else {
			stats.tx_frames++;
		}
		writer.busy = false;
		writer.remaining = 0U;
		uart_irq_tx_enable(uart);
	}
	/* Wake a sender that found the writer busy. */
	k_sem_give(&tx_drained);
	return err;
}

void host_link_transport_stats_get(struct host_link_transport_stats *out) {
	K_SPINLOCK(&rx_lock) {
		out->rx_bytes = stats.rx_bytes;
		out->rx_overruns = stats.rx_overruns;
	}
	K_SPINLOCK(&tx_lock) {
		out->tx_frames = stats.tx_frames;
		out->tx_dropped = stats.tx_dropped;
	}
}
