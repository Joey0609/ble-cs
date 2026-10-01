/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief CS protocol message IDs, field encodings and complete frame layouts.
 *
 * Definitions only; framing functions are declared in cs_protocol.h.
 */

#ifndef CS_PROTOCOL_PACKETS_H_
#define CS_PROTOCOL_PACKETS_H_

#include "cs_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @defgroup cs_protocol_packets Packets
 * @ingroup cs_protocol
 * @brief Message IDs, field encodings and complete wire frames.
 *
 * Every frame struct is the complete frame as transmitted: it starts with
 * @ref cs_protocol_header_t, continues with the message fields in declaration
 * order and, for fixed-size frames, ends with @ref cs_protocol_footer_t. All
 * structs are packed and all multi-byte fields are little endian. Frames do
 * not embed utility structs; the application converts between these and its
 * own records.
 *
 * To send a fixed-size frame, fill the message fields and finalize it:
 * @code
 * struct cs_protocol_operation_mode_frame_t frame = {
 *     .mode = CS_PROTOCOL_MODE_CS_INITIATOR,
 * };
 * int len = cs_protocol_finalize_frame(&frame, sizeof(frame),
 *                                      CS_PROTOCOL_PACKET_SET_OPERATION_MODE);
 * @endcode
 *
 * On reception, cs_protocol_decode() validates framing; the application then
 * checks that @c header.size matches the expected frame size for @c type
 * before casting the frame to its struct.
 *
 * Command rules:
 * - Every host -> client command gets exactly one response:
 *   @ref CS_PROTOCOL_PACKET_CONNECT_RESPONSE for @ref CS_PROTOCOL_PACKET_CONNECT,
 *   @ref CS_PROTOCOL_PACKET_COMMAND_RESPONSE with @c request_type set to the
 *   command ID for every other command. The host sends one command at a time.
 * - Commands other than CONNECT before a successful connect are answered with
 *   @ref CS_PROTOCOL_STATUS_BAD_STATE / @ref CS_PROTOCOL_REASON_NOT_CONNECTED.
 * - SET_* and APPLY_CONFIG require the Bluetooth link to be down: while
 *   running they are answered with BAD_STATE / @ref CS_PROTOCOL_REASON_BUSY,
 *   while a link, scanning or advertising is active with BAD_STATE /
 *   @ref CS_PROTOCOL_REASON_LINK_ACTIVE. LINK_DISCONNECT while running is
 *   BAD_STATE / BUSY.
 * - START without an applied configuration is BAD_STATE /
 *   @ref CS_PROTOCOL_REASON_MISSING_CONFIG; with a @c config_crc32 different
 *   from the applied one it is @ref CS_PROTOCOL_STATUS_CONFIG_MISMATCH.
 * - GET_CONFIG is allowed in every state.
 * - CLIENT_STATE, RAS_DATA_LOST, RADIO_TEST_STATS, CS_PROCEDURES_COMPLETE and
 *   CS_PEER_DATA are unsolicited and never replace a response.
 * - CS procedures that end on their own (the initiator's controller completed
 *   @c max_procedure_count, without STOP) are reported as
 *   CS_PROCEDURES_COMPLETE with the number of completed procedures, followed by
 *   CLIENT_STATE(STOPPED, @ref CS_PROTOCOL_REASON_TEST_COMPLETE). The host ends
 *   the run as for a STOP.
 * - An interrupted operation is reported as CLIENT_STATE(STOPPED,
 *   @ref CS_PROTOCOL_REASON_INTERRUPTED) with a negative @c error: STOP before
 *   a finite test completed (the STOP response stays OK), CLOSE_SESSION or a
 *   lost host port while running (the client stops the operation). A failure
 *   that aborts a running operation is CLIENT_STATE(ERROR) with @c error and
 *   @c hci_status. A CLIENT_STATE with a non-zero @c error that could not be
 *   delivered is sent again right after the next successful CONNECT_RESPONSE.
 *
 * Configuration CRC (@c config_crc32): the client holds one applied
 * configuration. Its CRC is cs_protocol_crc32() over the concatenated
 * @b payloads (no headers or footers) of, in this order:
 * -# SET_OPERATION_MODE (1 byte)
 * -# SET_CS_INITIATOR_CONFIG, SET_CS_REFLECTOR_CONFIG or SET_RADIO_TX_TEST_CONFIG
 * -# SET_PERIPHERAL_PATTERNS, only if patterns are part of the applied configuration
 * -# SET_DEVICE_NAME, only if a device name is part of the applied configuration
 * -# SET_PEER_DATA, only if reflector data is part of the applied configuration
 * -# SET_T_PM, only if a preferred T_PM is part of the applied configuration
 * -# SET_LOG_CONFIG, only if log levels are part of the applied configuration
 *
 * Payloads are stored exactly as received. Pattern frames with non-zero bytes
 * after a pattern's length or in unused slots are rejected with
 * @ref CS_PROTOCOL_REASON_NONZERO_PADDING. SET_* commands fill a staging area;
 * APPLY_CONFIG validates the staged set, replaces the applied configuration
 * and clears the staging area. A rejected APPLY_CONFIG leaves the applied
 * configuration unchanged. Without an applied configuration @c config_valid
 * and @c config_crc32 are 0.
 *
 * Sequences:
 * @verbatim
 CONNECT                  -> CONNECT_RESPONSE(OK, supported_modes, config_valid, config_crc32)
     (host compares config_crc32 with its own)

   either apply the host configuration:
 [STOP]                   -> COMMAND_RESPONSE      only if running; closes the run
 [LINK_DISCONNECT]        -> COMMAND_RESPONSE      only if a link, scan or advertising is active
 SET_OPERATION_MODE       -> COMMAND_RESPONSE
 SET_<mode>_CONFIG        -> COMMAND_RESPONSE
 SET_PERIPHERAL_PATTERNS  -> COMMAND_RESPONSE      (CS modes, GAP central only)
 [SET_DEVICE_NAME]        -> COMMAND_RESPONSE      (CS modes)
 [SET_PEER_DATA]          -> COMMAND_RESPONSE      (CS initiator, reflector data none)
 [SET_T_PM]               -> COMMAND_RESPONSE      (CS initiator, T_PM 20 or 40 us)
 [SET_LOG_CONFIG]         -> COMMAND_RESPONSE      (any mode, levels other than the defaults)
 APPLY_CONFIG             -> COMMAND_RESPONSE(config_crc32)   host checks CRC == its own

   or take the client configuration:
 GET_CONFIG               -> SET_OPERATION_MODE, SET_<mode>_CONFIG, [SET_PERIPHERAL_PATTERNS],
                             [SET_DEVICE_NAME], [SET_PEER_DATA], [SET_T_PM],
                             [SET_LOG_CONFIG], COMMAND_RESPONSE(config_crc32)

 START(config_crc32)      -> COMMAND_RESPONSE      then CLIENT_STATE, reports, CS_FAE_TABLE
                                                   (radio RX tests: RADIO_TEST_STATS baseline,
                                                   then periodic RADIO_TEST_STATS)
   (max_procedure_count reached: CS_PROCEDURES_COMPLETE(procedures_completed),
                              CLIENT_STATE(STOPPED, TEST_COMPLETE); run closed, link kept)
 STOP                     -> [RADIO_TEST_STATS]    final report of a radio RX test
                             COMMAND_RESPONSE      procedures disabled, link kept, run closed
 CLOSE_SESSION            -> COMMAND_RESPONSE      host session ends; a running operation is
                             stopped, CLIENT_STATE(STOPPED, INTERRUPTED, -ECANCELED) follows
                             the next CONNECT_RESPONSE
 @endverbatim
 * Any rejection aborts the sequence on the host; nothing after it is sent.
 * @{
 */

/**
 * @brief Message IDs carried in @ref cs_protocol_header_t.type.
 *
 * IDs are explicit protocol values. Never place an enum object directly on
 * the wire because its storage size is compiler-dependent.
 */
enum cs_protocol_packet_type_t {
	/** Reserved; never sent. */
	CS_PROTOCOL_PACKET_INVALID = 0x0000,
	/** Client -> host: @ref cs_protocol_cs_capabilities_frame_t. */
	CS_PROTOCOL_PACKET_CS_CAPABILITIES = 0x0001,
	/** Client -> host: @ref cs_protocol_cs_configuration_frame_t. */
	CS_PROTOCOL_PACKET_CS_CONFIGURATION = 0x0002,
	/** Client -> host: @ref cs_protocol_cs_procedure_enable_complete_frame_t. */
	CS_PROTOCOL_PACKET_CS_PROCEDURE_ENABLE_COMPLETE = 0x0003,
	/** Client -> host: @ref cs_protocol_cs_initiator_subevent_result_frame_t. */
	CS_PROTOCOL_PACKET_CS_INITIATOR_SUBEVENT_RESULT = 0x0004,
	/** Client -> host: @ref cs_protocol_cs_reflector_subevent_result_frame_t. */
	CS_PROTOCOL_PACKET_CS_REFLECTOR_SUBEVENT_RESULT = 0x0005,
	/** Client -> host: @ref cs_protocol_log_message_frame_t. */
	CS_PROTOCOL_PACKET_LOG_MESSAGE = 0x0006,
	/** Client -> host: @ref cs_protocol_connect_response_frame_t. */
	CS_PROTOCOL_PACKET_CONNECT_RESPONSE = 0x0007,
	/** Client -> host: @ref cs_protocol_command_response_frame_t. */
	CS_PROTOCOL_PACKET_COMMAND_RESPONSE = 0x0008,
	/** Client -> host: @ref cs_protocol_cs_fae_table_frame_t. */
	CS_PROTOCOL_PACKET_CS_FAE_TABLE = 0x0009,
	/** Client -> host: @ref cs_protocol_client_state_frame_t. */
	CS_PROTOCOL_PACKET_CLIENT_STATE = 0x000A,
	/** Client -> host: @ref cs_protocol_ras_data_lost_frame_t. */
	CS_PROTOCOL_PACKET_RAS_DATA_LOST = 0x000B,
	/** Client -> host: @ref cs_protocol_radio_test_stats_frame_t. */
	CS_PROTOCOL_PACKET_RADIO_TEST_STATS = 0x000C,
	/** Host -> client: @ref cs_protocol_operation_mode_frame_t. */
	CS_PROTOCOL_PACKET_SET_OPERATION_MODE = 0x0100,
	/** Host -> client: @ref cs_protocol_cs_initiator_config_frame_t. */
	CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG = 0x0101,
	/** Host -> client: @ref cs_protocol_cs_reflector_config_frame_t. */
	CS_PROTOCOL_PACKET_SET_CS_REFLECTOR_CONFIG = 0x0102,
	/** Host -> client: @ref cs_protocol_radio_tx_test_config_frame_t. */
	CS_PROTOCOL_PACKET_SET_RADIO_TX_TEST_CONFIG = 0x0103,
	/** Host -> client: @ref cs_protocol_peripheral_patterns_frame_t. */
	CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS = 0x0104,
	/** Host -> client: @ref cs_protocol_apply_config_frame_t. */
	CS_PROTOCOL_PACKET_APPLY_CONFIG = 0x0105,
	/** Host -> client: @ref cs_protocol_connect_frame_t. */
	CS_PROTOCOL_PACKET_CONNECT = 0x0106,
	/** Host -> client: @ref cs_protocol_start_frame_t. */
	CS_PROTOCOL_PACKET_START = 0x0107,
	/** Host -> client: @ref cs_protocol_stop_frame_t. */
	CS_PROTOCOL_PACKET_STOP = 0x0108,
	/** Host -> client: @ref cs_protocol_close_session_frame_t. */
	CS_PROTOCOL_PACKET_CLOSE_SESSION = 0x0109,
	/** Host -> client: @ref cs_protocol_get_config_frame_t. */
	CS_PROTOCOL_PACKET_GET_CONFIG = 0x010A,
	/** Host -> client: @ref cs_protocol_link_disconnect_frame_t. */
	CS_PROTOCOL_PACKET_LINK_DISCONNECT = 0x010B,
	/** Local Bluetooth name, staged after configuration/patterns. */
	CS_PROTOCOL_PACKET_SET_DEVICE_NAME = 0x010C,
	CS_PROTOCOL_PACKET_SCAN_START = 0x010D,
	CS_PROTOCOL_PACKET_PEER_CONNECT = 0x010E,
	CS_PROTOCOL_PACKET_ADVERTISE_START = 0x010F,
	CS_PROTOCOL_PACKET_SCAN_RESULT = 0x000D,
	/** Client -> host: @ref cs_protocol_cs_procedures_complete_frame_t. */
	CS_PROTOCOL_PACKET_CS_PROCEDURES_COMPLETE = 0x000E,
	/** Client -> host: @ref cs_protocol_cs_peer_data_frame_t. */
	CS_PROTOCOL_PACKET_CS_PEER_DATA = 0x000F,
	/** Client -> host: @ref cs_protocol_connection_parameters_frame_t. */
	CS_PROTOCOL_PACKET_CONNECTION_PARAMETERS = 0x0010,
	/** Host -> client: @ref cs_protocol_peer_data_frame_t. */
	CS_PROTOCOL_PACKET_SET_PEER_DATA = 0x0110,
	/** Host -> client: @ref cs_protocol_log_config_frame_t. */
	CS_PROTOCOL_PACKET_SET_LOG_CONFIG = 0x0111,
	/** Host -> client: @ref cs_protocol_t_pm_frame_t. */
	CS_PROTOCOL_PACKET_SET_T_PM = 0x0112,
};

/** Protocol version sent in CONNECT and returned in CONNECT_RESPONSE. */
#define CS_PROTOCOL_VERSION 0x000BU

/**
 * @defgroup cs_protocol_config_values Configuration encodings
 * @brief Values and limits for host -> client configuration fields.
 * @{
 */

/** @ref cs_protocol_operation_mode_frame_t.mode encodings. */
enum cs_protocol_operation_mode {
	/** Run as CS initiator. */
	CS_PROTOCOL_MODE_CS_INITIATOR = 0x00,
	/** Run as CS reflector. */
	CS_PROTOCOL_MODE_CS_REFLECTOR = 0x01,
	/** Run the radio test. */
	CS_PROTOCOL_MODE_RADIO_TX_TEST = 0x02,
};

/** @c operation_mode value in client reports when no configuration is applied. */
#define CS_PROTOCOL_MODE_NONE 0xFFU

/** @c supported_modes bit for operation mode @p mode (a @ref cs_protocol_operation_mode). */
#define CS_PROTOCOL_MODE_BIT(mode) (1U << (mode))

/** @c gap_role encodings; independent of the CS role. */
enum cs_protocol_gap_role_t {
	/** GAP central: scans and connects using the peripheral name patterns. */
	CS_PROTOCOL_GAP_CENTRAL = 0x00,
	/** GAP peripheral: advertises and accepts a connection. */
	CS_PROTOCOL_GAP_PERIPHERAL = 0x01,
};

/** Highest valid CS configuration ID. */
#define CS_PROTOCOL_CONFIG_ID_MAX 3U

/** Highest allowed CS maximum TX power, in dBm. */
#define CS_PROTOCOL_CONFIG_MAX_TX_POWER_MAX 20
/** Lowest allowed CS maximum TX power, in dBm. */
#define CS_PROTOCOL_CONFIG_MAX_TX_POWER_MIN (-127)

/** @c cs_sync_antenna_selection encodings. */
enum cs_protocol_config_sync_antenna {
	/** Use antenna 1 for CS_SYNC packets. */
	CS_PROTOCOL_CONFIG_SYNC_ANTENNA_ONE = 0x01,
	/** Use antenna 2 for CS_SYNC packets. */
	CS_PROTOCOL_CONFIG_SYNC_ANTENNA_TWO = 0x02,
	/** Use antenna 3 for CS_SYNC packets. */
	CS_PROTOCOL_CONFIG_SYNC_ANTENNA_THREE = 0x03,
	/** Use antenna 4 for CS_SYNC packets. */
	CS_PROTOCOL_CONFIG_SYNC_ANTENNA_FOUR = 0x04,
	/** Cycle through the antennas in repetitive order. */
	CS_PROTOCOL_CONFIG_SYNC_ANTENNA_REPETITIVE = 0xFE,
	/** No recommendation; the controller chooses. */
	CS_PROTOCOL_CONFIG_SYNC_ANTENNA_NO_RECOMMENDATION = 0xFF,
};

/** @c tone_antenna_config_selection encodings (antenna configuration index). */
enum cs_protocol_config_tone_antenna {
	/** 1 initiator antenna, 1 reflector antenna. */
	CS_PROTOCOL_CONFIG_TONE_ANTENNA_A1_B1 = 0x00,
	/** 2 initiator antennas, 1 reflector antenna. */
	CS_PROTOCOL_CONFIG_TONE_ANTENNA_A2_B1 = 0x01,
	/** 3 initiator antennas, 1 reflector antenna. */
	CS_PROTOCOL_CONFIG_TONE_ANTENNA_A3_B1 = 0x02,
	/** 4 initiator antennas, 1 reflector antenna. */
	CS_PROTOCOL_CONFIG_TONE_ANTENNA_A4_B1 = 0x03,
	/** 1 initiator antenna, 2 reflector antennas. */
	CS_PROTOCOL_CONFIG_TONE_ANTENNA_A1_B2 = 0x04,
	/** 1 initiator antenna, 3 reflector antennas. */
	CS_PROTOCOL_CONFIG_TONE_ANTENNA_A1_B3 = 0x05,
	/** 1 initiator antenna, 4 reflector antennas. */
	CS_PROTOCOL_CONFIG_TONE_ANTENNA_A1_B4 = 0x06,
	/** 2 initiator antennas, 2 reflector antennas. */
	CS_PROTOCOL_CONFIG_TONE_ANTENNA_A2_B2 = 0x07,
};

/** Procedure @c phy encodings. */
enum cs_protocol_config_procedure_phy {
	/** LE 1M. */
	CS_PROTOCOL_CONFIG_PROCEDURE_PHY_1M = 0x01,
	/** LE 2M. */
	CS_PROTOCOL_CONFIG_PROCEDURE_PHY_2M = 0x02,
	/** LE Coded, S=8. */
	CS_PROTOCOL_CONFIG_PROCEDURE_PHY_CODED_S8 = 0x03,
	/** LE Coded, S=2. */
	CS_PROTOCOL_CONFIG_PROCEDURE_PHY_CODED_S2 = 0x04,
};

/** @c preferred_peer_antenna bits. */
enum cs_protocol_config_peer_antenna {
	/** Use the peer's first ordered antenna element. */
	CS_PROTOCOL_CONFIG_PEER_ANTENNA_1 = 0x01,
	/** Use the peer's second ordered antenna element. */
	CS_PROTOCOL_CONFIG_PEER_ANTENNA_2 = 0x02,
	/** Use the peer's third ordered antenna element. */
	CS_PROTOCOL_CONFIG_PEER_ANTENNA_3 = 0x04,
	/** Use the peer's fourth ordered antenna element. */
	CS_PROTOCOL_CONFIG_PEER_ANTENNA_4 = 0x08,
};

/** @c tx_power_delta value requesting no recommendation. */
#define CS_PROTOCOL_CONFIG_TX_POWER_DELTA_NONE INT8_MIN

/** SNR control encodings for RTT packets. */
enum cs_protocol_config_snr_control {
	/** 18 dB. */
	CS_PROTOCOL_CONFIG_SNR_CONTROL_18DB = 0x00,
	/** 21 dB. */
	CS_PROTOCOL_CONFIG_SNR_CONTROL_21DB = 0x01,
	/** 24 dB. */
	CS_PROTOCOL_CONFIG_SNR_CONTROL_24DB = 0x02,
	/** 27 dB. */
	CS_PROTOCOL_CONFIG_SNR_CONTROL_27DB = 0x03,
	/** 30 dB. */
	CS_PROTOCOL_CONFIG_SNR_CONTROL_30DB = 0x04,
	/** SNR control not applied. */
	CS_PROTOCOL_CONFIG_SNR_CONTROL_NOT_USED = 0xFF,
};

/** Creation @c mode encodings: main mode in bits 0-3, sub-mode in bits 4-7. */
enum cs_protocol_config_mode {
	/** Main mode 1 (RTT), no sub-mode. */
	CS_PROTOCOL_CONFIG_MODE_1 = 0x01,
	/** Main mode 2 (PBR), no sub-mode. */
	CS_PROTOCOL_CONFIG_MODE_2 = 0x02,
	/** Main mode 3 (RTT and PBR), no sub-mode. */
	CS_PROTOCOL_CONFIG_MODE_3 = 0x03,
	/** Main mode 2 with sub-mode 1. */
	CS_PROTOCOL_CONFIG_MODE_2_SUB_MODE_1 = 0x12,
	/** Main mode 2 with sub-mode 3. */
	CS_PROTOCOL_CONFIG_MODE_2_SUB_MODE_3 = 0x32,
	/** Main mode 3 with sub-mode 2. */
	CS_PROTOCOL_CONFIG_MODE_3_SUB_MODE_2 = 0x23,
};

/** Creation @c rtt_type encodings. */
enum cs_protocol_config_rtt_type {
	/** RTT on the access address only. */
	CS_PROTOCOL_CONFIG_RTT_TYPE_AA_ONLY = 0x00,
	/** RTT with a 32-bit sounding sequence. */
	CS_PROTOCOL_CONFIG_RTT_TYPE_32_BIT_SOUNDING = 0x01,
	/** RTT with a 96-bit sounding sequence. */
	CS_PROTOCOL_CONFIG_RTT_TYPE_96_BIT_SOUNDING = 0x02,
	/** RTT with a 32-bit random sequence. */
	CS_PROTOCOL_CONFIG_RTT_TYPE_32_BIT_RANDOM = 0x03,
	/** RTT with a 64-bit random sequence. */
	CS_PROTOCOL_CONFIG_RTT_TYPE_64_BIT_RANDOM = 0x04,
	/** RTT with a 96-bit random sequence. */
	CS_PROTOCOL_CONFIG_RTT_TYPE_96_BIT_RANDOM = 0x05,
	/** RTT with a 128-bit random sequence. */
	CS_PROTOCOL_CONFIG_RTT_TYPE_128_BIT_RANDOM = 0x06,
};

/** Creation @c cs_sync_phy encodings. */
enum cs_protocol_config_sync_phy {
	/** CS_SYNC on LE 1M. */
	CS_PROTOCOL_CONFIG_SYNC_PHY_1M = 0x01,
	/** CS_SYNC on LE 2M. */
	CS_PROTOCOL_CONFIG_SYNC_PHY_2M = 0x02,
	/** CS_SYNC on LE 2M 2BT. */
	CS_PROTOCOL_CONFIG_SYNC_PHY_2M_2BT = 0x03,
};

/** Creation @c channel_selection_type encodings. */
enum cs_protocol_config_chsel_type {
	/** Channel selection algorithm #3b. */
	CS_PROTOCOL_CONFIG_CHSEL_TYPE_3B = 0x00,
	/** Channel selection algorithm #3c. */
	CS_PROTOCOL_CONFIG_CHSEL_TYPE_3C = 0x01,
};

/** Creation @c ch3c_shape encodings. */
enum cs_protocol_config_ch3c_shape {
	/** Hat shape: rising then falling channel sequence. */
	CS_PROTOCOL_CONFIG_CH3C_SHAPE_HAT = 0x00,
	/** X shape: interleaved rising and falling channel sequences. */
	CS_PROTOCOL_CONFIG_CH3C_SHAPE_X = 0x01,
};

/** Creation @c cs_enhancements_1 bit 0: IPT in the CS reflector. */
#define CS_PROTOCOL_CONFIG_ENHANCEMENTS_1_IPT 0x01U

/** Creation @c context encodings. */
enum cs_protocol_config_creation_context {
	/** Write the configuration in the local controller only. */
	CS_PROTOCOL_CONFIG_CREATION_CONTEXT_LOCAL_ONLY = 0x00,
	/** Write the configuration locally and in the peer via configuration exchange. */
	CS_PROTOCOL_CONFIG_CREATION_CONTEXT_LOCAL_AND_REMOTE = 0x01,
};

/** Number of bytes in a CS channel map. */
#define CS_PROTOCOL_CONFIG_CHANNEL_MAP_SIZE 10U

/** @} */

/**
 * @defgroup cs_protocol_session_values Session encodings
 * @brief Values carried in connect, command response and client state frames.
 * @{
 */

/** @c status of CONNECT_RESPONSE and COMMAND_RESPONSE. */
enum cs_protocol_status {
	/** Command accepted and completed. */
	CS_PROTOCOL_STATUS_OK = 0x00,
	/** Command rejected; @c reason says why. */
	CS_PROTOCOL_STATUS_REJECTED = 0x01,
	/** Command or operation mode not supported by this build. */
	CS_PROTOCOL_STATUS_UNSUPPORTED = 0x02,
	/** Command not allowed in the current state, e.g. configuration while the link is up. */
	CS_PROTOCOL_STATUS_BAD_STATE = 0x03,
	/** Frame size does not match its type. */
	CS_PROTOCOL_STATUS_INVALID_FRAME = 0x04,
	/** CONNECT @c protocol_version does not match @ref CS_PROTOCOL_VERSION. */
	CS_PROTOCOL_STATUS_VERSION = 0x05,
	/** Apply, start or stop failed; @c error holds the negative errno. */
	CS_PROTOCOL_STATUS_FAILED = 0x06,
	/** START @c config_crc32 differs from the applied configuration CRC. */
	CS_PROTOCOL_STATUS_CONFIG_MISMATCH = 0x07,
};

/** @c reason of COMMAND_RESPONSE and CLIENT_STATE. */
enum cs_protocol_reject_reason {
	/** No specific reason. */
	CS_PROTOCOL_REASON_NONE = 0x00,
	/** No host session: CONNECT has not succeeded. */
	CS_PROTOCOL_REASON_NOT_CONNECTED = 0x01,
	/** Configuration frame type does not match the staged operation mode. */
	CS_PROTOCOL_REASON_MODE_MISMATCH = 0x02,
	/** A field value is outside its valid range. */
	CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE = 0x03,
	/** Pattern bytes past a pattern's length, or in unused slots, are not zero. */
	CS_PROTOCOL_REASON_NONZERO_PADDING = 0x04,
	/** No (staged or applied) configuration. */
	CS_PROTOCOL_REASON_MISSING_CONFIG = 0x05,
	/** GAP central configuration without peripheral patterns. */
	CS_PROTOCOL_REASON_MISSING_PATTERNS = 0x06,
	/** A test is running; stop it first. */
	CS_PROTOCOL_REASON_BUSY = 0x07,
	/** Configuration change while a Bluetooth link, scanning or advertising is active. */
	CS_PROTOCOL_REASON_LINK_ACTIVE = 0x08,
	/** Procedures disabled, but the last RAS data was not received in time. */
	CS_PROTOCOL_REASON_STOP_TIMEOUT = 0x09,
	/** Peer RAS server does not support real-time ranging data. */
	CS_PROTOCOL_REASON_RAS_NO_REALTIME = 0x0A,
	/** The test finished on its own, e.g. a radio test with a finite packet count. */
	CS_PROTOCOL_REASON_TEST_COMPLETE = 0x0B,
	/**
	 * CLIENT_STATE(STOPPED or ERROR): the operation was interrupted before it
	 * completed; @c error says what interrupted it.
	 */
	CS_PROTOCOL_REASON_INTERRUPTED = 0x0C,
	CS_PROTOCOL_REASON_SCAN_FAILED = 0x0D,
	CS_PROTOCOL_REASON_ADVERTISE_FAILED = 0x0E,
	CS_PROTOCOL_REASON_CONNECT_FAILED = 0x0F,
	CS_PROTOCOL_REASON_SECURITY_FAILED = 0x10,
	CS_PROTOCOL_REASON_RAS_DISCOVERY_FAILED = 0x11,
	CS_PROTOCOL_REASON_CS_CONFIG_FAILED = 0x12,
	CS_PROTOCOL_REASON_CS_SECURITY_FAILED = 0x13,
	/**
	 * CLIENT_STATE(ERROR): reflector data none was selected, but the peer does
	 * not support IPT or the created configuration does not enable it.
	 */
	CS_PROTOCOL_REASON_PEER_IPT_UNSUPPORTED = 0x14,
};

/** @c state of CLIENT_STATE and @c client_state of CONNECT_RESPONSE. */
enum cs_protocol_client_state {
	/** No configuration applied, no radio activity. */
	CS_PROTOCOL_CLIENT_STATE_IDLE = 0x00,
	/** Configuration applied, not started. */
	CS_PROTOCOL_CLIENT_STATE_CONFIGURED = 0x01,
	/** GAP central scanning for a peer. */
	CS_PROTOCOL_CLIENT_STATE_SCANNING = 0x02,
	/** GAP peripheral advertising. */
	CS_PROTOCOL_CLIENT_STATE_ADVERTISING = 0x03,
	/** Bluetooth link established. */
	CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTED = 0x04,
	/** Ranging Service set up on the link. */
	CS_PROTOCOL_CLIENT_STATE_RAS_READY = 0x05,
	/** CS procedures or the radio test are running. */
	CS_PROTOCOL_CLIENT_STATE_RUNNING = 0x06,
	/** Procedures or the radio test stopped; the link is kept. */
	CS_PROTOCOL_CLIENT_STATE_STOPPED = 0x07,
	/** Bluetooth link lost unexpectedly. */
	CS_PROTOCOL_CLIENT_STATE_LINK_LOST = 0x08,
	/** Bluetooth link disconnected on request. */
	CS_PROTOCOL_CLIENT_STATE_LINK_DISCONNECTED = 0x09,
	/** Unrecoverable error; @c reason and @c hci_status give details. */
	CS_PROTOCOL_CLIENT_STATE_ERROR = 0x0A,
	CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTING = 0x0B,
};

/** Number of entries in a CS FAE table. */
#define CS_PROTOCOL_FAE_TABLE_ENTRIES 72U

/** @} */

/**
 * @defgroup cs_protocol_host_frames Host -> client frames
 * @brief Commands that open the session, configure, start and stop the client.
 * @{
 */

/**
 * @brief @ref CS_PROTOCOL_PACKET_SET_OPERATION_MODE, 13 bytes.
 *
 * Selects which configuration frame follows.
 */
struct cs_protocol_operation_mode_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Operation mode, one of @ref cs_protocol_operation_mode. */
	uint8_t mode;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

/**
 * @brief @ref CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG, 69 bytes.
 *
 * Connection, CS default settings, procedure parameters and the CS
 * configuration to create. Fields prefixed @c creation_ are the CS
 * configuration creation parameters.
 */
struct cs_protocol_cs_initiator_config_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** GAP role, one of @ref cs_protocol_gap_role_t; independent of the CS role. */
	uint8_t gap_role;
	/** CS configuration ID, 0..@ref CS_PROTOCOL_CONFIG_ID_MAX. */
	uint8_t config_id;
	/** Minimum connection interval, 1.25 ms units. */
	uint16_t connection_interval_min;
	/** Maximum connection interval, 1.25 ms units. */
	uint16_t connection_interval_max;
	/** Peripheral latency, ACL events. */
	uint16_t connection_latency;
	/** Supervision timeout, 10 ms units. */
	uint16_t connection_timeout;
	/** CS_SYNC antenna, one of @ref cs_protocol_config_sync_antenna. */
	uint8_t cs_sync_antenna_selection;
	/**
	 * Maximum TX power (EIRP) in dBm,
	 * @ref CS_PROTOCOL_CONFIG_MAX_TX_POWER_MIN..@ref CS_PROTOCOL_CONFIG_MAX_TX_POWER_MAX.
	 */
	int8_t max_tx_power;
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
	/** Tone antenna configuration index, one of @ref cs_protocol_config_tone_antenna. */
	uint8_t tone_antenna_config_selection;
	/** Procedure PHY, one of @ref cs_protocol_config_procedure_phy. */
	uint8_t phy;
	/** Recommended TX power delta in dB, or @ref CS_PROTOCOL_CONFIG_TX_POWER_DELTA_NONE. */
	int8_t tx_power_delta;
	/** Preferred peer antennas, bitmask of @ref cs_protocol_config_peer_antenna. */
	uint8_t preferred_peer_antenna;
	/** Initiator SNR control, one of @ref cs_protocol_config_snr_control. */
	uint8_t snr_control_initiator;
	/** Reflector SNR control, one of @ref cs_protocol_config_snr_control. */
	uint8_t snr_control_reflector;
	/** Main mode and sub-mode, one of @ref cs_protocol_config_mode. */
	uint8_t creation_mode;
	/** Minimum main-mode steps before a sub-mode step. */
	uint8_t creation_min_main_mode_steps;
	/** Maximum main-mode steps before a sub-mode step. */
	uint8_t creation_max_main_mode_steps;
	/** Main-mode steps repeated from the end of the previous subevent. */
	uint8_t creation_main_mode_repetition;
	/** Mode-0 steps at the start of each subevent. */
	uint8_t creation_mode_0_steps;
	/** RTT type, one of @ref cs_protocol_config_rtt_type. */
	uint8_t creation_rtt_type;
	/** CS_SYNC PHY, one of @ref cs_protocol_config_sync_phy. */
	uint8_t creation_cs_sync_phy;
	/**
	 * CS channel map, byte 0 first. Bit n represents 2402 + n MHz; this is a
	 * CS frequency index, not a BLE ACL channel index.
	 */
	uint8_t creation_channel_map[10];
	/** Times the channel map is cycled through for non-mode-0 steps. */
	uint8_t creation_channel_map_repetition;
	/** Channel selection algorithm, one of @ref cs_protocol_config_chsel_type. */
	uint8_t creation_channel_selection_type;
	/** Channel selection 3c shape, one of @ref cs_protocol_config_ch3c_shape. */
	uint8_t creation_ch3c_shape;
	/** Channels skipped in each channel selection 3c rising/falling sequence. */
	uint8_t creation_ch3c_jump;
	/** CS enhancements 1 bits, e.g. @ref CS_PROTOCOL_CONFIG_ENHANCEMENTS_1_IPT. */
	uint8_t creation_cs_enhancements_1;
	/** Creation destination, one of @ref cs_protocol_config_creation_context. */
	uint8_t creation_context;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

/**
 * @brief @ref CS_PROTOCOL_PACKET_SET_CS_REFLECTOR_CONFIG, 46 bytes.
 *
 * Same leading fields as @ref cs_protocol_cs_initiator_config_frame_t; the
 * reflector does not create the CS configuration, so there are no
 * @c creation_ fields.
 */
struct cs_protocol_cs_reflector_config_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** GAP role, one of @ref cs_protocol_gap_role_t; independent of the CS role. */
	uint8_t gap_role;
	/** CS configuration ID, 0..@ref CS_PROTOCOL_CONFIG_ID_MAX. */
	uint8_t config_id;
	/** Minimum connection interval, 1.25 ms units. */
	uint16_t connection_interval_min;
	/** Maximum connection interval, 1.25 ms units. */
	uint16_t connection_interval_max;
	/** Peripheral latency, ACL events. */
	uint16_t connection_latency;
	/** Supervision timeout, 10 ms units. */
	uint16_t connection_timeout;
	/** CS_SYNC antenna, one of @ref cs_protocol_config_sync_antenna. */
	uint8_t cs_sync_antenna_selection;
	/**
	 * Maximum TX power (EIRP) in dBm,
	 * @ref CS_PROTOCOL_CONFIG_MAX_TX_POWER_MIN..@ref CS_PROTOCOL_CONFIG_MAX_TX_POWER_MAX.
	 */
	int8_t max_tx_power;
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
	/** Tone antenna configuration index, one of @ref cs_protocol_config_tone_antenna. */
	uint8_t tone_antenna_config_selection;
	/** Procedure PHY, one of @ref cs_protocol_config_procedure_phy. */
	uint8_t phy;
	/** Recommended TX power delta in dB, or @ref CS_PROTOCOL_CONFIG_TX_POWER_DELTA_NONE. */
	int8_t tx_power_delta;
	/** Preferred peer antennas, bitmask of @ref cs_protocol_config_peer_antenna. */
	uint8_t preferred_peer_antenna;
	/** Initiator SNR control, one of @ref cs_protocol_config_snr_control. */
	uint8_t snr_control_initiator;
	/** Reflector SNR control, one of @ref cs_protocol_config_snr_control. */
	uint8_t snr_control_reflector;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

/**
 * @brief @ref CS_PROTOCOL_PACKET_SET_RADIO_TX_TEST_CONFIG, 37 bytes.
 *
 * Radio test parameters. Fields that do not apply to @c test_type are ignored.
 */
struct cs_protocol_radio_tx_test_config_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/**
	 * Radio test type: 0 unmodulated TX, 1 modulated TX, 2 RX, 3 TX sweep,
	 * 4 RX sweep, 5 duty-cycle TX, 6 unmodulated sleep sweep,
	 * 7 modulated sleep sweep.
	 */
	uint8_t test_type;
	/**
	 * PHY: 0 BLE 1M, 1 BLE 2M, 2 BLE LR125K, 3 BLE LR500K,
	 * 4 Nordic 1M, 5 Nordic 2M, 6 IEEE 802.15.4 250K.
	 */
	uint8_t phy;
	/** 2400 + channel MHz (0..80); PHY 6 uses channels 11..26. */
	uint8_t channel;
	/** Requested output power in dBm. */
	int8_t txpower;
	/** Modulated payload: 0 random, 1 repeated 11110000, 2 repeated 11001100. */
	uint8_t pattern;
	/** Packets to send; 0 = unlimited. Completion callbacks remain client-local. */
	uint32_t packet_count;
	/** Inclusive first sweep channel, 0..80. */
	uint8_t sweep_start_channel;
	/** Inclusive last sweep channel, 0..80. */
	uint8_t sweep_end_channel;
	/** Per-channel dwell time in milliseconds. */
	uint32_t sweep_delay_ms;
	/** Duty-cycle TX percentage, 1..99. */
	uint8_t duty_cycle;
	/** Sleep sweep transmit duration in microseconds. */
	uint16_t tx_time_us;
	/** Sleep sweep sleep duration in microseconds. */
	uint16_t sleep_time_us;
	/** FEM ramp-up time in microseconds; ignored without FEM. */
	uint32_t fem_ramp_up_time_us;
	/** FEM-specific control; 255 keeps the default. */
	uint8_t fem_tx_power_control;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

/**
 * @brief @ref CS_PROTOCOL_PACKET_SET_PERIPHERAL_PATTERNS, 277 bytes.
 *
 * Advertising name prefixes a GAP central connects to. A peer matches when its
 * name starts with any active pattern. Matching and validation are
 * application work.
 */
struct cs_protocol_peripheral_patterns_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Number of active patterns, 1..8. */
	uint8_t count;
	/** Length of each active pattern in bytes, 1..32; unused entries zero. */
	uint8_t lengths[8];
	/**
	 * Case-sensitive UTF-8 name prefixes; OR matching, no wildcards or NUL.
	 * Bytes after each length and unused entries must be zero.
	 */
	uint8_t patterns[8][32];
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

/** Local Bluetooth name: 1..32 UTF-8 bytes, no NUL, zero padding.
 * Optional final configuration payload in CRC order. Omission restores the
 * firmware default. Not valid for radio test mode.
 */
/* Discovery commands require an applied CS configuration. No CRC payload changes. */
struct cs_protocol_scan_start_frame_t {
    struct cs_protocol_header_t header;
    struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
struct cs_protocol_advertise_start_frame_t {
    struct cs_protocol_header_t header;
    struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
struct cs_protocol_peer_connect_frame_t {
    struct cs_protocol_header_t header;
    uint8_t address_type; /* 0 public, 1 random */
    uint8_t address[6]; /* Zephyr/on-air byte order */
    struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
/* One advertisement or scan-response update; merge by address/type.
 * flags: bit 0 connectable, bit 1 complete name. Missing names have length 0.
 * All advertised name bytes fit, including extended advertising (254 bytes).
 */
struct cs_protocol_scan_result_frame_t {
    struct cs_protocol_header_t header;
    uint8_t address_type;
    uint8_t address[6];
    int8_t rssi_dbm;
    uint8_t flags;
    uint8_t name_length;
    uint8_t name[254];
    struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_scan_start_frame_t) == 12U, "scan_start size");
_Static_assert(offsetof(struct cs_protocol_scan_start_frame_t, footer) == 6U, "scan_start footer");
_Static_assert(sizeof(struct cs_protocol_advertise_start_frame_t) == 12U, "advertise_start size");
_Static_assert(offsetof(struct cs_protocol_advertise_start_frame_t, footer) == 6U, "advertise_start footer");
_Static_assert(sizeof(struct cs_protocol_peer_connect_frame_t) == 19U, "peer_connect size");
_Static_assert(offsetof(struct cs_protocol_peer_connect_frame_t, footer) == 13U, "peer_connect footer");
_Static_assert(sizeof(struct cs_protocol_scan_result_frame_t) == 276U, "scan_result size");
_Static_assert(offsetof(struct cs_protocol_scan_result_frame_t, footer) == 270U, "scan_result footer");

struct cs_protocol_device_name_frame_t {
    struct cs_protocol_header_t header;
    uint8_t length;
    uint8_t name[32];
    struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_device_name_frame_t) == 45U, "device_name size");
_Static_assert(offsetof(struct cs_protocol_device_name_frame_t, footer) == 39U, "device_name footer");

/** @ref cs_protocol_peer_data_frame_t.peer_data encodings: data the initiator receives from the reflector. */
enum cs_protocol_peer_data {
	/** Reflector subevents through RAS real-time ranging data; the default without SET_PEER_DATA. */
	CS_PROTOCOL_PEER_DATA_RAS_REALTIME = 0x00,
	/** None: initiator subevents only, without RAS. Requires IPT. */
	CS_PROTOCOL_PEER_DATA_NONE = 0x01,
};

/**
 * @brief @ref CS_PROTOCOL_PACKET_SET_PEER_DATA, 13 bytes.
 *
 * Optional configuration of the CS initiator mode, added in protocol version
 * 0x0007. Without it the initiator receives the reflector's data through RAS
 * real-time, so the only accepted value is @ref CS_PROTOCOL_PEER_DATA_NONE
 * (VALUE_OUT_OF_RANGE otherwise) and each configuration has one byte
 * representation. Other modes: REJECTED / MODE_MISMATCH. APPLY_CONFIG rejects
 * it without @ref CS_PROTOCOL_CONFIG_ENHANCEMENTS_1_IPT in the staged
 * initiator configuration (VALUE_OUT_OF_RANGE, -EINVAL).
 */
struct cs_protocol_peer_data_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** One of @ref cs_protocol_peer_data; only NONE is accepted. */
	uint8_t peer_data;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_peer_data_frame_t) == 13U, "peer_data frame size");
