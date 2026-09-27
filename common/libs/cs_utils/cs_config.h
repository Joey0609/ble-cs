/* SPDX-License-Identifier: MIT */
/**
 * @file cs_config.h
 * @brief Caller-owned, byte-packed configuration records for connected CS endpoints.
 */
#ifndef CS_CONFIG_H_
#define CS_CONFIG_H_

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Only referenced through pointers; no Zephyr header is needed by users. */
struct bt_conn;

/**
 * @defgroup cs_config CS endpoint configuration
 * @brief Defaults, setters and apply helpers for reflector and initiator records.
 *
 * The configuration records are self-contained and byte-packed. Every field is
 * a fixed-width integer holding the HCI encoding of its setting; no bool, enum
 * or Zephyr type appears in a record, so a record can be stored or sent over a
 * serial link as raw bytes. The records follow the cs_capabilities conventions:
 *
 * - The first two bytes are @c role and @c size, so a reader can identify and
 *   skip the record without knowing the rest of its layout.
 * - Multi-byte fields are host-endian. On the little-endian nRF targets this is
 *   little-endian on the wire.
 * - Values implied by the record itself are not stored: the local role flags
 *   of the default settings, the creation role, and the configuration ID of
 *   the procedure and creation parameters are derived from @c role and
 *   @c config_id when a record is applied.
 *
 * Each endpoint owns one record. Initialize it with the matching get_default
 * function, then update it through its role-specific setters or by writing
 * fields directly. Inputs are copied; the library retains no input pointers and
 * allocates no memory. Callers must serialize concurrent access to one record.
 *
 * Default generators and setters only manage data. The apply functions build
 * the corresponding Zephyr parameter structures from the stored fields and
 * issue the Bluetooth/CS operations. They do not start CS security or enable
 * procedures; applications own those operations and completion callbacks.
 *
 * @note Settings are requests, not negotiated controller results. Validation
 *       is limited to the checks documented by each setter; direct field writes
 *       bypass them. Encoded values are cast to the Zephyr enums when applied.
 *
 * @par Reflector usage
 * @code{.c}
 * struct cs_reflector_config reflector;
 * int err = cs_reflector_config_get_default(&reflector);
 * if (err) {
 *     return err;
 * }
 * err = cs_reflector_config_set_config_id(&reflector, 1);
 * if (err) {
 *     return err;
 * }
 * err = cs_reflector_config_apply_default_settings(&reflector, conn);
 * @endcode
 *
 * @par Initiator usage
 * @code{.c}
 * struct cs_initiator_config initiator;
 * int err = cs_initiator_config_get_default(&initiator);
 * if (err) {
 *     return err;
 * }
 * initiator.creation.rtt_type = CS_CONFIG_RTT_TYPE_32_BIT_SOUNDING;
 * err = cs_initiator_config_set_config_id(&initiator, 1);
 * if (err) {
 *     return err;
 * }
 * // Apply the stored settings at the appropriate connection lifecycle stage.
 * @endcode
 * @{
 */

/** Local CS role of a record; values match enum bt_conn_le_cs_role. */
enum cs_config_role {
	CS_CONFIG_ROLE_INITIATOR = 0x00,
	CS_CONFIG_ROLE_REFLECTOR = 0x01,
};

/** Highest valid CS configuration ID. */
#define CS_CONFIG_ID_MAX 3U

/** Highest allowed CS maximum TX power, in dBm. */
#define CS_CONFIG_MAX_TX_POWER_MAX 20
/** Lowest allowed CS maximum TX power, in dBm. */
#define CS_CONFIG_MAX_TX_POWER_MIN (-127)

/** @c cs_sync_antenna_selection encodings. */
enum cs_config_sync_antenna {
	CS_CONFIG_SYNC_ANTENNA_ONE = 0x01,
	CS_CONFIG_SYNC_ANTENNA_TWO = 0x02,
	CS_CONFIG_SYNC_ANTENNA_THREE = 0x03,
	CS_CONFIG_SYNC_ANTENNA_FOUR = 0x04,
	CS_CONFIG_SYNC_ANTENNA_REPETITIVE = 0xFE,
	CS_CONFIG_SYNC_ANTENNA_NO_RECOMMENDATION = 0xFF,
};

