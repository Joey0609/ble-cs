/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief UART byte transport of the host link.
 *
 * The UART is the devicetree chosen node @c app,host-link-uart, a USB CDC ACM
 * instance or a hardware UART. Received bytes
 * go through a ring buffer to the host link thread; whole frames are queued
 * for transmission so frames from different threads never interleave.
 *
 * Nothing in the transport waits without a bound: locks are spinlocks, and the
 * only wait, for transmit room in host_link_transport_send(), ends at a deadline
 * fixed at build time by the wait class.
 */

#ifndef HOST_LINK_TRANSPORT_H_
#define HOST_LINK_TRANSPORT_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <zephyr/kernel.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Upper bound, in milliseconds, of any transport wait; enforced at build time. */
#define HOST_LINK_TRANSPORT_MAX_WAIT_MS 5000

/** How long a frame may wait for transmit room. */
enum host_link_transport_wait {
	/** Up to CONFIG_APP_HOST_LINK_RESPONSE_TIMEOUT_MS. */
	HOST_LINK_TRANSPORT_WAIT_RESPONSE,
	/** Up to CONFIG_APP_HOST_LINK_REPORT_TIMEOUT_MS. */
	HOST_LINK_TRANSPORT_WAIT_REPORT,
};

/** Transfer counters. */
struct host_link_transport_stats {
	/** Bytes received from the host. */
	uint64_t rx_bytes;
	/** Received bytes dropped because the receive buffer was full. */
	uint32_t rx_overruns;
	/** Frames queued for the host. */
	uint32_t tx_frames;
	/** Frames not queued: no room before the timeout, or no host. */
	uint32_t tx_dropped;
};

/**
 * @brief Register the UART callback and enable reception.
 *
 * @param rx_ready Given whenever received bytes are waiting.
 * @retval 0 Ready.
 * @retval -ENODEV The UART is not ready.
 * @return Other negative error from the UART driver.
 */
int host_link_transport_init(struct k_sem *rx_ready);

/**
 * @brief Whether a host has the port open (DTR asserted).
 *
 * Always true without @c CONFIG_APP_HOST_LINK_DTR.
 */
bool host_link_transport_host_ready(void);

/**
 * @brief Copy up to @p len received bytes.
 * @return Number of bytes copied.
 */
size_t host_link_transport_read(uint8_t *data, size_t len);

/** @brief Discard received bytes and bytes not yet handed to the UART. */
void host_link_transport_discard(void);

/**
 * @brief Queue one complete frame, waiting for room at most the build-time
 * timeout of @p wait.
 *
 * Either the whole frame is queued or nothing. In an ISR it never waits.
 *
 * @retval 0 Queued.
 * @retval -EPIPE No host has the port open.
 * @retval -EAGAIN No room before the timeout.
 * @retval -EMSGSIZE The frame is larger than the transmit buffer.
 */
int host_link_transport_send(const uint8_t *frame, size_t len, enum host_link_transport_wait wait);

/**
 * @brief Reserve transmit room for one frame written piece by piece.
 *
 * For frames too large to build in memory first (streamed subevent results).
 * Never waits, so it may be called from a Bluetooth callback: the room is
 * checked once. While the writer is held, host_link_transport_send() waits as
 * for a full buffer, so frames never interleave. Every successful begin must
 * be followed by writes totalling @p len bytes and host_link_transport_frame_end().
 *
 * @retval 0 Room reserved; the writer is held.
 * @retval -EPIPE No host has the port open.
 * @retval -EAGAIN Not enough room, or another frame is being written.
 * @retval -EMSGSIZE The frame is larger than the transmit buffer.
 */
int host_link_transport_frame_begin(size_t len);

/**
 * @brief Append bytes to the frame reserved with host_link_transport_frame_begin().
 *
 * Writes beyond the reserved length, or after host_link_transport_discard()
 * reset the buffer, are ignored.
 */
void host_link_transport_frame_write(const uint8_t *data, size_t len);

/**
 * @brief Release the writer and start transmission.
 * @retval 0 The frame was queued whole.
 * @retval -EIO Fewer bytes than reserved were written, or the buffer was
 *         discarded meanwhile; what was queued is not a valid frame.
 */
int host_link_transport_frame_end(void);

/** @brief Copy the transfer counters. */
void host_link_transport_stats_get(struct host_link_transport_stats *stats);

#ifdef __cplusplus
}
#endif

#endif /* HOST_LINK_TRANSPORT_H_ */
