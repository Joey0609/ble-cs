/* SPDX-License-Identifier: MIT */
/**
 * @file cs_results.h
 * @brief Pack controller-reported CS configuration and procedure results into
 *        byte-packed records.
 */
#ifndef CS_RESULTS_H_
#define CS_RESULTS_H_

#include <stddef.h>
#include <stdint.h>

#include "cs_config.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Only referenced through pointers; no Zephyr header is needed by users. */
struct bt_conn;
struct bt_conn_le_cs_config;
struct bt_conn_le_cs_procedure_enable_complete;

/**
 * @defgroup cs_results CS results
 * @brief Capture the outcome of CS configuration creation and procedure enable.
 *
 * @ref cs_config records hold what an endpoint requests. The records here hold
 * what the controller actually settled on, as reported by the
 * le_cs_config_complete and le_cs_procedure_enable_complete callbacks. They
 * follow the cs_capabilities and cs_config conventions:
 *
 * - The first two bytes are @c type and @c size, so a reader can identify and
 *   skip a record without knowing the rest of its layout.
 * - Every field is a whole, byte-aligned integer holding its HCI encoding. Use
 *   the @c CS_CONFIG_* constants from cs_config.h to interpret them.
 * - @c status is the HCI status of the callback. On a non-zero status the
 *   controller reports no parameters and every field after the header is zero.
 * - @c timestamp_us uses the same GRTC time base as subevent records, see
 *   cs_subevent_timestamp_us().
 *
 * Multi-byte fields are host-endian. On the little-endian nRF targets this is
 * little-endian on the wire.
 *
 * @par Usage
 * @code{.c}
 * static void config_complete_cb(struct bt_conn *conn, uint8_t status,
 *                                struct bt_conn_le_cs_config *config)
 * {
 *     struct cs_config_complete record;
 *
 *     if (cs_config_complete_pack(&record, conn, status, config, 0) == 0) {
 *         transmit(&record, record.size);
 *     }
 * }
 *
 * static void procedure_enable_cb(struct bt_conn *conn, uint8_t status,
 *                                 struct bt_conn_le_cs_procedure_enable_complete *params)
 * {
 *     struct cs_procedure_enable_complete record;
 *
 *     if (cs_procedure_enable_complete_pack(&record, conn, status, params, 0) == 0) {
 *         transmit(&record, record.size);
 *     }
 * }
 * @endcode
 * @{
 */

/** Record discriminant stored in the first byte. */
enum cs_result_type {
	/** @ref cs_config_complete. */
	CS_RESULT_TYPE_CONFIG_COMPLETE = 0x01,
	/** @ref cs_procedure_enable_complete. */
	CS_RESULT_TYPE_PROCEDURE_ENABLE_COMPLETE = 0x02,
};

/** @c state encodings of @ref cs_procedure_enable_complete. */
enum cs_result_procedure_state {
	CS_RESULT_PROCEDURES_DISABLED = 0x00,
	CS_RESULT_PROCEDURES_ENABLED = 0x01,
};

/** @c selected_tx_power value when the controller reports no TX power. */
#define CS_RESULT_TX_POWER_UNAVAILABLE 0x7F

/**
 * @brief Byte-packed CS configuration complete record (40 bytes).
 *
 * Field meanings follow struct bt_conn_le_cs_config.
 */
struct cs_config_complete {
	/** Always @ref CS_RESULT_TYPE_CONFIG_COMPLETE. */
	uint8_t type;
	/** Total record size in bytes; always sizeof(struct cs_config_complete). */
	uint8_t size;
	/** Zephyr connection index from bt_conn_index(). */
	uint8_t conn_index;
	/** HCI status of the event; 0 on success. */
	uint8_t status;
	/** GRTC time the event was captured, in microseconds. */
	uint64_t timestamp_us;