/** @c tone_antenna_config_selection encodings (antenna configuration index). */
enum cs_config_tone_antenna {
	CS_CONFIG_TONE_ANTENNA_A1_B1 = 0x00,
	CS_CONFIG_TONE_ANTENNA_A2_B1 = 0x01,
	CS_CONFIG_TONE_ANTENNA_A3_B1 = 0x02,
	CS_CONFIG_TONE_ANTENNA_A4_B1 = 0x03,
	CS_CONFIG_TONE_ANTENNA_A1_B2 = 0x04,
	CS_CONFIG_TONE_ANTENNA_A1_B3 = 0x05,
	CS_CONFIG_TONE_ANTENNA_A1_B4 = 0x06,
	CS_CONFIG_TONE_ANTENNA_A2_B2 = 0x07,
};

/** Procedure @c phy encodings. */
enum cs_config_procedure_phy {
	CS_CONFIG_PROCEDURE_PHY_1M = 0x01,
	CS_CONFIG_PROCEDURE_PHY_2M = 0x02,
	CS_CONFIG_PROCEDURE_PHY_CODED_S8 = 0x03,
	CS_CONFIG_PROCEDURE_PHY_CODED_S2 = 0x04,
};

/** @c preferred_peer_antenna bits. */
enum cs_config_peer_antenna {
	CS_CONFIG_PEER_ANTENNA_1 = 0x01,
	CS_CONFIG_PEER_ANTENNA_2 = 0x02,
	CS_CONFIG_PEER_ANTENNA_3 = 0x04,
	CS_CONFIG_PEER_ANTENNA_4 = 0x08,
};

/** @c tx_power_delta value requesting no recommendation. */
#define CS_CONFIG_TX_POWER_DELTA_NONE INT8_MIN

/** SNR control encodings. */
enum cs_config_snr_control {
	CS_CONFIG_SNR_CONTROL_18DB = 0x00,
	CS_CONFIG_SNR_CONTROL_21DB = 0x01,
	CS_CONFIG_SNR_CONTROL_24DB = 0x02,
	CS_CONFIG_SNR_CONTROL_27DB = 0x03,
	CS_CONFIG_SNR_CONTROL_30DB = 0x04,
	CS_CONFIG_SNR_CONTROL_NOT_USED = 0xFF,
};

/** Creation @c mode encodings: main mode in bits 0-3, sub-mode in bits 4-7. */
enum cs_config_mode {
	CS_CONFIG_MODE_1 = 0x01,
	CS_CONFIG_MODE_2 = 0x02,
	CS_CONFIG_MODE_3 = 0x03,
	CS_CONFIG_MODE_2_SUB_MODE_1 = 0x12,
	CS_CONFIG_MODE_2_SUB_MODE_3 = 0x32,
	CS_CONFIG_MODE_3_SUB_MODE_2 = 0x23,
};

/** Creation @c rtt_type encodings. */
enum cs_config_rtt_type {
	CS_CONFIG_RTT_TYPE_AA_ONLY = 0x00,
	CS_CONFIG_RTT_TYPE_32_BIT_SOUNDING = 0x01,
	CS_CONFIG_RTT_TYPE_96_BIT_SOUNDING = 0x02,
	CS_CONFIG_RTT_TYPE_32_BIT_RANDOM = 0x03,
	CS_CONFIG_RTT_TYPE_64_BIT_RANDOM = 0x04,
	CS_CONFIG_RTT_TYPE_96_BIT_RANDOM = 0x05,
	CS_CONFIG_RTT_TYPE_128_BIT_RANDOM = 0x06,
};

/** Creation @c cs_sync_phy encodings. */
enum cs_config_sync_phy {
	CS_CONFIG_SYNC_PHY_1M = 0x01,
	CS_CONFIG_SYNC_PHY_2M = 0x02,
	CS_CONFIG_SYNC_PHY_2M_2BT = 0x03,
};

/** Creation @c channel_selection_type encodings. */
enum cs_config_chsel_type {
	CS_CONFIG_CHSEL_TYPE_3B = 0x00,
	CS_CONFIG_CHSEL_TYPE_3C = 0x01,
};

/** Creation @c ch3c_shape encodings. */
enum cs_config_ch3c_shape {
	CS_CONFIG_CH3C_SHAPE_HAT = 0x00,
	CS_CONFIG_CH3C_SHAPE_X = 0x01,
};

/** Creation @c cs_enhancements_1 bit 0: IPT in the CS reflector. */
#define CS_CONFIG_ENHANCEMENTS_1_IPT 0x01U

/**
 * Initiator @c peer_data encodings: the data the initiator receives from the
 * reflector.
 */
enum cs_config_peer_data {
	/** Reflector subevents through RAS real-time ranging data (default). */
	CS_CONFIG_PEER_DATA_RAS_REALTIME = 0x00,
	/**
	 * None: initiator subevents only, without RAS. Requires IPT
	 * (@ref CS_CONFIG_ENHANCEMENTS_1_IPT), with which the initiator's phase
	 * correction terms carry the full two-way phase.
	 */
	CS_CONFIG_PEER_DATA_NONE = 0x01,
};

