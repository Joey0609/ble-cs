/* SPDX-License-Identifier: MIT */
#ifndef REPORT_PRINTER_H_
#define REPORT_PRINTER_H_

#include <stdint.h>

/** Printer counters, for the debug UART. */
struct report_printer_stats {
	/** Records formatted and written to the host. */
	uint32_t printed;
	/** Records discarded because no host had the port open. */
	uint32_t discarded;
	/** Printer calls that returned -ENOSPC or -EINVAL, or malformed records. */
	uint32_t format_errors;
};

/**
 * @brief Copy the printer counters.
 *
 * The printer thread starts at boot. It takes records from the record queue,
 * formats them with the cs_utils printers and writes the text to USB CDC.
 */
void report_printer_stats_get(struct report_printer_stats *stats);

#endif /* REPORT_PRINTER_H_ */