_Static_assert(offsetof(struct cs_protocol_peer_data_frame_t, footer) == 7U,
               "peer_data footer offset");

/** @ref cs_protocol_t_pm_frame_t.t_pm_us values: the preferred T_PM in microseconds. */
enum cs_protocol_t_pm {
	/** 10 us; the preferred T_PM without SET_T_PM. */
	CS_PROTOCOL_T_PM_10_US = 10,
	CS_PROTOCOL_T_PM_20_US = 20,
	CS_PROTOCOL_T_PM_40_US = 40,
};

/**
 * @brief @ref CS_PROTOCOL_PACKET_SET_T_PM, 13 bytes.
 *
 * Optional configuration of the CS initiator mode, added in protocol version
 * 0x0009: the preferred phase measurement period T_PM. The initiator passes it
 * to its controller before each LE CS Create Config; a reflector without
 * support for it gets a T_PM both devices support, and CS_CONFIGURATION reports
 * the one in use. Without it the initiator prefers
 * @ref CS_PROTOCOL_T_PM_10_US, so only 20 and 40 are accepted
 * (VALUE_OUT_OF_RANGE otherwise) and each configuration has one byte
 * representation. Other modes: REJECTED / MODE_MISMATCH. Before
 * SET_OPERATION_MODE: BAD_STATE / MISSING_CONFIG.
 */