	/** CS configuration ID (0-3). */
	uint8_t config_id;
	/** Main mode and sub-mode, one of @ref cs_config_mode. */
	uint8_t mode;
	/** Minimum main-mode steps before a sub-mode step. */
	uint8_t min_main_mode_steps;
	/** Maximum main-mode steps before a sub-mode step. */
	uint8_t max_main_mode_steps;
	/** Main-mode steps repeated from the end of the previous subevent. */
	uint8_t main_mode_repetition;
	/** Mode-0 steps at the start of each subevent. */
	uint8_t mode_0_steps;
	/** Local CS role, one of @ref cs_config_role. */
	uint8_t role;
	/** RTT type, one of @ref cs_config_rtt_type. */
	uint8_t rtt_type;
	/** CS_SYNC PHY, one of @ref cs_config_sync_phy. */
	uint8_t cs_sync_phy;
	/** Times the channel map is cycled through for non-mode-0 steps. */
	uint8_t channel_map_repetition;
	/** Channel selection algorithm, one of @ref cs_config_chsel_type. */
	uint8_t channel_selection_type;
	/** Channel selection 3c shape, one of @ref cs_config_ch3c_shape. */
	uint8_t ch3c_shape;
	/** Channels skipped in each channel selection 3c rising/falling sequence. */
	uint8_t ch3c_jump;
	/** CS enhancements 1 bits, e.g. @ref CS_CONFIG_ENHANCEMENTS_1_IPT. */
	uint8_t cs_enhancements_1;
	/** Interlude between RTT packets, microseconds. */
	uint8_t t_ip1_time_us;
	/** Interlude between CS tones, microseconds. */
	uint8_t t_ip2_time_us;
	/** Frequency change period, microseconds. */
	uint8_t t_fcs_time_us;
	/** Tone phase measurement period, microseconds. */
	uint8_t t_pm_time_us;
	/** CS channel map, byte 0 first; bit n represents 2402 + n MHz. */
	uint8_t channel_map[CS_CONFIG_CHANNEL_MAP_SIZE];
} __attribute__((__packed__));

/**
 * @brief Byte-packed CS procedure enable complete record (31 bytes).
 *
 * Field meanings follow struct bt_conn_le_cs_procedure_enable_complete. The
 * multi-byte fields are grouped directly after the header. With @c state
 * @ref CS_RESULT_PROCEDURES_DISABLED only @c config_id and @c state are
 * meaningful; the other procedure fields are zero.
 */
struct cs_procedure_enable_complete {
	/** Always @ref CS_RESULT_TYPE_PROCEDURE_ENABLE_COMPLETE. */
	uint8_t type;
	/** Total record size in bytes; always sizeof(struct cs_procedure_enable_complete). */
	uint8_t size;
	/** Zephyr connection index from bt_conn_index(). */
	uint8_t conn_index;
	/** HCI status of the event; 0 on success. */
	uint8_t status;
	/** GRTC time the event was captured, in microseconds. */
	uint64_t timestamp_us;

	/** Duration of each subevent, microseconds. */
	uint32_t subevent_len;
	/** Time between subevents in one CS event, 0.625 ms units. */
	uint16_t subevent_interval;
	/** ACL events between consecutive CS event anchor points. */
	uint16_t event_interval;
	/** ACL events between consecutive CS procedure anchor points. */
	uint16_t procedure_interval;
	/** Procedures scheduled; 0 means until disabled. */
	uint16_t procedure_count;
	/** Maximum procedure duration, 0.625 ms units. */
	uint16_t max_procedure_len;

	/** CS configuration ID (0-3). */
	uint8_t config_id;
	/** Procedure state, one of @ref cs_result_procedure_state. */
	uint8_t state;
	/** Tone antenna configuration index, one of @ref cs_config_tone_antenna. */
	uint8_t tone_antenna_config_selection;
	/** Selected TX power in dBm, or @ref CS_RESULT_TX_POWER_UNAVAILABLE. */
	int8_t selected_tx_power;
	/** Subevents anchored off the same ACL connection event (1-32). */
	uint8_t subevents_per_event;
} __attribute__((__packed__));

_Static_assert(sizeof(struct cs_config_complete) == 40U, "cs_config_complete must be packed");
_Static_assert(sizeof(struct cs_procedure_enable_complete) == 31U,
               "cs_procedure_enable_complete must be packed");

