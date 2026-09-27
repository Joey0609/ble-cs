/* SPDX-License-Identifier: MIT */
/* Shared between host_link.c and host_link_reports.c; not part of the API. */
#ifndef HOST_LINK_INTERNAL_H_
#define HOST_LINK_INTERNAL_H_

#include <stddef.h>
#include <stdint.h>

#include "host_link_frame.h"

/* Queue a finalized report frame; dropped and counted without a session. */
int host_link_send_report(const uint8_t *frame, size_t len);

/* Streamed report frames: session check, never waits, counted like host_link_send_report(). */
extern const struct host_link_frame_sink host_link_report_sink;

/* Reports sent and dropped since boot. */
void host_link_report_counters(uint32_t *sent, uint32_t *dropped);

#endif /* HOST_LINK_INTERNAL_H_ */