struct cs_protocol_t_pm_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** One of @ref cs_protocol_t_pm; 20 or 40 are accepted. */
	uint8_t t_pm_us;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_t_pm_frame_t) == 13U, "t_pm frame size");
_Static_assert(offsetof(struct cs_protocol_t_pm_frame_t, footer) == 7U, "t_pm footer offset");

/** @ref cs_protocol_log_config_frame_t levels, in Zephyr numbering. */
enum cs_protocol_log_level {
	CS_PROTOCOL_LOG_LEVEL_OFF = 0x00,
	CS_PROTOCOL_LOG_LEVEL_ERROR = 0x01,
	CS_PROTOCOL_LOG_LEVEL_WARNING = 0x02,
	CS_PROTOCOL_LOG_LEVEL_INFO = 0x03,
	CS_PROTOCOL_LOG_LEVEL_DEBUG = 0x04,
};

/** Console level without SET_LOG_CONFIG. */
#define CS_PROTOCOL_LOG_CONSOLE_LEVEL_DEFAULT CS_PROTOCOL_LOG_LEVEL_INFO
/** LOG_MESSAGE level without SET_LOG_CONFIG. */
#define CS_PROTOCOL_LOG_PROTOCOL_LEVEL_DEFAULT CS_PROTOCOL_LOG_LEVEL_WARNING

