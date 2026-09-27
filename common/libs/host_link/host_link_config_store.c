/* SPDX-License-Identifier: MIT */
#include <errno.h>
#include <stddef.h>
#include <string.h>

#include "host_link_config_store.h"

#define PATTERN_SLOTS 8U
#define PATTERN_SIZE 32U

/* Offsets inside the SET_PERIPHERAL_PATTERNS payload. */
#define PATTERNS_COUNT_OFFSET 0U
#define PATTERNS_LENGTHS_OFFSET 1U
#define PATTERNS_DATA_OFFSET (PATTERNS_LENGTHS_OFFSET + PATTERN_SLOTS)

/* Offsets inside the SET_LOG_CONFIG payload. */
#define LOG_CONFIG_CONSOLE_OFFSET \
	(offsetof(struct cs_protocol_log_config_frame_t, console_level) - CS_PROTOCOL_HEADER_SIZE)
#define LOG_CONFIG_PROTOCOL_OFFSET \
	(offsetof(struct cs_protocol_log_config_frame_t, protocol_level) - CS_PROTOCOL_HEADER_SIZE)

_Static_assert(HOST_LINK_PATTERNS_PAYLOAD_SIZE == PATTERNS_DATA_OFFSET + PATTERN_SLOTS * PATTERN_SIZE,
               "Peripheral patterns payload layout");
_Static_assert(HOST_LINK_CONFIG_PAYLOAD_MAX >= HOST_LINK_REFLECTOR_PAYLOAD_SIZE &&
                       HOST_LINK_CONFIG_PAYLOAD_MAX >= HOST_LINK_RADIO_TEST_PAYLOAD_SIZE,
               "Configuration payload storage");

void host_link_config_store_init(struct host_link_config_store *store) {
	memset(store, 0, sizeof(*store));
}

int host_link_config_mode_of_type(uint16_t type) {
	switch (type) {
	case CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG:
		return CS_PROTOCOL_MODE_CS_INITIATOR;
	case CS_PROTOCOL_PACKET_SET_CS_REFLECTOR_CONFIG:
		return CS_PROTOCOL_MODE_CS_REFLECTOR;
	case CS_PROTOCOL_PACKET_SET_RADIO_TX_TEST_CONFIG:
		return CS_PROTOCOL_MODE_RADIO_TX_TEST;
	default:
		return -1;
	}
}

uint16_t host_link_config_type_of_mode(uint8_t mode, size_t *payload_len) {
	switch (mode) {
	case CS_PROTOCOL_MODE_CS_INITIATOR:
		*payload_len = HOST_LINK_INITIATOR_PAYLOAD_SIZE;
		return CS_PROTOCOL_PACKET_SET_CS_INITIATOR_CONFIG;
	case CS_PROTOCOL_MODE_CS_REFLECTOR:
		*payload_len = HOST_LINK_REFLECTOR_PAYLOAD_SIZE;
		return CS_PROTOCOL_PACKET_SET_CS_REFLECTOR_CONFIG;
	case CS_PROTOCOL_MODE_RADIO_TX_TEST:
		*payload_len = HOST_LINK_RADIO_TEST_PAYLOAD_SIZE;
		return CS_PROTOCOL_PACKET_SET_RADIO_TX_TEST_CONFIG;
	default:
		*payload_len = 0U;
		return 0U;
	}
}

void host_link_config_stage_mode(struct host_link_config_store *store, uint8_t mode) {
	memset(&store->staged, 0, sizeof(store->staged));
	store->staged.has_mode = true;
	store->staged.mode = mode;
}

struct host_link_result host_link_config_check_config(const struct host_link_config_store *store,
                                                      uint16_t type) {
	if (!store->staged.has_mode) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
	}
	if (host_link_config_mode_of_type(type) != (int)store->staged.mode) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MODE_MISMATCH);
	}
	return HOST_LINK_RESULT_OK;
}

void host_link_config_stage_config(struct host_link_config_store *store, const uint8_t *payload,
                                   size_t len) {
	memcpy(store->staged.config, payload, len);
	store->staged.config_len = (uint8_t)len;
}