/**
 * Initiator @c t_pm_us values: the preferred phase measurement period T_PM in
 * microseconds. The controller uses it at LE CS Create Config when both devices
 * support it, otherwise a T_PM both support; configuration complete reports
 * the one in use.
 */
enum cs_config_t_pm {
	/** 10 us (default). */
	CS_CONFIG_T_PM_10_US = 10,
	/** 20 us. */
	CS_CONFIG_T_PM_20_US = 20,
	/** 40 us, mandatory for every CS device. */
	CS_CONFIG_T_PM_40_US = 40,
};

/** Creation @c context encodings; values match enum bt_le_cs_create_config_context. */
enum cs_config_creation_context {
	/** Write the configuration in the local controller only. */
	CS_CONFIG_CREATION_CONTEXT_LOCAL_ONLY = 0x00,
	/** Write the configuration locally and in the peer via configuration exchange. */
	CS_CONFIG_CREATION_CONTEXT_LOCAL_AND_REMOTE = 0x01,
};

/** Number of bytes in a CS channel map. */
#define CS_CONFIG_CHANNEL_MAP_SIZE 10U

/**
 * @brief Requested ACL connection parameters (8 bytes).
 * Independent of the local CS role.
 */
struct cs_config_connection {
	/** Minimum connection interval, 1.25 ms units. */
	uint16_t interval_min;
	/** Maximum connection interval, 1.25 ms units. */
	uint16_t interval_max;
	/** Peripheral latency, ACL events. */
	uint16_t latency;
	/** Supervision timeout, 10 ms units. */
	uint16_t timeout;
} __attribute__((__packed__));

/**
 * @brief Local CS default settings (2 bytes).
 * The role enable flags are derived from the owning record's @c role.
 */
struct cs_config_default_settings {
	/** CS_SYNC antenna, one of @ref cs_config_sync_antenna. */
	uint8_t cs_sync_antenna_selection;
	/** Maximum TX power (EIRP) in dBm. */
	int8_t max_tx_power;
} __attribute__((__packed__));

/**
 * @brief Requested CS procedure parameters (22 bytes).
 * The configuration ID is the owning record's @c config_id.
 */
struct cs_config_procedure {
	/** Maximum procedure duration, 0.625 ms units. */
	uint16_t max_procedure_len;
	/** Minimum ACL events between consecutive procedures. */
	uint16_t min_procedure_interval;
	/** Maximum ACL events between consecutive procedures. */
	uint16_t max_procedure_interval;
	/** Maximum number of procedures; 0 requests no limit. */
	uint16_t max_procedure_count;
	/** Minimum suggested subevent length, microseconds. */
	uint32_t min_subevent_len;
	/** Maximum suggested subevent length, microseconds. */
	uint32_t max_subevent_len;
	/** Tone antenna configuration index, one of @ref cs_config_tone_antenna. */
	uint8_t tone_antenna_config_selection;
	/** Procedure PHY, one of @ref cs_config_procedure_phy. */
	uint8_t phy;
	/** Recommended TX power delta in dB, or @ref CS_CONFIG_TX_POWER_DELTA_NONE. */
	int8_t tx_power_delta;
	/** Preferred peer antennas, bitmask of @ref cs_config_peer_antenna. */
	uint8_t preferred_peer_antenna;
	/** Initiator SNR control, one of @ref cs_config_snr_control. */
	uint8_t snr_control_initiator;
	/** Reflector SNR control, one of @ref cs_config_snr_control. */
	uint8_t snr_control_reflector;
} __attribute__((__packed__));

/**
 * @brief Shared CS configuration created by the initiator (23 bytes).
 * The configuration ID is the owning record's @c config_id; the role is always
 * initiator.
 */
struct cs_config_creation {
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
	/** RTT type, one of @ref cs_config_rtt_type. */
	uint8_t rtt_type;
	/** CS_SYNC PHY, one of @ref cs_config_sync_phy. */
	uint8_t cs_sync_phy;
	/**
	 * CS channel map, byte 0 first. Bit n represents 2402 + n MHz; this is a
	 * CS frequency index, not a BLE ACL channel index.
	 */
	uint8_t channel_map[CS_CONFIG_CHANNEL_MAP_SIZE];
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
	/** Creation destination, one of @ref cs_config_creation_context. */
	uint8_t context;
} __attribute__((__packed__));