/**
 * @brief @ref CS_PROTOCOL_PACKET_SET_LOG_CONFIG, 14 bytes.
 *
 * Optional configuration of every operation mode, added in protocol version
 * 0x0008: the levels of the client's log consumers. A consumer receives
 * messages at its level and below. Without it the client uses
 * @ref CS_PROTOCOL_LOG_CONSOLE_LEVEL_DEFAULT and
 * @ref CS_PROTOCOL_LOG_PROTOCOL_LEVEL_DEFAULT, so a payload equal to the
 * defaults is rejected, as is a level above
 * @ref CS_PROTOCOL_LOG_LEVEL_DEBUG (REJECTED / VALUE_OUT_OF_RANGE): each
 * configuration has one byte representation. Before SET_OPERATION_MODE:
 * BAD_STATE / MISSING_CONFIG. The levels take effect at APPLY_CONFIG.
 */
struct cs_protocol_log_config_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Console (debug UART or RTT) level, one of @ref cs_protocol_log_level. */
	uint8_t console_level;
	/** LOG_MESSAGE level, one of @ref cs_protocol_log_level. */
	uint8_t protocol_level;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_log_config_frame_t) == 14U, "log_config frame size");
_Static_assert(offsetof(struct cs_protocol_log_config_frame_t, footer) == 8U,
               "log_config footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_APPLY_CONFIG, 12 bytes.
 *
 * Apply the previously received operation mode and configuration. No payload.
 */
struct cs_protocol_apply_config_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

_Static_assert(sizeof(struct cs_protocol_operation_mode_frame_t) == 13U,
               "operation_mode frame size");
_Static_assert(offsetof(struct cs_protocol_operation_mode_frame_t,
                        footer) == 7U,
               "operation_mode footer offset");
_Static_assert(sizeof(struct cs_protocol_cs_initiator_config_frame_t) == 69U,
               "cs_initiator_config frame size");
_Static_assert(offsetof(struct cs_protocol_cs_initiator_config_frame_t,
                        footer) == 63U,
               "cs_initiator_config footer offset");
_Static_assert(sizeof(struct cs_protocol_cs_reflector_config_frame_t) == 46U,
               "cs_reflector_config frame size");
_Static_assert(offsetof(struct cs_protocol_cs_reflector_config_frame_t,
                        footer) == 40U,
               "cs_reflector_config footer offset");
_Static_assert(sizeof(struct cs_protocol_radio_tx_test_config_frame_t) == 37U,
               "radio_tx_test_config frame size");
_Static_assert(offsetof(struct cs_protocol_radio_tx_test_config_frame_t,
                        footer) == 31U,
               "radio_tx_test_config footer offset");
_Static_assert(sizeof(struct cs_protocol_peripheral_patterns_frame_t) == 277U,
               "peripheral_patterns frame size");
_Static_assert(offsetof(struct cs_protocol_peripheral_patterns_frame_t,
                        footer) == 271U,
               "peripheral_patterns footer offset");
_Static_assert(sizeof(struct cs_protocol_apply_config_frame_t) == 12U,
               "apply_config frame size");
_Static_assert(offsetof(struct cs_protocol_apply_config_frame_t,
                        footer) == 6U,
               "apply_config footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CONNECT, 14 bytes.
 *
 * Opens a host session. Answered with @ref cs_protocol_connect_response_frame_t.
 */
struct cs_protocol_connect_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Host protocol version, @ref CS_PROTOCOL_VERSION. */
	uint16_t protocol_version;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

/**
 * @brief @ref CS_PROTOCOL_PACKET_START, 16 bytes.
 *
 * Starts the applied configuration: CS procedures (after the connection
 * sequence when there is no link) or the radio test.
 */
struct cs_protocol_start_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** CRC of the configuration the host expects to run; must equal the applied CRC. */
	uint32_t config_crc32;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

/**
 * @brief @ref CS_PROTOCOL_PACKET_STOP, 12 bytes.
 *
 * Disables CS procedures (keeping the link) or stops the radio test. Confirmed
 * after procedures are disabled and, in the initiator role, the last RAS data
 * has arrived or timed out. No payload.
 */
struct cs_protocol_stop_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

/**
 * @brief @ref CS_PROTOCOL_PACKET_CLOSE_SESSION, 12 bytes.
 *
 * Ends the host session only; the Bluetooth link and a running test are
 * unaffected. No payload.
 */
struct cs_protocol_close_session_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

/**
 * @brief @ref CS_PROTOCOL_PACKET_GET_CONFIG, 12 bytes.
 *
 * Requests the applied configuration. The client replies with the same
 * host-direction frames (SET_OPERATION_MODE, the configuration frame,
 * SET_PERIPHERAL_PATTERNS if present), followed by COMMAND_RESPONSE carrying
 * the CRC. Allowed in every state. No payload.
 */
struct cs_protocol_get_config_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

/**
 * @brief @ref CS_PROTOCOL_PACKET_LINK_DISCONNECT, 12 bytes.
 *
 * Disconnects the Bluetooth link and stops scanning or advertising. Confirmed
 * after the disconnected callback, or immediately without a link. No payload.
 */
struct cs_protocol_link_disconnect_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));