/**
 * @brief Pack a CS configuration complete event into a record.
 *
 * @param[out] dst Record to fill. Fully overwritten on success; untouched on error.
 * @param[in] conn Connection the event was received on. Not retained.
 * @param[in] status HCI status passed to le_cs_config_complete.
 * @param[in] src Configuration passed to the callback. May be NULL only when
 *                @p status is non-zero; it is ignored in that case.
 * @param[in] timestamp_us Capture time in microseconds, or 0 to sample the GRTC now.
 * @retval 0 Record packed.
 * @retval -EINVAL @p dst or @p conn is NULL, or @p src is NULL with a zero @p status.
 * @note Call from the callback while @p src is still valid. Issues no Bluetooth operations.
 */
int cs_config_complete_pack(struct cs_config_complete *dst,
                            const struct bt_conn *conn,
                            uint8_t status,
                            const struct bt_conn_le_cs_config *src,
                            uint64_t timestamp_us);

/**
 * @brief Pack a CS procedure enable complete event into a record.
 *
 * @param[out] dst Record to fill. Fully overwritten on success; untouched on error.
 * @param[in] conn Connection the event was received on. Not retained.
 * @param[in] status HCI status passed to le_cs_procedure_enable_complete.
 * @param[in] src Parameters passed to the callback. May be NULL only when
 *                @p status is non-zero; it is ignored in that case.
 * @param[in] timestamp_us Capture time in microseconds, or 0 to sample the GRTC now.
 * @retval 0 Record packed. A disable event keeps only @c config_id and @c state.
 * @retval -EINVAL @p dst or @p conn is NULL, or @p src is NULL with a zero @p status.
 * @note Call from the callback while @p src is still valid. Issues no Bluetooth operations.
 */
int cs_procedure_enable_complete_pack(struct cs_procedure_enable_complete *dst,
                                      const struct bt_conn *conn,
                                      uint8_t status,
                                      const struct bt_conn_le_cs_procedure_enable_complete *src,
                                      uint64_t timestamp_us);

/** Buffer size that always holds the cs_config_complete_print() output. */
#define CS_CONFIG_COMPLETE_PRINT_SIZE 1024U

/** Buffer size that always holds the cs_procedure_enable_complete_print() output. */
#define CS_PROCEDURE_ENABLE_COMPLETE_PRINT_SIZE 512U

/**
 * @brief Format a configuration complete record as text.
 *
 * Writes the header and, on success, every field with timing units, the raw
 * channel map and the enabled CS channel indices. Lines end in '\n'.
 *
 * @param[out] buf Destination; always NUL-terminated when @p size is non-zero.
 * @param[in] size Capacity of @p buf in bytes. @ref CS_CONFIG_COMPLETE_PRINT_SIZE
 *                 never truncates.
 * @param[in] record Record to describe. Not modified or retained.
 * @return Characters written, excluding the NUL.
 * @retval -EINVAL @p buf or @p record is NULL, or @p size is zero; no output.
 * @retval -ENOSPC Output did not fit; @p buf holds the truncated prefix.
 * @note Issues no output of its own; the caller decides where the text goes.
 */
int cs_config_complete_print(char *buf, size_t size, const struct cs_config_complete *record);

/**
 * @brief Format a procedure enable complete record as text.
 *
 * Writes the header and, on success, every field with timing and power units.
 *
 * @param[out] buf Destination; always NUL-terminated when @p size is non-zero.
 * @param[in] size Capacity of @p buf in bytes.
 *                 @ref CS_PROCEDURE_ENABLE_COMPLETE_PRINT_SIZE never truncates.
 * @param[in] record Record to describe. Not modified or retained.
 * @return Characters written, excluding the NUL.
 * @retval -EINVAL @p buf or @p record is NULL, or @p size is zero; no output.
 * @retval -ENOSPC Output did not fit; @p buf holds the truncated prefix.
 */
int cs_procedure_enable_complete_print(char *buf, size_t size,
                                       const struct cs_procedure_enable_complete *record);

/** @} */

#ifdef __cplusplus
}
#endif

#endif /* CS_RESULTS_H_ */