/**
 * @brief Requested local settings for one connected CS reflector (36 bytes).
 *
 * Initialize with @ref cs_reflector_config_get_default. The connected peer
 * supplies the shared measurement/channel configuration through CS exchange;
 * this record stores the reflector's local connection and CS settings.
 */
struct cs_reflector_config {
	/** Always @ref CS_CONFIG_ROLE_REFLECTOR. */
	uint8_t role;
	/** Total record size in bytes; always sizeof(struct cs_reflector_config). */
	uint8_t size;
	/** CS configuration ID (0-3) supplied by the peer. */
	uint8_t config_id;
	/** Reserved for future use; written as zero. */
	uint8_t reserved;
	/** Requested ACL connection parameters. */
	struct cs_config_connection connection;
	/** Local CS antenna and power settings. */
	struct cs_config_default_settings defaults;
	/** Requested CS procedure parameters. */
	struct cs_config_procedure procedure;
} __attribute__((__packed__));

/**
 * @brief Requested local and shared settings for one connected CS initiator (60 bytes).
 *
 * Initialize with @ref cs_initiator_config_get_default.
 */
struct cs_initiator_config {
	/** Always @ref CS_CONFIG_ROLE_INITIATOR. */
	uint8_t role;
	/** Total record size in bytes; always sizeof(struct cs_initiator_config). */
	uint8_t size;
	/** CS configuration ID (0-3) used for both creation and procedure parameters. */
	uint8_t config_id;
	/**
	 * Data received from the reflector, one of @ref cs_config_peer_data. Zero
	 * (RAS real-time) in records written before the field existed.
	 */
	uint8_t peer_data;
	/** Requested ACL connection parameters. */
	struct cs_config_connection connection;
	/** Local CS antenna and power settings. */
	struct cs_config_default_settings defaults;
	/** Requested CS procedure parameters. */
	struct cs_config_procedure procedure;
	/** Shared measurement modes, RTT, sync PHY, steps, channels and context. */
	struct cs_config_creation creation;
	/** Preferred T_PM, one of @ref cs_config_t_pm. */
	uint8_t t_pm_us;
} __attribute__((__packed__));

_Static_assert(sizeof(struct cs_config_connection) == 8U, "cs_config_connection must be packed");
_Static_assert(sizeof(struct cs_config_default_settings) == 2U, "cs_config_default_settings must be packed");
_Static_assert(sizeof(struct cs_config_procedure) == 22U, "cs_config_procedure must be packed");
_Static_assert(sizeof(struct cs_config_creation) == 23U, "cs_config_creation must be packed");
_Static_assert(sizeof(struct cs_reflector_config) == 36U, "cs_reflector_config must be packed");
_Static_assert(sizeof(struct cs_initiator_config) == 60U, "cs_initiator_config must be packed");

/**
 * @brief Initialize or reset a reflector configuration record.
 *
 * Fills the header (reflector role, record size, ID 0) and resets all fields to
 * a 7.5 ms ACL interval, latency 0, supervision timeout 4 s, repetitive sync
 * antenna selection and the maximum allowed CS TX power. Procedure defaults
 * select maximum duration 6.25 ms, intervals of 1-4 ACL events, unlimited
 * procedures, 6 ms subevents, A1:B1 tone antennas, 1M procedure PHY, no TX
 * power delta recommendation, preferred peer antenna 1, and unused SNR
 * controls for both endpoints.
 *
 * @param[out] config Caller-owned record to initialize; need not be initialized.
 * @retval 0 All fields reset to defaults.
 * @retval -EINVAL @p config is NULL.
 * @note Reinitializing an existing record discards all previous overrides.
 */
int cs_reflector_config_get_default(struct cs_reflector_config *config);

/**
 * @brief Replace this reflector's requested ACL connection parameters.
 *
 * Requires 6 <= interval_min <= interval_max <= 3200 (1.25 ms units),
 * latency <= 499 events and timeout in 10-3200 (10 ms units). The timeout
 * must be strictly greater than twice the maximum interval multiplied by
 * (latency + 1); in encoded units, timeout * 4 > interval_max * (latency + 1).
 *
 * @param[in,out] config Initialized reflector record to update.
 * @param[in] connection Parameters to copy; no pointer is retained.
 * @retval 0 Connection parameters replaced.
 * @retval -EINVAL An argument is NULL or an ACL constraint above is violated.
 * @note The record remains unchanged on failure. No ACL update is sent.
 */
int cs_reflector_config_set_connection(struct cs_reflector_config *config,
                                       const struct cs_config_connection *connection);