_Static_assert(sizeof(struct cs_protocol_connect_frame_t) == 14U,
               "connect frame size");
_Static_assert(offsetof(struct cs_protocol_connect_frame_t,
                        footer) == 8U,
               "connect footer offset");
_Static_assert(sizeof(struct cs_protocol_start_frame_t) == 16U,
               "start frame size");
_Static_assert(offsetof(struct cs_protocol_start_frame_t,
                        footer) == 10U,
               "start footer offset");
_Static_assert(sizeof(struct cs_protocol_stop_frame_t) == 12U,
               "stop frame size");
_Static_assert(offsetof(struct cs_protocol_stop_frame_t,
                        footer) == 6U,
               "stop footer offset");
_Static_assert(sizeof(struct cs_protocol_close_session_frame_t) == 12U,
               "close_session frame size");
_Static_assert(offsetof(struct cs_protocol_close_session_frame_t,
                        footer) == 6U,
               "close_session footer offset");
_Static_assert(sizeof(struct cs_protocol_get_config_frame_t) == 12U,
               "get_config frame size");
_Static_assert(offsetof(struct cs_protocol_get_config_frame_t,
                        footer) == 6U,
               "get_config footer offset");
_Static_assert(sizeof(struct cs_protocol_link_disconnect_frame_t) == 12U,
               "link_disconnect frame size");