/* Well-formed UTF-8 (no overlong forms, surrogates or values above U+10FFFF). */
static bool utf8_valid(const uint8_t *s, size_t len) {
	size_t i = 0U;

	while (i < len) {
		uint8_t c = s[i];
		size_t extra;
		uint32_t min, cp;

		if (c < 0x80U) {
			i++;
			continue;
		} else if ((c & 0xE0U) == 0xC0U) {
			extra = 1U, min = 0x80U, cp = c & 0x1FU;
		} else if ((c & 0xF0U) == 0xE0U) {
			extra = 2U, min = 0x800U, cp = c & 0x0FU;
		} else if ((c & 0xF8U) == 0xF0U) {
			extra = 3U, min = 0x10000U, cp = c & 0x07U;
		} else {
			return false;
		}
		if (i + extra >= len) {
			return false;
		}
		for (size_t k = 1U; k <= extra; k++) {
			if ((s[i + k] & 0xC0U) != 0x80U) {
				return false;
			}
			cp = (cp << 6) | (s[i + k] & 0x3FU);
		}
		if (cp < min || cp > 0x10FFFFU || (cp >= 0xD800U && cp <= 0xDFFFU)) {
			return false;
		}
		i += extra + 1U;
	}
	return true;
}

struct host_link_result host_link_config_check_patterns(const struct host_link_config_store *store,
                                                        const uint8_t *payload) {
	const uint8_t count = payload[PATTERNS_COUNT_OFFSET];
	const uint8_t *lengths = &payload[PATTERNS_LENGTHS_OFFSET];
	bool nonzero_padding = false;

	if (!store->staged.has_mode) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
	}
	if (store->staged.mode == CS_PROTOCOL_MODE_RADIO_TX_TEST) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MODE_MISMATCH);
	}
	if (count < 1U || count > PATTERN_SLOTS) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	}

	for (uint8_t slot = 0U; slot < PATTERN_SLOTS; slot++) {
		const uint8_t *data = &payload[PATTERNS_DATA_OFFSET + slot * PATTERN_SIZE];
		const uint8_t length = slot < count ? lengths[slot] : 0U;

		if (slot < count) {
			if (length < 1U || length > PATTERN_SIZE || memchr(data, 0, length) != NULL ||
			    !utf8_valid(data, length)) {
				return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED,
				                        CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
			}
		} else if (lengths[slot] != 0U) {
			nonzero_padding = true;
		}
		for (size_t i = length; i < PATTERN_SIZE; i++) {
			nonzero_padding |= data[i] != 0U;
		}
	}
	if (nonzero_padding) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_NONZERO_PADDING);
	}
	return HOST_LINK_RESULT_OK;
}

struct host_link_result host_link_config_check_device_name(const struct host_link_config_store *store,
                                                          const uint8_t *payload) {
    uint8_t len = payload[0];
    if (!store->staged.has_mode || !store->staged.config_len) {
        return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
    }
    if (store->staged.mode == CS_PROTOCOL_MODE_RADIO_TX_TEST) {
        return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MODE_MISMATCH);
    }
    if (len < 1U || len > 32U || memchr(payload + 1, 0, len) || !utf8_valid(payload + 1, len)) {
        return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
    }
    for (size_t i = len + 1; i < HOST_LINK_DEVICE_NAME_PAYLOAD_SIZE; ++i) {
        if (payload[i]) {
            return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_NONZERO_PADDING);
        }
    }
    return HOST_LINK_RESULT_OK;
}

struct host_link_result host_link_config_check_peer_data(const struct host_link_config_store *store,
                                                         const uint8_t *payload) {
	if (!store->staged.has_mode) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
	}
	if (store->staged.mode != CS_PROTOCOL_MODE_CS_INITIATOR) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MODE_MISMATCH);
	}
	/* RAS real-time is the default without the frame: one representation per configuration. */
	if (payload[0] != CS_PROTOCOL_PEER_DATA_NONE) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	}
	return HOST_LINK_RESULT_OK;
}

void host_link_config_stage_peer_data(struct host_link_config_store *store, const uint8_t *payload) {
	store->staged.peer_data = payload[0];
	store->staged.has_peer_data = true;
}

struct host_link_result host_link_config_check_t_pm(const struct host_link_config_store *store,
                                                    const uint8_t *payload) {
	if (!store->staged.has_mode) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
	}
	if (store->staged.mode != CS_PROTOCOL_MODE_CS_INITIATOR) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MODE_MISMATCH);
	}
	/* 10 us is the preference without the frame: one representation per configuration. */
	if (payload[0] != CS_PROTOCOL_T_PM_20_US && payload[0] != CS_PROTOCOL_T_PM_40_US) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	}
	return HOST_LINK_RESULT_OK;
}

void host_link_config_stage_t_pm(struct host_link_config_store *store, const uint8_t *payload) {
	store->staged.t_pm_us = payload[0];
	store->staged.has_t_pm = true;
}