/**
 * @brief Replace this reflector's local CS antenna and power settings.
 *
 * Requires max_tx_power in @ref CS_CONFIG_MAX_TX_POWER_MIN to
 * @ref CS_CONFIG_MAX_TX_POWER_MAX. The antenna selection is copied without
 * controller capability validation.
 *
 * @param[in,out] config Initialized reflector record to update.
 * @param[in] settings Local default settings to copy; no pointer is retained.
 * @retval 0 Settings replaced.
 * @retval -EINVAL An argument is NULL or max_tx_power is out of range.
 * @note The record remains unchanged on failure.
 */
int cs_reflector_config_set_default_settings(struct cs_reflector_config *config,
                                             const struct cs_config_default_settings *settings);

/**
 * @brief Replace this reflector's requested CS procedure parameters.
 *
 * All fields are copied as supplied. @c tone_antenna_config_selection must be a
 * defined configuration, and @c preferred_peer_antenna a non-zero mask of peer
 * antennas 1-4 with at least as many bits set as the configuration's peer
 * antennas (A, the initiator's side). Other timing, antenna, PHY, power and SNR
 * compatibility remain the application's and controller's responsibility.
 * The configuration ID is set separately with @ref cs_reflector_config_set_config_id.
 *
 * @param[in,out] config Initialized reflector record to update.
 * @param[in] procedure Procedure parameters to copy; no pointer is retained.
 * @retval 0 Procedure parameters replaced.
 * @retval -EINVAL An argument is NULL, or the antenna selections are invalid.
 */
int cs_reflector_config_set_procedure(struct cs_reflector_config *config,
                                      const struct cs_config_procedure *procedure);

/**
 * @brief Select this reflector's CS configuration ID.
 *
 * Identifies a configuration supplied by the peer. This does not create or
 * remove a controller configuration.
 *
 * @param[in,out] config Initialized reflector record to update.
 * @param[in] id CS configuration ID, from 0 through @ref CS_CONFIG_ID_MAX.
 * @retval 0 Configuration ID updated.
 * @retval -EINVAL @p config is NULL or @p id exceeds @ref CS_CONFIG_ID_MAX.
 * @note The record remains unchanged on failure.
 */
int cs_reflector_config_set_config_id(struct cs_reflector_config *config,
                                      uint8_t id);

/**
 * @brief Initialize or reset an initiator configuration record.
 *
 * Fills the header (initiator role, record size, ID 0) and resets connection,
 * default and procedure settings to the baseline documented in
 * @ref cs_reflector_config_get_default. Creation defaults select main mode
 * 2/submode 1, 2-10 main-mode steps, no main-mode repetition, one mode-0 step,
 * AA-only RTT, 1M sync PHY, channels 26-61, one channel-map repetition and
 * channel selection 3b. Inactive 3c fields use hat shape and jump 2;
 * enhancements are zero. The creation context is local-and-remote. Reflector
 * data is RAS real-time.
 *
 * @param[out] config Caller-owned record to initialize; need not be initialized.
 * @retval 0 All fields reset to defaults.
 * @retval -EINVAL @p config is NULL.
 * @note Reinitializing an existing record discards all previous overrides.
 */
int cs_initiator_config_get_default(struct cs_initiator_config *config);

/**
 * @brief Replace this initiator's requested ACL connection parameters.
 *
 * Applies the checks documented in @ref cs_reflector_config_set_connection.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @param[in] connection Parameters to copy; no pointer is retained.
 * @retval 0 Connection parameters replaced.
 * @retval -EINVAL An argument is NULL or an ACL constraint is violated.
 * @note The record remains unchanged on failure. No ACL update is sent.
 */
int cs_initiator_config_set_connection(struct cs_initiator_config *config,
                                       const struct cs_config_connection *connection);

/**
 * @brief Replace this initiator's local CS antenna and power settings.
 *
 * Applies the checks documented in @ref cs_reflector_config_set_default_settings.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @param[in] settings Local default settings to copy; no pointer is retained.
 * @retval 0 Settings replaced.
 * @retval -EINVAL An argument is NULL or max_tx_power is out of range.
 * @note The record remains unchanged on failure.
 */
int cs_initiator_config_set_default_settings(struct cs_initiator_config *config,
                                             const struct cs_config_default_settings *settings);

/**
 * @brief Replace this initiator's requested CS procedure parameters.
 *
 * All fields are copied as supplied. @c tone_antenna_config_selection must be a
 * defined configuration, and @c preferred_peer_antenna a non-zero mask of peer
 * antennas 1-4 with at least as many bits set as the configuration's peer
 * antennas (B, the reflector's side). Other timing, antenna, PHY, power and SNR
 * compatibility remain the application's and controller's responsibility.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @param[in] procedure Procedure parameters to copy; no pointer is retained.
 * @retval 0 Procedure parameters replaced.
 * @retval -EINVAL An argument is NULL, or the antenna selections are invalid.
 */
