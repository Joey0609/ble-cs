/* SPDX-License-Identifier: MIT */

/**
 * @file
 * @brief Configuration payloads -> cs_utils records and radio test settings.
 *
 * Every value goes through the same setter or check the hostless applications
 * use, so a payload is accepted exactly when its values are. The errno of the
 * first failing setter is returned for COMMAND_RESPONSE.error.
 */

#ifndef HOST_LINK_CONFIG_H_
#define HOST_LINK_CONFIG_H_

#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "cs_protocol/cs_protocol_packets.h"
#include "host_link_types.h"

#ifdef __cplusplus
extern "C" {
#endif

struct cs_initiator_config;
struct cs_reflector_config;
struct radio_test_mode_config;

/**
 * @brief GAP role of a CS configuration payload.
 * @return One of @ref cs_protocol_gap_role_t (first byte of both CS payloads).
 */
static inline uint8_t host_link_config_gap_role(const uint8_t *payload) {
	return payload[0];
}

/**
 * @brief Check the antenna selections of a CS configuration against the local antennas.
 *
 * The local side of @p tone_antenna_config_selection is A (initiator antennas)
 * in the initiator role and B (reflector antennas) in the reflector role; the
 * peer's side is only known after connecting and is left to the controller.
 * A @p cs_sync_antenna_selection of 1..4 names a local antenna; repetitive and
 * no recommendation are always accepted. The limit is the count reported in
 * CONNECT_RESPONSE.num_antennas_supported, so the host can apply the same rule.
 *
 * @param mode CS_PROTOCOL_MODE_CS_INITIATOR or CS_PROTOCOL_MODE_CS_REFLECTOR.
 * @param cs_sync_antenna_selection One of @ref cs_protocol_config_sync_antenna.
 * @param tone_antenna_config_selection One of @ref cs_protocol_config_tone_antenna.
 * @param num_antennas Local antenna count, 1..4.
 * @retval 0 Both selections fit the local antennas.
 * @retval -EINVAL A selection is not a defined encoding.
 * @retval -ERANGE A selection needs more local antennas than @p num_antennas.
 */
static inline int host_link_config_check_antennas(uint8_t mode, uint8_t cs_sync_antenna_selection,
                                                  uint8_t tone_antenna_config_selection,
                                                  uint8_t num_antennas) {
	/* (initiator, reflector) antennas per tone antenna configuration index. */
	static const uint8_t tone_antennas[][2] = {
		{1, 1}, {2, 1}, {3, 1}, {4, 1}, {1, 2}, {1, 3}, {1, 4}, {2, 2},
	};
	bool sync_named = cs_sync_antenna_selection >= CS_PROTOCOL_CONFIG_SYNC_ANTENNA_ONE &&
	                  cs_sync_antenna_selection <= CS_PROTOCOL_CONFIG_SYNC_ANTENNA_FOUR;

	if ((!sync_named && cs_sync_antenna_selection != CS_PROTOCOL_CONFIG_SYNC_ANTENNA_REPETITIVE &&
	     cs_sync_antenna_selection != CS_PROTOCOL_CONFIG_SYNC_ANTENNA_NO_RECOMMENDATION) ||
	    tone_antenna_config_selection >= sizeof(tone_antennas) / sizeof(tone_antennas[0]) ||
	    (mode != CS_PROTOCOL_MODE_CS_INITIATOR && mode != CS_PROTOCOL_MODE_CS_REFLECTOR)) {
		return -EINVAL;
	}
	if ((sync_named && cs_sync_antenna_selection > num_antennas) ||
	    tone_antennas[tone_antenna_config_selection][mode == CS_PROTOCOL_MODE_CS_REFLECTOR] > num_antennas) {
		return -ERANGE;
	}
	return 0;
}

/**
 * @brief SET_CS_INITIATOR_CONFIG payload -> initiator record.
 *
 * Antenna selections are checked against CONFIG_APP_HOST_LINK_NUM_ANTENNAS with
 * host_link_config_check_antennas().
 * @retval 0 Converted; @p config holds every field.
 * @retval -EMSGSIZE @p len is not the initiator payload size.
 * @retval -EINVAL A value is refused (GAP role, IPT bits, antenna encoding, or a cs_utils setter).
 * @retval -ERANGE An antenna selection needs more local antennas than the build has.
 */
int host_link_config_to_initiator(const uint8_t *payload, size_t len,
                                  struct cs_initiator_config *config);

/**
 * @brief CS initiator configuration set -> initiator record.
 *
 * Converts the configuration payload with host_link_config_to_initiator(),
 * applies SET_PEER_DATA with cs_initiator_config_set_peer_data() (RAS
 * real-time without it) and SET_T_PM with cs_initiator_config_set_t_pm()
 * (10 us without it), and checks the result with
 * cs_initiator_config_check_peer_data().
 * @retval 0 Converted.
 * @retval -EINVAL The set is not a CS initiator set, a value is refused, or
 *         reflector data none is set without the IPT request.
 * @return Other errors as host_link_config_to_initiator().
 */
int host_link_config_set_to_initiator(const struct host_link_config_set *set,
                                      struct cs_initiator_config *config);

/**
 * @brief SET_CS_REFLECTOR_CONFIG payload -> reflector record.
 *
 * Antenna selections are checked as for host_link_config_to_initiator().
 * @retval 0 Converted.
 * @retval -EMSGSIZE @p len is not the reflector payload size.
 * @retval -EINVAL A value is refused.
 * @retval -ERANGE An antenna selection needs more local antennas than the build has.
 */
int host_link_config_to_reflector(const uint8_t *payload, size_t len,
                                  struct cs_reflector_config *config);

/**
 * @brief SET_RADIO_TX_TEST_CONFIG payload -> radio test settings.
 *
 * @c done_cb is left NULL. The settings are checked with
 * radio_test_mode_config_validate().
 * @retval 0 Converted and valid.
 * @retval -EMSGSIZE @p len is not the radio test payload size.
 * @retval -EINVAL A value is refused.
 * @retval -ENOTSUP The PHY is not available on this SoC.
 */
int host_link_config_to_radio_test(const uint8_t *payload, size_t len,
                                   struct radio_test_mode_config *config);

#ifdef __cplusplus
}
#endif

#endif /* HOST_LINK_CONFIG_H_ */
