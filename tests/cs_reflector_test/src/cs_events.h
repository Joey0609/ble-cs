/* SPDX-License-Identifier: MIT */
#ifndef CS_EVENTS_H_
#define CS_EVENTS_H_

#include <stdint.h>

#include <cs_utils/cs_reports.h>

/** Largest subevent record the callbacks capture. */
#define CS_EVENTS_SUBEVENT_BUF_SIZE CS_SUBEVENT_BUF_SIZE(CONFIG_CS_REFLECTOR_TEST_SUBEVENT_MAX_STEPS)

/** Measurement counters since boot, for the debug UART and the verdict. */
struct cs_events_stats {
	/** Subevent reports received. */
	uint32_t subevents;
	/** Reports whose steps did not all fit the parse buffer. */
	uint32_t truncated;
	/** Reports cs_subevent_parse() rejected, or with no cached layout. */
	uint32_t parse_errors;
	/** Procedures whose last subevent reported completion. */
	uint32_t procedures_complete;
	/** Procedures reported aborted. */
	uint32_t procedures_aborted;
};

/** @brief Copy the counters. */
void cs_events_stats_get(struct cs_events_stats *stats);

#endif /* CS_EVENTS_H_ */