int cs_initiator_config_set_procedure(struct cs_initiator_config *config,
                                      const struct cs_config_procedure *procedure);

/**
 * @brief Select this initiator's CS configuration ID.
 *
 * The single stored ID is used for both configuration creation and procedure
 * parameters. This does not create or remove a controller configuration.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @param[in] id CS configuration ID, from 0 through @ref CS_CONFIG_ID_MAX.
 * @retval 0 Configuration ID updated.
 * @retval -EINVAL @p config is NULL or @p id exceeds @ref CS_CONFIG_ID_MAX.
 * @note The record remains unchanged on failure.
 */
int cs_initiator_config_set_config_id(struct cs_initiator_config *config,
                                      uint8_t id);

/**
 * @brief Replace this initiator's shared CS creation parameters.
 *
 * Requires a channel map accepted by @ref cs_initiator_config_set_channel_map
 * and a context accepted by @ref cs_initiator_config_set_creation_context.
 * Other fields, including measurement mode and step policy, are copied without
 * capability or range validation.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @param[in] creation Creation parameters to copy; no pointer is retained.
 * @retval 0 Creation parameters replaced.
 * @retval -EINVAL An argument is NULL, the map is invalid or the context is unsupported.
 * @note The record remains unchanged on failure. No CS creation is sent.
 */
int cs_initiator_config_set_creation(struct cs_initiator_config *config,
                                     const struct cs_config_creation *creation);

/**
 * @brief Request Inline Phase Correction Term Transfer (IPT) in the reflector.
 *
 * Sets @ref CS_CONFIG_ENHANCEMENTS_1_IPT in creation.cs_enhancements_1,
 * preserving all other settings. Apply through
 * @ref cs_initiator_config_apply_creation. The reflector receives this setting
 * through configuration exchange; it has no separate local IPT setter.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @retval 0 IPT requested in the stored creation parameters.
 * @retval -EINVAL @p config is NULL.
 * @note No controller command or capability check is performed. The application
 *       must ensure compatible local/remote capabilities (including the peer's
 *       cs_ipt_reflector support). Nordic controllers require
 *       CONFIG_BT_CTLR_EXTENDED_FEAT_SET=y for CS enhancements.
 */
int cs_initiator_config_enable_ipt(struct cs_initiator_config *config);

/**
 * @brief Clear the IPT request in this initiator's creation parameters.
 *
 * Clears only @ref CS_CONFIG_ENHANCEMENTS_1_IPT. An existing controller
 * configuration is not changed.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @retval 0 Stored IPT request cleared.
 * @retval -EINVAL @p config is NULL.
 */
int cs_initiator_config_disable_ipt(struct cs_initiator_config *config);

/**
 * @brief Replace this initiator's CS channel map.
 *
 * The map must enable at least 15 channels. Bits 0, 1, 23, 24, 25, 77, 78
 * and 79 must be clear. Other creation fields are retained.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @param[in] channel_map Pointer to @ref CS_CONFIG_CHANNEL_MAP_SIZE readable
 *                        bytes. May be the record's own map.
 * @retval 0 Channel map replaced.
 * @retval -EINVAL An argument is NULL, a reserved bit is set or fewer than
 *                 15 channels are enabled.
 * @note The record remains unchanged on failure.
 */
int cs_initiator_config_set_channel_map(struct cs_initiator_config *config,
                                        const uint8_t channel_map[CS_CONFIG_CHANNEL_MAP_SIZE]);

/**
 * @brief Select where the initiator's CS configuration will be created.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @param[in] context One of @ref cs_config_creation_context.
 * @retval 0 Creation context updated.
 * @retval -EINVAL @p config is NULL or @p context is unsupported.
 * @note The record remains unchanged on failure.
 */
int cs_initiator_config_set_creation_context(struct cs_initiator_config *config,
                                             uint8_t context);

/**
 * @brief Select the data the initiator receives from the reflector.
 *
 * @ref CS_CONFIG_PEER_DATA_NONE needs IPT, but the IPT request is not checked
 * here: @ref cs_initiator_config_set_creation and
 * @ref cs_initiator_config_disable_ipt can clear it afterwards. Check the final
 * record with @ref cs_initiator_config_check_peer_data.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @param[in] peer_data One of @ref cs_config_peer_data.
 * @retval 0 Reflector data setting updated.
 * @retval -EINVAL @p config is NULL or @p peer_data is unknown.
 * @note The record remains unchanged on failure.
 */
