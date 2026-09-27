/* SPDX-License-Identifier: MIT */
/**
 * @file cs_capabilities.h
 * @brief Pack local and remote CS capabilities into byte-packed records.
 */
#ifndef CS_CAPABILITIES_H_
#define CS_CAPABILITIES_H_

#include <stddef.h>
#include <stdint.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/cs.h>
#include <zephyr/toolchain.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @defgroup cs_capabilities_api CS capabilities
 * @brief Capture local or remote CS capabilities as one byte-packed record.
 *
 * Zephyr reports capabilities as struct bt_conn_le_cs_capabilities, whose
 * layout mixes bool, enum and multi-byte fields and is not a stable wire
 * format. @ref cs_capabilities carries the same information in a byte-packed
 * record for transmission over a serial link, following the conventions of
 * the cs_reports records:
 *
 * - The first two bytes are @c source and @c size, so a reader can identify
 *   and skip the record without knowing the rest of its layout.
 * - Every field is a whole, byte-aligned integer. Booleans become uint8_t
 *   values of 0 or 1 and enums become their uint8_t encodings.
 * - The record is written field by field, never overlaid on HCI data.
 * - @c timestamp_us uses the same GRTC time base as step records, see
 *   cs_subevent_timestamp_us().
 *
 * Multi-byte fields are host-endian. On the little-endian nRF targets this is
 * little-endian on the wire.
 *
 * @par Usage
 * @code{.c}
 * struct cs_capabilities caps;
 *
 * // Local controller, typically once after bt_enable().
 * int err = cs_capabilities_read_local(&caps);
 * if (!err) {
 *     transmit(&caps, caps.size);
 * }
 *
 * // Remote peer, from the capability exchange callback.
 * static void remote_capabilities_cb(struct bt_conn *conn, uint8_t status,
 *                                    struct bt_conn_le_cs_capabilities *params)
 * {
 *     struct cs_capabilities remote;
 *
 *     if (status == 0 && cs_capabilities_pack(&remote, conn, params, 0) == 0) {
 *         transmit(&remote, remote.size);
 *     }
 * }
 * @endcode
 * @{
 */

/** Whose capabilities a @ref cs_capabilities record describes. */
enum cs_capabilities_source {
	/** The local controller. @c conn_index is @ref CS_CAPABILITIES_CONN_NONE. */
	CS_CAPABILITIES_SOURCE_LOCAL = 0x00,
	/** The remote peer on the connection named by @c conn_index. */
	CS_CAPABILITIES_SOURCE_REMOTE = 0x01,
};

/** @c conn_index value of a record that belongs to no connection. */
#define CS_CAPABILITIES_CONN_NONE 0xFFU

/**
 * @brief Byte-packed CS capabilities record.
 *
 * Field meanings and encodings follow struct bt_conn_le_cs_capabilities. The
 * multi-byte fields are grouped directly after the header so each sits on an
 * even offset; the single-byte fields follow.
 */
struct cs_capabilities {
	/** Whose capabilities these are, one of @ref cs_capabilities_source. */
	uint8_t source;
	/** Total record size in bytes; always sizeof(struct cs_capabilities). */
	uint8_t size;
	/**
	 * Zephyr connection index from bt_conn_index() for a remote record, or
	 * @ref CS_CAPABILITIES_CONN_NONE for a local one.
	 */
	uint8_t conn_index;
	/** Reserved for future use; written as zero. */
	uint8_t reserved;
	/** GRTC time the capabilities were captured, in microseconds. */
	uint64_t timestamp_us;

	/**
	 * Maximum consecutive CS procedures. Zero means both fixed and indefinite
	 * procedure counts are supported.
	 */
	uint16_t max_consecutive_procedures_supported;
	/** Optional T_IP1 durations, bits 0-6: 10, 20, 30, 40, 50, 60, 80 us. */
	uint16_t t_ip1_times_supported;
	/** Optional T_IP2 durations, bits 0-6: 10, 20, 30, 40, 50, 60, 80 us. */
	uint16_t t_ip2_times_supported;
	/** Optional T_FCS durations, bits 0-8: 15, 20, 30, 40, 50, 60, 80, 100, 120 us. */
	uint16_t t_fcs_times_supported;
	/** Optional T_PM durations, bits 0-1: 10, 20 us. */
	uint16_t t_pm_times_supported;
	/** T_IP2 durations supported with IPT, bits 0-6: 10, 20, 30, 40, 50, 60, 80 us. */
	uint16_t t_ip2_ipt_times_supported;

	/** Number of CS configurations supported. */
	uint8_t num_config_supported;
	/** Number of antennas supported. */
	uint8_t num_antennas_supported;
	/** Maximum number of antenna paths supported. */
	uint8_t max_antenna_paths_supported;
	/** 1 when the initiator role is supported. */
	uint8_t initiator_supported;
	/** 1 when the reflector role is supported. */
	uint8_t reflector_supported;
	/** 1 when mode 3 is supported. */
	uint8_t mode_3_supported;
	/** RTT AA-only precision, enum bt_conn_le_cs_capability_rtt_aa_only. */
	uint8_t rtt_aa_only_precision;
	/** RTT sounding precision, enum bt_conn_le_cs_capability_rtt_sounding. */
	uint8_t rtt_sounding_precision;
	/** RTT random payload precision, enum bt_conn_le_cs_capability_rtt_random_payload. */
	uint8_t rtt_random_payload_precision;
	/** CS steps needed for RTT AA-only accuracy; 0 when unsupported. */
	uint8_t rtt_aa_only_n;
	/** CS steps needed for RTT sounding accuracy; 0 when unsupported. */
	uint8_t rtt_sounding_n;
	/** CS steps needed for RTT random payload accuracy; 0 when unsupported. */
	uint8_t rtt_random_payload_n;
	/** 1 when phase-based NADM is supported for a sounding-sequence CS_SYNC. */
	uint8_t phase_based_nadm_sounding_supported;
	/** 1 when phase-based NADM is supported for a random-sequence CS_SYNC. */
	uint8_t phase_based_nadm_random_supported;
	/** 1 when CS_SYNC on LE 2M PHY is supported. */
	uint8_t cs_sync_2m_phy_supported;
	/** 1 when CS_SYNC on LE 2M 2BT PHY is supported. */
	uint8_t cs_sync_2m_2bt_phy_supported;
	/** 1 when CS without frequency actuation error is supported. */
	uint8_t cs_without_fae_supported;
	/** 1 when channel selection algorithm #3c is supported. */
	uint8_t chsel_alg_3c_supported;
	/** 1 when phase-based ranging from an RTT sounding sequence is supported. */
	uint8_t pbr_from_rtt_sounding_seq_supported;
	/** 1 when IPT in the CS reflector is supported. */
	uint8_t cs_ipt_reflector_supported;
	/** Antenna switch period of the CS tones, in microseconds. */
	uint8_t t_sw_time;
	/** Supported RTT SNR levels, bits 0-4: 18, 21, 24, 27, 30 dB. */
	uint8_t tx_snr_capability;
	/** Antenna switch period of the CS tones during IPT: 0, 1, 2, 4 or 10 us. */
	uint8_t t_sw_ipt_time_supported;
} __attribute__((__packed__));

/**
 * @brief Pack Zephyr CS capabilities into a byte-packed record.
 *
 * Copies every field of @p src into @p dst, converting booleans to 0 or 1 and
 * enums to their uint8_t encodings, and fills the record header.
 *
 * @param[out] dst Record to fill. Fully overwritten on success; untouched on
 *                 error.
 * @param[in] conn Connection the capabilities were received on, or NULL for
 *                 the local controller. Selects @c source and @c conn_index;
 *                 not retained.
 * @param[in] src Capabilities from Zephyr, e.g. the le_cs_read_remote_capabilities_complete
 *                callback parameters or bt_le_cs_read_local_supported_capabilities().
 *                Not modified or retained.
 * @param[in] timestamp_us Capture time in microseconds, or 0 to sample the
 *                         GRTC now.
 * @retval 0 Record packed.
 * @retval -EINVAL @p dst or @p src is NULL.
 * @note Call from the remote capabilities callback only when its status is 0,
 *       while @p src is still valid.
 * @note Issues no Bluetooth operations.
 */
int cs_capabilities_pack(struct cs_capabilities *dst,
                         const struct bt_conn *conn,
                         const struct bt_conn_le_cs_capabilities *src,
                         uint64_t timestamp_us);

/**
 * @brief Read the local controller's CS capabilities into a packed record.
 *
 * Issues HCI LE CS Read Local Supported Capabilities V2 and falls back to V1
 * when the controller rejects V2. V1 does not report IPT support, so after a
 * fallback @c cs_ipt_reflector_supported, @c t_ip2_ipt_times_supported and
 * @c t_sw_ipt_time_supported read as zero.
 *
 * @param[out] dst Record to fill. Fully overwritten on success; untouched on
 *                 error.
 * @retval 0 Capabilities read and packed; @c source is local.
 * @retval -EINVAL @p dst is NULL.
 * @retval -EIO The controller returned a non-zero HCI status.
 * @retval <0 Other negative errno from the HCI command.
 * @note Requires Bluetooth to be enabled. Blocks on a synchronous HCI command,
 *       so do not call from the Bluetooth RX thread or a callback it runs.
 */
int cs_capabilities_read_local(struct cs_capabilities *dst);

/** Buffer size that always holds the cs_capabilities_print() output. */
#define CS_CAPABILITIES_PRINT_SIZE 1024U

/**
 * @brief Format a packed CS capabilities record as text.
 *
 * Writes the header and every capability field. Enum and bitmask fields are
 * written as their raw encodings. Lines end in '\n'.
 *
 * @param[out] buf Destination; always NUL-terminated when @p size is non-zero.
 * @param[in] size Capacity of @p buf in bytes. @ref CS_CAPABILITIES_PRINT_SIZE
 *                 never truncates.
 * @param[in] caps Record to describe. Not modified or retained.
 * @return Characters written, excluding the NUL.
 * @retval -EINVAL @p buf or the record is NULL, or @p size is zero; no output.
 * @retval -ENOSPC Output did not fit; @p buf holds the truncated prefix.
 * @note Issues no output of its own; the caller decides where the text goes.
 */
int cs_capabilities_print(char *buf, size_t size, const struct cs_capabilities *caps);

/** @} */

#ifdef __cplusplus
}
#endif

#endif /* CS_CAPABILITIES_H_ */
