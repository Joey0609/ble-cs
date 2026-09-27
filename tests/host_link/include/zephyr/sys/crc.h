/* SPDX-License-Identifier: MIT */
/* Test-only substitute for Zephyr crc32_ieee() and crc32_ieee_update() (CRC-32/IEEE, reflected, poly 0xEDB88320). */
#ifndef TEST_ZEPHYR_SYS_CRC_H_
#define TEST_ZEPHYR_SYS_CRC_H_

#include <stddef.h>
#include <stdint.h>

static inline uint32_t crc32_ieee(const uint8_t *data, size_t len) {
	uint32_t crc = 0xFFFFFFFFU;

	for (size_t i = 0; i < len; i++) {
		crc ^= data[i];
		for (int bit = 0; bit < 8; bit++) {
			crc = (crc >> 1) ^ (0xEDB88320U & (0U - (crc & 1U)));
		}
	}
	return ~crc;
}

static inline uint32_t crc32_ieee_update(uint32_t crc, const uint8_t *data, size_t len) {
	crc = ~crc;
	for (size_t i = 0; i < len; i++) {
		crc ^= data[i];
		for (int bit = 0; bit < 8; bit++) {
			crc = (crc >> 1) ^ (0xEDB88320U & (0U - (crc & 1U)));
		}
	}
	return ~crc;
}

#endif