int cs_initiator_config_set_peer_data(struct cs_initiator_config *config,
                                      uint8_t peer_data);

/**
 * @brief Check the reflector data setting against the IPT request.
 *
 * @param[in] config Initiator record; not modified or retained.
 * @retval 0 RAS real-time, or none with @ref CS_CONFIG_ENHANCEMENTS_1_IPT
 *         set in creation.cs_enhancements_1.
 * @retval -EINVAL @p config is NULL, @c peer_data is unknown, or none is
 *         selected without the IPT request.
 */
int cs_initiator_config_check_peer_data(const struct cs_initiator_config *config);

/**
 * @brief Select the preferred phase measurement period T_PM.
 *
 * The initiator passes it to its controller before LE CS Create Config
 * (vendor command CS Params Set); a peer without support for it gets a T_PM
 * both devices support.
 *
 * @param[in,out] config Initialized initiator record to update.
 * @param[in] t_pm_us One of @ref cs_config_t_pm.
 * @retval 0 T_PM updated.
 * @retval -EINVAL @p config is NULL or @p t_pm_us is not 10, 20 or 40.
 * @note The record remains unchanged on failure.
 */
int cs_initiator_config_set_t_pm(struct cs_initiator_config *config, uint8_t t_pm_us);

/**
 * @brief Request the stored ACL connection parameters for a reflector.
 *
 * Builds struct bt_le_conn_param and submits it through bt_conn_le_param_update().
 * Success means the request was accepted, not that negotiation has completed.
 *
 * @param[in] config Initialized reflector record; not modified or retained.
 * @param[in] conn Valid, connected Bluetooth connection owned by the caller.
 * @retval 0 ACL parameter request accepted.
 * @retval -EINVAL An argument is NULL.
 * @return Other negative error codes are propagated from bt_conn_le_param_update().
 * @note Each apply function is independent; a failure does not roll back
 *       earlier successful apply operations.
 */
int cs_reflector_config_apply_connection(const struct cs_reflector_config *config,
                                         struct bt_conn *conn);

/**
 * @brief Apply the stored local CS defaults for a reflector.
 *
 * Calls bt_le_cs_set_default_settings() with only the reflector role enabled
 * and the stored sync antenna selection and maximum TX power.
 *
 * @param[in] config Initialized reflector record; not modified or retained.
 * @param[in] conn Valid, connected Bluetooth connection owned by the caller.
 * @retval 0 Local CS defaults command completed successfully.
 * @retval -EINVAL An argument is NULL.
 * @return Other negative error codes are propagated from bt_le_cs_set_default_settings().
 */
int cs_reflector_config_apply_default_settings(const struct cs_reflector_config *config,
                                               struct bt_conn *conn);

/**
 * @brief Apply the stored CS procedure parameters for a reflector.
 *
 * Calls bt_le_cs_set_procedure_parameters() with the stored configuration ID
 * and procedure fields. This does not enable or schedule procedures.
 *
 * @param[in] config Initialized reflector record; not modified or retained.
 * @param[in] conn Valid, connected Bluetooth connection owned by the caller.
 * @retval 0 Procedure parameters command completed successfully.
 * @retval -EINVAL An argument is NULL.
 * @return Other negative error codes are propagated from bt_le_cs_set_procedure_parameters().
 */
int cs_reflector_config_apply_procedure(const struct cs_reflector_config *config,
                                        struct bt_conn *conn);

/**
 * @brief Request the stored ACL connection parameters for an initiator.
 * @see cs_reflector_config_apply_connection
 */
int cs_initiator_config_apply_connection(const struct cs_initiator_config *config,
                                         struct bt_conn *conn);

/**
 * @brief Apply the stored local CS defaults for an initiator.
 *
 * Calls bt_le_cs_set_default_settings() with only the initiator role enabled.
 * @see cs_reflector_config_apply_default_settings
 */
int cs_initiator_config_apply_default_settings(const struct cs_initiator_config *config,
                                               struct bt_conn *conn);

/**
 * @brief Apply the stored CS procedure parameters for an initiator.
 *
 * Apply after successful configuration creation and the required security setup.
 * @see cs_reflector_config_apply_procedure
 */
int cs_initiator_config_apply_procedure(const struct cs_initiator_config *config,
                                        struct bt_conn *conn);