_Static_assert(offsetof(struct cs_protocol_link_disconnect_frame_t,
                        footer) == 6U,
               "link_disconnect footer offset");

/** @} */

/**
 * @defgroup cs_protocol_result_values Result encodings
 * @brief Values carried in client -> host report and step fields.
 *
 * Status and abort values mirror HCI verbatim.
 * @{
 */

/** CS role encodings, used by @ref cs_protocol_cs_configuration_frame_t.role. */
enum cs_protocol_cs_role_t {
	/** CS initiator. */
	CS_PROTOCOL_CS_ROLE_INITIATOR = 0x00,
	/** CS reflector. */
	CS_PROTOCOL_CS_ROLE_REFLECTOR = 0x01,
};

/** @ref cs_protocol_cs_capabilities_frame_t.source encodings. */
enum cs_protocol_cs_capabilities_source_t {
	/** Capabilities of the local controller. */
	CS_PROTOCOL_CS_CAPABILITIES_SOURCE_LOCAL = 0x00,
	/** Capabilities of the connected peer's controller. */
	CS_PROTOCOL_CS_CAPABILITIES_SOURCE_REMOTE = 0x01,
};

/** @ref cs_protocol_cs_capabilities_frame_t.conn_index for local capabilities. */
#define CS_PROTOCOL_CS_CAPABILITIES_CONN_NONE UINT8_C(0xff)

/** @ref cs_protocol_cs_step_decoded_t.mode encodings. */
enum cs_protocol_cs_step_mode_t {
	/** Mode 0: frequency calibration. */
	CS_PROTOCOL_CS_STEP_MODE_0 = 0x00,
	/** Mode 1: RTT. */
	CS_PROTOCOL_CS_STEP_MODE_1 = 0x01,
	/** Mode 2: PBR tones. */
	CS_PROTOCOL_CS_STEP_MODE_2 = 0x02,
	/** Mode 3: RTT and PBR tones. */
	CS_PROTOCOL_CS_STEP_MODE_3 = 0x03,
};

/** @c procedure_done_status encodings. */
enum cs_protocol_cs_procedure_status_t {
	/** All results for the procedure are reported. */
	CS_PROTOCOL_CS_PROCEDURE_COMPLETE = 0x00,
	/** More results for the procedure follow. */
	CS_PROTOCOL_CS_PROCEDURE_INCOMPLETE = 0x01,
	/** The procedure was aborted; see @c procedure_abort_reason. */
	CS_PROTOCOL_CS_PROCEDURE_ABORTED = 0x0f,
};

/** @c subevent_done_status encodings. */
enum cs_protocol_cs_subevent_status_t {
	/** All results for the subevent are reported. */
	CS_PROTOCOL_CS_SUBEVENT_COMPLETE = 0x00,
	/** More results for the subevent follow. */
	CS_PROTOCOL_CS_SUBEVENT_INCOMPLETE = 0x01,
	/** The subevent was aborted; see @c subevent_abort_reason. */
	CS_PROTOCOL_CS_SUBEVENT_ABORTED = 0x0f,
};

/** @c procedure_abort_reason encodings. */
enum cs_protocol_cs_procedure_abort_reason_t {
	/** Not aborted. */
	CS_PROTOCOL_CS_PROCEDURE_NOT_ABORTED = 0x00,
	/** Aborted by local or remote request. */
	CS_PROTOCOL_CS_PROCEDURE_ABORT_REQUESTED = 0x01,
	/** Too few channels in the channel map. */
	CS_PROTOCOL_CS_PROCEDURE_ABORT_TOO_FEW_CHANNELS = 0x02,
	/** The channel map update instant has passed. */
	CS_PROTOCOL_CS_PROCEDURE_ABORT_CHMAP_INSTANT_PASSED = 0x03,
	/** Unspecified reason. */
	CS_PROTOCOL_CS_PROCEDURE_ABORT_UNSPECIFIED = 0x0f,
};

/** @c subevent_abort_reason encodings. */
enum cs_protocol_cs_subevent_abort_reason_t {
	/** Not aborted. */
	CS_PROTOCOL_CS_SUBEVENT_NOT_ABORTED = 0x00,
	/** Aborted by local or remote request. */
	CS_PROTOCOL_CS_SUBEVENT_ABORT_REQUESTED = 0x01,
	/** No CS_SYNC (mode-0) packet was received. */
	CS_PROTOCOL_CS_SUBEVENT_ABORT_NO_CS_SYNC = 0x02,
	/** Scheduling conflict or limited resources. */
	CS_PROTOCOL_CS_SUBEVENT_ABORT_SCHED_CONFLICT = 0x03,
	/** Unspecified reason. */
	CS_PROTOCOL_CS_SUBEVENT_ABORT_UNSPECIFIED = 0x0f,
};

/**
 * @name "Not available" sentinels
 * Values HCI uses for "not available", carried verbatim by the report fields.
 * Mirrored here so that neither side of the link has to pull in the Zephyr
 * HCI headers to recognize them.
 * @{
 */
/** @c frequency_compensation not available. */
#define CS_PROTOCOL_CS_FREQ_COMPENSATION_NA UINT16_C(0xc000)
/** @c reference_power_level not available. */
#define CS_PROTOCOL_CS_REF_POWER_LEVEL_NA ((int8_t)0x7f)
/** @c selected_tx_power not available. */
#define CS_PROTOCOL_CS_TX_POWER_NA ((int8_t)0x7f)
/** HCI RSSI not available; on the wire see @ref CS_PROTOCOL_CS_STEP_FLAG_RSSI_VALID. */
#define CS_PROTOCOL_CS_RSSI_NA UINT8_C(0x7f)
/** HCI time difference not available; on the wire see @ref CS_PROTOCOL_CS_STEP_FLAG_TIME_DIFFERENCE_VALID. */
#define CS_PROTOCOL_CS_TIME_DIFFERENCE_NA ((int16_t)0x8000)
/** @ref cs_protocol_cs_step_decoded_t.nadm unknown. */
#define CS_PROTOCOL_CS_NADM_UNKNOWN UINT8_C(0xff)
/** @c abort_step when the subevent was not aborted. */
#define CS_PROTOCOL_CS_ABORT_STEP_UNUSED UINT8_C(0xff)
/** @} */

/**
 * @name Step flags
 * Bits of @ref cs_protocol_cs_step_decoded_t.flags. A clear bit means the
 * controller reported the field as unavailable and its value is zero.
 * @{
 */
/** @c rssi is valid. */
#define CS_PROTOCOL_CS_STEP_FLAG_RSSI_VALID UINT8_C(0x01)
/** @c measured_freq_offset is valid. */
#define CS_PROTOCOL_CS_STEP_FLAG_FREQ_OFFSET_VALID UINT8_C(0x02)
/** @c time_difference is valid. */
#define CS_PROTOCOL_CS_STEP_FLAG_TIME_DIFFERENCE_VALID UINT8_C(0x04)
/** @c pct1_i, @c pct1_q, @c pct2_i and @c pct2_q are valid. */
#define CS_PROTOCOL_CS_STEP_FLAG_PCT_VALID UINT8_C(0x08)
/** @} */

/** @} */

/**
 * @defgroup cs_protocol_steps Decoded step records
 * @brief Step encoding used in subevent result @c step_data.
 *
 * The device resolves the HCI step layout (role, RTT type and antenna path
 * count are known there) and ships values rather than raw HCI bytes, so the
 * receiver never has to guess a layout from a length. Nibble-packed HCI
 * indicators are expanded to whole bytes and "not available" sentinels become
 * @c flags bits. Multi-byte fields are little endian.
 *
 * Each record is self-delimiting: its total size is
 * sizeof(struct cs_protocol_cs_step_decoded_t) +
 * @c num_tones * sizeof(struct cs_protocol_cs_tone_decoded_t).
 * @{
 */

/** @brief One PBR tone measurement, 8 bytes. */
struct cs_protocol_cs_tone_decoded_t {
	/** In-phase term, sign-extended from 12 bits. */
	int16_t i;
	/** Quadrature term, sign-extended from 12 bits. */
	int16_t q;
	/** Antenna path this tone belongs to, resolved through the permutation. */
	uint8_t antenna_path;
	/** Tone quality indicator, as reported by HCI. */
	uint8_t quality;
	/** Tone extension indicator, as reported by HCI. */
	uint8_t extension;
	/** Reserved; zero. */
	uint8_t reserved;
} __attribute__((__packed__));

/**
 * @brief Fixed part of one decoded CS step, 22 bytes, followed by its tones.
 *
 * Fields that do not apply to the step's @c mode carry no information.
 */
struct cs_protocol_cs_step_decoded_t {
	/** Step mode, one of @ref cs_protocol_cs_step_mode_t. */
	uint8_t mode;
	/** CS channel index; the step frequency is 2402 + @c channel MHz. */
	uint8_t channel;
	/** Validity bits, see @ref CS_PROTOCOL_CS_STEP_FLAG_RSSI_VALID and following. */
	uint8_t flags;
	/** Access-address check result, expanded from its nibble. Modes 0, 1, 3. */
	uint8_t aa_quality;
	/** Access-address bit error count, expanded from its nibble. Modes 0, 1, 3. */
	uint8_t bit_errors;
	/** Packet RSSI in dBm. Modes 0, 1, 3. */
	int8_t rssi;
	/** Antenna the packet was received on. Modes 0, 1, 3. */
	uint8_t antenna;
	/** Normalized attack detector metric, or @ref CS_PROTOCOL_CS_NADM_UNKNOWN. Modes 1, 3. */
	uint8_t nadm;
	/** Measured frequency offset, as reported by HCI. Mode 0, initiator only. */
	uint16_t measured_freq_offset;
	/**
	 * Round-trip time difference, as reported by HCI: ToA-ToD for the
	 * initiator, ToD-ToA for the reflector. Modes 1, 3.
	 */
	int16_t time_difference;
	/** First packet phase correction term, in-phase. Modes 1, 3 with sounding RTT. */
	int16_t pct1_i;
	/** First packet phase correction term, quadrature. */
	int16_t pct1_q;
	/** Second packet phase correction term, in-phase. */
	int16_t pct2_i;
	/** Second packet phase correction term, quadrature. */
	int16_t pct2_q;
	/** Raw antenna path permutation index, as reported. Modes 2, 3. */
	uint8_t antenna_permutation_index;
	/** Entries in @c tones: antenna paths plus the extension slot; 0 for modes 0, 1. */
	uint8_t num_tones;
	/** Tone records. */
	struct cs_protocol_cs_tone_decoded_t tones[];
} __attribute__((__packed__));

