/* SPDX-License-Identifier: MIT */
/* Native USB CDC transmitter: 4096-byte bursts every 10 ms. See README.md. */
#include <stdint.h>
#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

static const struct device *const cdc =
		DEVICE_DT_GET(DT_NODELABEL(cdc_acm_uart0));
static uint8_t payload[4096];
static size_t offset;
K_SEM_DEFINE(burst_available,
             1,
             1);
K_TIMER_DEFINE(burst_timer,
               NULL,
               NULL);

/* Inspect in a debugger; never print into the binary data stream. */
volatile uint32_t usb_rate_skipped_bursts;
volatile uint32_t usb_burst_count = 0;
volatile uint64_t usb_burst_bytes = 0;

static void transmit_ready(const struct device *dev,
                           void *user_data) {
	ARG_UNUSED(user_data);

	if (!uart_irq_update(dev) || !uart_irq_tx_ready(dev)) {
		return;
	}

	/* Submit only the current burst and preserve partial-write progress. */
	int sent = uart_fifo_fill(dev, payload + offset, sizeof(payload) - offset);

	if (sent <= 0) {
		return;
	}
	offset += (size_t)sent;
	usb_burst_bytes += (uint64_t)sent;
	if (offset == sizeof(payload)) {
		offset = 0;
		/* Disable before releasing the producer, avoiding a lost TX wakeup. */
		uart_irq_tx_disable(dev);
		k_sem_give(&burst_available);
		usb_burst_count++;
	}
}

int monitor_bursts(void *arg1,
                   void *arg2,
                   void *arg3) {
	ARG_UNUSED(arg1);
	ARG_UNUSED(arg2);
	ARG_UNUSED(arg3);
	for (;;) {
		uint32_t dtr = 0;
		k_sleep(K_MSEC(200));
		if (uart_line_ctrl_get(cdc, UART_LINE_CTRL_DTR, &dtr) != 0 || !dtr) {
			continue;
		}
		printk("USB CDC current burst %u, skipped %u, bytes: %llu\n",
		       usb_burst_count,
		       usb_rate_skipped_bursts,
		       (unsigned long long)usb_burst_bytes);
	}
	return 0;
}

K_THREAD_DEFINE(monitor_thread,
                1024,
                monitor_bursts,
                NULL,
                NULL,
                NULL,
                K_LOWEST_APPLICATION_THREAD_PRIO,
                0,
                0);

int main(void) {
	for (size_t i = 0; i < sizeof(payload); ++i) {
		payload[i] = (uint8_t)i;
	}
	if (!device_is_ready(cdc)) {
		return -1;
	}
	if (uart_irq_callback_user_data_set(cdc, transmit_ready, NULL) != 0) {
		return -1;
	}

	k_timer_start(&burst_timer, K_MSEC(10), K_MSEC(1));
	for (;;) {
		uint32_t periods = k_timer_status_sync(&burst_timer);
		uint32_t dtr = 0;

		if (uart_line_ctrl_get(cdc, UART_LINE_CTRL_DTR, &dtr) != 0 || !dtr) {
			continue;
		}
		/* Do not turn a delayed producer into an artificial catch-up burst.
		 * If the previous burst still cannot enter the FIFO, count this drop.
		 */
		usb_rate_skipped_bursts += periods - 1;
		if (k_sem_take(&burst_available, K_NO_WAIT) != 0) {
			usb_rate_skipped_bursts++;
			continue;
		}
		uart_irq_tx_enable(cdc);
	}
	return 0;
}