/**
 * @brief Submit the initiator's stored CS creation parameters and context.
 *
 * Builds struct bt_le_cs_create_config_params from the stored configuration
 * ID and creation fields with the initiator role and calls
 * bt_le_cs_create_config(). The stored T_PM preference is not sent here: it
 * is a SoftDevice Controller vendor setting, which the initiator role
 * (common/libs/cs_roles) sets right before this call.
 *
 * @param[in] config Initialized initiator record; not modified or retained.
 * @param[in] conn Valid, connected Bluetooth connection owned by the caller.
 * @retval 0 Creation command accepted; completion is still pending.
 * @retval -EINVAL An argument is NULL.
 * @retval -EINVAL The stored T_PM is not 10, 20 or 40.
 * @return Other negative error codes are propagated from bt_le_cs_create_config().
 * @note Wait for the le_cs_config_complete callback and check its status.
 *       Complete CS security setup before applying/enabling procedures.
 */
int cs_initiator_config_apply_creation(const struct cs_initiator_config *config,
                                       struct bt_conn *conn);

/** Buffer size that always holds the cs_reflector_config_print() output. */
#define CS_REFLECTOR_CONFIG_PRINT_SIZE 768U

/** Buffer size that always holds the cs_initiator_config_print() output. */
#define CS_INITIATOR_CONFIG_PRINT_SIZE 1536U

/** Entries in a CS frequency actuation error (FAE) table. */
#define CS_FAE_TABLE_ENTRIES 72U

/**
 * Scale of the FAE table entries: ppm = entry / CS_FAE_TABLE_LSB_DENOMINATOR.
 *
 * Zephyr passes the values through without a unit. LL_CS_FAE_RSP (Core v6.3,
 * Vol 6, Part B, 2.4.2.52) gives each entry a range of -4 to +3.96875 ppm with
 * a resolution of 0.03125 ppm.
 */
#define CS_FAE_TABLE_LSB_DENOMINATOR 32U

/** Buffer size that always holds the cs_fae_table_print() output. */
#define CS_FAE_TABLE_PRINT_SIZE 768U

/**
 * @brief Format a reflector configuration record as text.
 *
 * Writes the header, connection parameters, local CS defaults and every
 * procedure field, with units for timing and power. Encoded values are written
 * numerically. Lines end in '\n'. No Bluetooth operations are issued.
 *
 * @param[out] buf Destination; always NUL-terminated when @p size is non-zero.
 * @param[in] size Capacity of @p buf in bytes.
 *                 @ref CS_REFLECTOR_CONFIG_PRINT_SIZE never truncates.
 * @param[in] config Record to describe; not modified or retained.
 * @return Characters written, excluding the NUL.
 * @retval -EINVAL @p buf or the record is NULL, or @p size is zero; no output.
 * @retval -ENOSPC Output did not fit; @p buf holds the truncated prefix.
 * @note Issues no output of its own; the caller decides where the text goes.
 */
int cs_reflector_config_print(char *buf, size_t size, const struct cs_reflector_config *config);

/**
 * @brief Format an initiator configuration record as text.
 *
 * Writes everything @ref cs_reflector_config_print does, plus the reflector
 * data setting, creation settings, context, the raw channel map and enabled
 * CS channel indices.
 *
 * @param[out] buf Destination; always NUL-terminated when @p size is non-zero.
 * @param[in] size Capacity of @p buf in bytes.
 *                 @ref CS_INITIATOR_CONFIG_PRINT_SIZE never truncates.
 * @param[in] config Record to describe; not modified or retained.
 * @return Characters written, excluding the NUL.
 * @retval -EINVAL @p buf or the record is NULL, or @p size is zero; no output.
 * @retval -ENOSPC Output did not fit; @p buf holds the truncated prefix.
 */
int cs_initiator_config_print(char *buf, size_t size, const struct cs_initiator_config *config);

/**
 * @brief Format a frequency actuation error (FAE) table as text.
 *
 * Writes all @ref CS_FAE_TABLE_ENTRIES signed entries in HCI table order,
 * eight per row. Values are raw signed HCI encodings. Table indices are not CS
 * channel indices.
 *
 * Taking the entries rather than the callback structure lets a caller copy the
 * table out of le_cs_read_remote_fae_table_complete and format it later.
 *
 * @param[out] buf Destination; always NUL-terminated when @p size is non-zero.
 * @param[in] size Capacity of @p buf in bytes. @ref CS_FAE_TABLE_PRINT_SIZE
 *                 never truncates.
 * @param[in] entries @ref CS_FAE_TABLE_ENTRIES readable entries.
 * @return Characters written, excluding the NUL.
 * @retval -EINVAL @p buf or the record is NULL, or @p size is zero; no output.
 * @retval -ENOSPC Output did not fit; @p buf holds the truncated prefix.
 */
int cs_fae_table_print(char *buf, size_t size, const int8_t *entries);

/** @} */

#ifdef __cplusplus
}
#endif

#endif /* CS_CONFIG_H_ */