_Static_assert(sizeof(struct cs_protocol_cs_tone_decoded_t) == 8U,
               "CS decoded tone must be packed");
_Static_assert(sizeof(struct cs_protocol_cs_step_decoded_t) == 22U,
               "CS decoded step header must be packed");
/* Tone entries follow the header directly, so both sizes must stay even to
 * keep every 16-bit field on an even offset within the frame payload.
 */
_Static_assert(sizeof(struct cs_protocol_cs_step_decoded_t) % 2U == 0U,
               "CS decoded step header must keep tone entries 16-bit aligned");

/** @} */

/**
 * @defgroup cs_protocol_client_frames Client -> host frames
 * @brief Session responses, reports of controller events, CS results and log text.
 *
 * Variable-length frames declare only their fixed prefix and a flexible
 * array; C cannot place a member after it. Their @ref cs_protocol_footer_t
 * follows the data at offset @c header.size - @ref CS_PROTOCOL_FOOTER_SIZE,
 * and @c sizeof is the fixed prefix only. Allocate room for the data and
 * footer.
 * @{
 */

/**
 * @brief @ref CS_PROTOCOL_PACKET_CS_CAPABILITIES, 49 bytes.
 *
 * Local or remote CS capabilities as reported by the controller.
 */
struct cs_protocol_cs_capabilities_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Whose capabilities these are, one of @ref cs_protocol_cs_capabilities_source_t. */
	uint8_t source;
	/** Connection index of a remote report, or @ref CS_PROTOCOL_CS_CAPABILITIES_CONN_NONE. */
	uint8_t conn_index;
	/** Number of CS configurations supported. */
	uint8_t num_config_supported;
	/** Maximum consecutive CS procedures; 0 means fixed and indefinite counts are supported. */
	uint16_t max_consecutive_procedures_supported;
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
	/** RTT AA-only precision, as reported by HCI. */
	uint8_t rtt_aa_only_precision;
	/** RTT sounding precision, as reported by HCI. */
	uint8_t rtt_sounding_precision;
	/** RTT random payload precision, as reported by HCI. */
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
	/** Optional T_IP1 durations, bits 0-6: 10, 20, 30, 40, 50, 60, 80 us. */
	uint16_t t_ip1_times_supported;
	/** Optional T_IP2 durations, bits 0-6: 10, 20, 30, 40, 50, 60, 80 us. */
	uint16_t t_ip2_times_supported;
	/** Optional T_FCS durations, bits 0-8: 15, 20, 30, 40, 50, 60, 80, 100, 120 us. */
	uint16_t t_fcs_times_supported;
	/** Optional T_PM durations, bits 0-1: 10, 20 us. */
	uint16_t t_pm_times_supported;
	/** Antenna switch period of the CS tones, in microseconds. */
	uint8_t t_sw_time;
	/** Supported RTT SNR levels, bits 0-4: 18, 21, 24, 27, 30 dB. */
	uint8_t tx_snr_capability;
	/** T_IP2 durations supported with IPT, bits 0-6: 10, 20, 30, 40, 50, 60, 80 us. */
	uint16_t t_ip2_ipt_times_supported;
	/** Antenna switch period of the CS tones during IPT: 0, 1, 2, 4 or 10 us. */
	uint8_t t_sw_ipt_time_supported;
	/** 1 when the controller supports IPT as CS reflector. */
	uint8_t cs_ipt_reflector_supported;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_cs_capabilities_frame_t) == 49U,
               "cs_capabilities frame size");
_Static_assert(offsetof(struct cs_protocol_cs_capabilities_frame_t,
                        footer) == 43U,
               "cs_capabilities footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CS_CONFIGURATION, 40 bytes.
 *
 * CS configuration as completed by the controller.
 */
struct cs_protocol_cs_configuration_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** CS configuration ID, 0..@ref CS_PROTOCOL_CONFIG_ID_MAX. */
	uint8_t id;
	/** Main mode and sub-mode, one of @ref cs_protocol_config_mode. */
	uint8_t mode;
	/** Minimum main-mode steps before a sub-mode step. */
	uint8_t min_main_mode_steps;
	/** Maximum main-mode steps before a sub-mode step. */
	uint8_t max_main_mode_steps;
	/** Main-mode steps repeated from the end of the previous subevent. */
	uint8_t main_mode_repetition;
	/** Mode-0 steps at the start of each subevent. */
	uint8_t mode_0_steps;
	/** Local CS role, one of @ref cs_protocol_cs_role_t. */
	uint8_t role;
	/** RTT type, one of @ref cs_protocol_config_rtt_type. */
	uint8_t rtt_type;
	/** CS_SYNC PHY, one of @ref cs_protocol_config_sync_phy. */
	uint8_t cs_sync_phy;
	/** Times the channel map is cycled through for non-mode-0 steps. */
	uint8_t channel_map_repetition;
	/** Channel selection algorithm, one of @ref cs_protocol_config_chsel_type. */
	uint8_t channel_selection_type;
	/** Channel selection 3c shape, one of @ref cs_protocol_config_ch3c_shape. */
	uint8_t ch3c_shape;
	/** Channels skipped in each channel selection 3c rising/falling sequence. */
	uint8_t ch3c_jump;
	/** CS enhancements 1 bits, e.g. @ref CS_PROTOCOL_CONFIG_ENHANCEMENTS_1_IPT. */
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
	uint8_t channel_map[10];
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_cs_configuration_frame_t) == 40U,
               "cs_configuration frame size");
_Static_assert(offsetof(struct cs_protocol_cs_configuration_frame_t,
                        footer) == 34U,
               "cs_configuration footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CS_PROCEDURE_ENABLE_COMPLETE, 31 bytes.
 *
 * Procedure parameters selected by the controller when procedures are
 * enabled. A disable report carries only @c config_id and @c state; the other
 * fields are zero.
 */
struct cs_protocol_cs_procedure_enable_complete_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** CS configuration ID, 0..@ref CS_PROTOCOL_CONFIG_ID_MAX. */
	uint8_t config_id;
	/** Procedure state: 0 disabled, 1 enabled. */
	uint8_t state;
	/** Tone antenna configuration index, one of @ref cs_protocol_config_tone_antenna. */
	uint8_t tone_antenna_config_selection;
	/** Selected TX power in dBm, or @ref CS_PROTOCOL_CS_TX_POWER_NA. */
	int8_t selected_tx_power;
	/** Duration of each subevent, microseconds. */
	uint32_t subevent_len;
	/** Subevents anchored off the same ACL connection event, 1..32. */
	uint8_t subevents_per_event;
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
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_cs_procedure_enable_complete_frame_t) == 31U,
               "cs_procedure_enable_complete frame size");
_Static_assert(offsetof(struct cs_protocol_cs_procedure_enable_complete_frame_t,
                        footer) == 25U,
               "cs_procedure_enable_complete footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CS_INITIATOR_SUBEVENT_RESULT, variable size.
 *
 * One subevent's results measured by the initiator. @c step_data holds
 * @c num_steps_reported @ref cs_protocol_cs_step_decoded_t records, each
 * followed by its tones. The footer follows @c step_data. Fixed prefix is
 * 21 bytes.
 */
struct cs_protocol_cs_initiator_subevent_result_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** CS configuration ID, 0..@ref CS_PROTOCOL_CONFIG_ID_MAX. */
	uint8_t config_id;
	/** ACL connection event the procedure started in. */
	uint16_t start_acl_conn_event;
	/** CS procedure counter these results belong to. */
	uint16_t procedure_counter;
	/** Frequency compensation in 0.01 ppm, or @ref CS_PROTOCOL_CS_FREQ_COMPENSATION_NA. */
	uint16_t frequency_compensation;
	/** Reference power level in dBm, or @ref CS_PROTOCOL_CS_REF_POWER_LEVEL_NA. */
	int8_t reference_power_level;
	/** One of @ref cs_protocol_cs_procedure_status_t. */
	uint8_t procedure_done_status;
	/** One of @ref cs_protocol_cs_subevent_status_t. */
	uint8_t subevent_done_status;
	/** One of @ref cs_protocol_cs_procedure_abort_reason_t. */
	uint8_t procedure_abort_reason;
	/** One of @ref cs_protocol_cs_subevent_abort_reason_t. */
	uint8_t subevent_abort_reason;
	/** Antenna paths used for tones, 1..4; 0 without phase measurement (mode 1 only). */
	uint8_t num_antenna_paths;
	/** Number of step records in @c step_data. */
	uint8_t num_steps_reported;
	/** Step the subevent was aborted on, or @ref CS_PROTOCOL_CS_ABORT_STEP_UNUSED. */
	uint8_t abort_step;
	/** Concatenated step records; footer follows. */
	uint8_t step_data[];
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_cs_initiator_subevent_result_frame_t) == 21U,
               "Subevent frame prefix size");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CS_REFLECTOR_SUBEVENT_RESULT, variable size.
 *
 * Same layout and step encoding as
 * @ref cs_protocol_cs_initiator_subevent_result_frame_t, for results measured
 * by the reflector. Fixed prefix is 21 bytes.
 */
struct cs_protocol_cs_reflector_subevent_result_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** CS configuration ID, 0..@ref CS_PROTOCOL_CONFIG_ID_MAX. */
	uint8_t config_id;
	/** ACL connection event the procedure started in. */
	uint16_t start_acl_conn_event;
	/** CS procedure counter these results belong to. */
	uint16_t procedure_counter;
	/** Frequency compensation in 0.01 ppm, or @ref CS_PROTOCOL_CS_FREQ_COMPENSATION_NA. */
	uint16_t frequency_compensation;
	/** Reference power level in dBm, or @ref CS_PROTOCOL_CS_REF_POWER_LEVEL_NA. */
	int8_t reference_power_level;
	/** One of @ref cs_protocol_cs_procedure_status_t. */
	uint8_t procedure_done_status;
	/** One of @ref cs_protocol_cs_subevent_status_t. */
	uint8_t subevent_done_status;
	/** One of @ref cs_protocol_cs_procedure_abort_reason_t. */
	uint8_t procedure_abort_reason;
	/** One of @ref cs_protocol_cs_subevent_abort_reason_t. */
	uint8_t subevent_abort_reason;
	/** Antenna paths used for tones, 1..4; 0 without phase measurement (mode 1 only). */
	uint8_t num_antenna_paths;
	/** Number of step records in @c step_data. */
	uint8_t num_steps_reported;
	/** Step the subevent was aborted on, or @ref CS_PROTOCOL_CS_ABORT_STEP_UNUSED. */
	uint8_t abort_step;
	/** Concatenated step records; footer follows. */
	uint8_t step_data[];
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_cs_reflector_subevent_result_frame_t) == 21U,
               "Subevent frame prefix size");