struct host_link_result host_link_config_check_log_config(const struct host_link_config_store *store,
                                                          const uint8_t *payload) {
	const uint8_t console = payload[LOG_CONFIG_CONSOLE_OFFSET];
	const uint8_t protocol = payload[LOG_CONFIG_PROTOCOL_OFFSET];

	if (!store->staged.has_mode) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_CONFIG);
	}
	if (console > CS_PROTOCOL_LOG_LEVEL_DEBUG || protocol > CS_PROTOCOL_LOG_LEVEL_DEBUG) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	}
	/* The defaults apply without the frame: one representation per configuration. */
	if (console == CS_PROTOCOL_LOG_CONSOLE_LEVEL_DEFAULT &&
	    protocol == CS_PROTOCOL_LOG_PROTOCOL_LEVEL_DEFAULT) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_VALUE_OUT_OF_RANGE);
	}
	return HOST_LINK_RESULT_OK;
}

void host_link_config_stage_log_config(struct host_link_config_store *store, const uint8_t *payload) {
	memcpy(store->staged.log_config, payload, HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE);
	store->staged.has_log_config = true;
}

void host_link_config_stage_patterns(struct host_link_config_store *store, const uint8_t *payload) {
	memcpy(store->staged.patterns, payload, HOST_LINK_PATTERNS_PAYLOAD_SIZE);
	store->staged.has_patterns = true;
}

struct host_link_result host_link_config_check_apply(const struct host_link_config_store *store) {
	const struct host_link_config_set *staged = &store->staged;
	size_t expected_len;

	if (!staged->has_mode || host_link_config_type_of_mode(staged->mode, &expected_len) == 0U ||
	    staged->config_len != expected_len) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_REJECTED, CS_PROTOCOL_REASON_MISSING_CONFIG);
	}
	/* gap_role is the first field of both CS configuration payloads. */
	if (staged->mode != CS_PROTOCOL_MODE_RADIO_TX_TEST &&
	    staged->config[0] == CS_PROTOCOL_GAP_CENTRAL && !staged->has_patterns) {
		return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MISSING_PATTERNS);
	}
	/* The same rule as cs_initiator_config_check_peer_data(), on the payload:
	 * SET_PEER_DATA is staged only in the initiator mode.
	 */
	if (staged->has_peer_data && staged->peer_data == CS_PROTOCOL_PEER_DATA_NONE &&
	    !(staged->config[offsetof(struct cs_protocol_cs_initiator_config_frame_t,
	                              creation_cs_enhancements_1) - CS_PROTOCOL_HEADER_SIZE] &
	      CS_PROTOCOL_CONFIG_ENHANCEMENTS_1_IPT)) {
		return HOST_LINK_RESULT_OUT_OF_RANGE(-EINVAL);
	}
	return HOST_LINK_RESULT_OK;
}

void host_link_config_commit(struct host_link_config_store *store) {
	store->applied = store->staged;
	store->applied_valid = true;
	store->applied_crc32 = host_link_config_crc32(&store->applied);
	memset(&store->staged, 0, sizeof(store->staged));
}

uint32_t host_link_config_crc32(const struct host_link_config_set *set) {
	uint8_t payloads[HOST_LINK_MODE_PAYLOAD_SIZE + HOST_LINK_CONFIG_PAYLOAD_MAX +
	                 HOST_LINK_PATTERNS_PAYLOAD_SIZE + HOST_LINK_DEVICE_NAME_PAYLOAD_SIZE +
	                 HOST_LINK_PEER_DATA_PAYLOAD_SIZE + HOST_LINK_T_PM_PAYLOAD_SIZE +
	                 HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE];
	size_t len = 0U;

	if (!set->has_mode || set->config_len == 0U) {
		return 0U;
	}
	payloads[len++] = set->mode;
	memcpy(&payloads[len], set->config, set->config_len);
	len += set->config_len;
	if (set->has_patterns) {
		memcpy(&payloads[len], set->patterns, HOST_LINK_PATTERNS_PAYLOAD_SIZE);
		len += HOST_LINK_PATTERNS_PAYLOAD_SIZE;
	}
	if (set->has_device_name) {
		memcpy(&payloads[len], set->device_name, HOST_LINK_DEVICE_NAME_PAYLOAD_SIZE);
		len += HOST_LINK_DEVICE_NAME_PAYLOAD_SIZE;
	}
	if (set->has_peer_data) {
		payloads[len++] = set->peer_data;
	}
	if (set->has_t_pm) {
		payloads[len++] = set->t_pm_us;
	}
	if (set->has_log_config) {
		memcpy(&payloads[len], set->log_config, HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE);
		len += HOST_LINK_LOG_CONFIG_PAYLOAD_SIZE;
	}
	return cs_protocol_crc32(payloads, len);
}
