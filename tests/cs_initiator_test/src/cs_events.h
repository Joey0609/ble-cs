/* SPDX-License-Identifier: MIT */
#ifndef CS_EVENTS_H_
#define CS_EVENTS_H_

#include <stdint.h>

#include <cs_utils/cs_reports.h>

/** Largest subevent record the callbacks capture. */
#define CS_EVENTS_SUBEVENT_BUF_SIZE CS_SUBEVENT_BUF_SIZE(CONFIG_CS_INITIATOR_TEST_SUBEVENT_MAX_STEPS)

/** CS setup steps whose completion the test sequence waits for. */
enum cs_events_stage {
	CS_STAGE_REMOTE_CAPABILITIES,
	CS_STAGE_FAE_TABLE,
	CS_STAGE_CONFIG_CREATED,
	CS_STAGE_SECURITY_ENABLED,
	CS_STAGE_PROCEDURE_ENABLED,
};

/**
 * @brief Called on the Bluetooth RX thread when a setup step completes.
 *
 * Must not block.
 *
 * @param stage Step that completed.
 * @param status HCI status of the step; 0 on success.
 */
typedef void (*cs_events_stage_cb)(enum cs_events_stage stage, uint8_t status);

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

/** @brief Set the setup step handler. Call before bt_enable(). */
void cs_events_register(cs_events_stage_cb cb);

/** @brief Copy the counters. */
void cs_events_stats_get(struct cs_events_stats *stats);

#endif /* CS_EVENTS_H_ */