/**
 * @brief @ref CS_PROTOCOL_PACKET_LOG_MESSAGE, variable size.
 *
 * Diagnostic text from the client, "<lvl> module: text" with lvl one of err,
 * wrn, inf, dbg. Sent for messages at or below the applied protocol level
 * (@ref cs_protocol_log_config_frame_t). Fixed prefix is 6 bytes.
 */
struct cs_protocol_log_message_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** @c header.size - @ref CS_PROTOCOL_OVERHEAD bytes of text, no terminating NUL; footer follows. */
	uint8_t message[];
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_log_message_frame_t) == 6U,
               "Log frame prefix size");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CONNECT_RESPONSE, 30 bytes.
 *
 * Answer to CONNECT. With @c status @ref CS_PROTOCOL_STATUS_OK the host
 * session is open; the remaining fields describe the client and the
 * configuration it holds.
 */
struct cs_protocol_connect_response_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** One of @ref cs_protocol_status. */
	uint8_t status;
	/** Client protocol version, @ref CS_PROTOCOL_VERSION. */
	uint16_t protocol_version;
	/** Supported operation modes, bits @ref CS_PROTOCOL_MODE_BIT. */
	uint8_t supported_modes;
	/** Firmware version. */
	uint32_t firmware_version;
	/** Largest frame the client accepts, in bytes. */
	uint16_t max_frame_size;
	/** 1 when an applied configuration is held. */
	uint8_t config_valid;
	/** Applied operation mode, or @ref CS_PROTOCOL_MODE_NONE. */
	uint8_t operation_mode;
	/** CRC of the applied configuration; 0 when none. */
	uint32_t config_crc32;
	/** Current state, one of @ref cs_protocol_client_state. */
	uint8_t client_state;
	/** Maximum local antenna count from the board build configuration. */
	uint8_t num_antennas_supported;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_connect_response_frame_t) == 30U,
               "connect_response frame size");
_Static_assert(offsetof(struct cs_protocol_connect_response_frame_t,
                        footer) == 24U,
               "connect_response footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_COMMAND_RESPONSE, 24 bytes.
 *
 * Answer to every host command except CONNECT.
 */
struct cs_protocol_command_response_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** ID of the command answered, one of @ref cs_protocol_packet_type_t. */
	uint16_t request_type;
	/** One of @ref cs_protocol_status. */
	uint8_t status;
	/** One of @ref cs_protocol_reject_reason. */
	uint8_t reason;
	/** Negative errno from the setter, apply, start or stop call; 0 on success. */
	int32_t error;
	/** CRC of the applied configuration after the command; 0 when none. */
	uint32_t config_crc32;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_command_response_frame_t) == 24U,
               "command_response frame size");
_Static_assert(offsetof(struct cs_protocol_command_response_frame_t,
                        footer) == 18U,
               "command_response footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CS_FAE_TABLE, 86 bytes.
 *
 * One remote FAE table read completion event (initiator role only).
 */
struct cs_protocol_cs_fae_table_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** HCI status of the read; 0 on success. */
	uint8_t hci_status;
	/** Scale of @c entries: ppm = entry / @c lsb_denominator. */
	uint8_t lsb_denominator;
	/** Entries in HCI table order; all zero when @c hci_status is not 0. */
	int8_t entries[CS_PROTOCOL_FAE_TABLE_ENTRIES];
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_cs_fae_table_frame_t) == 86U,
               "cs_fae_table frame size");
_Static_assert(offsetof(struct cs_protocol_cs_fae_table_frame_t,
                        footer) == 80U,
               "cs_fae_table footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CLIENT_STATE, 20 bytes.
 *
 * Unsolicited client state change. Protocol version 0x0002 sent this frame
 * without @c error (16 bytes).
 */
struct cs_protocol_client_state_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** New state, one of @ref cs_protocol_client_state. */
	uint8_t state;
	/** Operation mode, or @ref CS_PROTOCOL_MODE_NONE. */
	uint8_t operation_mode;
	/** One of @ref cs_protocol_reject_reason. */
	uint8_t reason;
	/** HCI status that caused the change; 0 when none. */
	uint8_t hci_status;
	/**
	 * Negative errno when the change ends an operation abnormally, 0 otherwise:
	 * -ECANCELED for STOP before a finite test completed or CLOSE_SESSION while
	 * running, -ENOTCONN for a lost host port while running, or the error of a
	 * failed driver or controller call.
	 */
	int32_t error;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_client_state_frame_t) == 20U,
               "client_state frame size");
_Static_assert(offsetof(struct cs_protocol_client_state_frame_t,
                        footer) == 14U,
               "client_state footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_RAS_DATA_LOST, 16 bytes.
 *
 * Unsolicited: real-time RAS data of one procedure was not received.
 */
struct cs_protocol_ras_data_lost_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** RAS ranging counter of the lost procedure. */
	uint16_t ranging_counter;
	/** Negative errno from the RAS data callback. */
	int16_t error;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_ras_data_lost_frame_t) == 16U,
               "ras_data_lost frame size");
_Static_assert(offsetof(struct cs_protocol_ras_data_lost_frame_t,
                        footer) == 10U,
               "ras_data_lost footer offset");

/** RADIO_TEST_STATS.rssi_dbm when no packet was received since the previous report. */
#define CS_PROTOCOL_RSSI_UNAVAILABLE 127

/**
 * @brief @ref CS_PROTOCOL_PACKET_RADIO_TEST_STATS, 22 bytes.
 *
 * Unsolicited receive statistics of a running radio RX or RX sweep test.
 * The client sends a baseline after the START response, a report
 * periodically while the test runs, and a final report before the STOP
 * response or before CLIENT_STATE(STOPPED, TEST_COMPLETE). Other radio test
 * types send none.
 *
 * Counters are cumulative since START, across all sweep channels, and wrap
 * modulo 2^32; the host derives rates from differences between reports.
 */
struct cs_protocol_radio_test_stats_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Packets received with a valid CRC since START. */
	uint32_t packets_received;
	/** Packets received with a failed CRC since START. */
	uint32_t crc_errors;
	/**
	 * RSSI in dBm of the latest packet (valid or failed CRC) since the
	 * previous report, or @ref CS_PROTOCOL_RSSI_UNAVAILABLE.
	 */
	int8_t rssi_dbm;
	/**
	 * Channel of that packet (2400 + channel MHz, or the IEEE 802.15.4
	 * channel for that PHY); the tuned channel when no packet was received.
	 */
	uint8_t channel;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_radio_test_stats_frame_t) == 22U,
               "radio_test_stats frame size");
_Static_assert(offsetof(struct cs_protocol_radio_test_stats_frame_t,
                        footer) == 16U,
               "radio_test_stats footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CS_PROCEDURES_COMPLETE, 14 bytes.
 *
 * Unsolicited: the CS procedures of the run ended on their own, because the
 * initiator's controller completed @c max_procedure_count. Sent by the CS
 * initiator after the last procedure's RAS data arrived or timed out, right
 * before CLIENT_STATE(STOPPED, TEST_COMPLETE). Not sent after STOP. Added in
 * protocol version 0x0006.
 */
struct cs_protocol_cs_procedures_complete_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/**
	 * Procedures of this run whose last subevent reported procedure done
	 * status complete (aborted procedures are not counted).
	 */
	uint16_t procedures_completed;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_cs_procedures_complete_frame_t) == 14U,
               "cs_procedures_complete frame size");
_Static_assert(offsetof(struct cs_protocol_cs_procedures_complete_frame_t,
                        footer) == 8U,
               "cs_procedures_complete footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CS_PEER_DATA, 13 bytes.
 *
 * Unsolicited: the data the CS initiator receives from the reflector on this
 * link. Sent by the initiator at CS configuration complete, before the first
 * subevent; the hostless initiator also resends it with its other link
 * records when the host opens the port. A hostless host has no applied
 * configuration, and the controller's configuration report does not carry
 * this setting. Added in protocol version 0x0007.
 */
struct cs_protocol_cs_peer_data_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** One of @ref cs_protocol_peer_data. */
	uint8_t peer_data;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_cs_peer_data_frame_t) == 13U,
               "cs_peer_data frame size");
_Static_assert(offsetof(struct cs_protocol_cs_peer_data_frame_t, footer) == 7U,
               "cs_peer_data footer offset");

/**
 * @brief @ref CS_PROTOCOL_PACKET_CONNECTION_PARAMETERS, 20 bytes.
 *
 * Unsolicited: the negotiated ACL connection parameters of the current
 * Bluetooth link. The host receives this report when its USB session opens;
 * the hostless initiator resends the latest value when USB DTR rises.
 * Added in protocol version 0x000A; the MTU field was added in 0x000B.
 */
struct cs_protocol_connection_parameters_frame_t {
	/** Common header. */
	struct cs_protocol_header_t header;
	/** Negotiated connection interval, 1.25 ms units. */
	uint16_t interval;
	/** Negotiated peripheral latency, ACL events. */
	uint16_t latency;
	/** Negotiated supervision timeout, 10 ms units. */
	uint16_t timeout;
	/** Negotiated ATT MTU, in bytes. */
	uint16_t mtu;
	/** Common footer. */
	struct cs_protocol_footer_t footer;
} __attribute__((__packed__));
_Static_assert(sizeof(struct cs_protocol_connection_parameters_frame_t) == 20U,
               "connection_parameters frame size");
_Static_assert(offsetof(struct cs_protocol_connection_parameters_frame_t,
                        footer) == 14U,
               "connection_parameters footer offset");

/** @} */

/** @} */

#ifdef __cplusplus
}
#endif

#endif /* CS_PROTOCOL_PACKETS_H_ */
