/* SPDX-License-Identifier: MIT */
/* Test-only substitute for the Zephyr byte-order helpers used by cs_protocol.c. */
#ifndef TEST_ZEPHYR_SYS_BYTEORDER_H_
#define TEST_ZEPHYR_SYS_BYTEORDER_H_

#include <stdint.h>

static inline uint16_t sys_le16_to_cpu(uint16_t value) {
	const uint8_t *bytes = (const uint8_t *)&value;

	return (uint16_t)(bytes[0] | (bytes[1] << 8));
}

static inline uint32_t sys_le32_to_cpu(uint32_t value) {
	const uint8_t *bytes = (const uint8_t *)&value;

	return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) | ((uint32_t)bytes[2] << 16) |
	       ((uint32_t)bytes[3] << 24);
}

/* The conversions are their own inverses. */
#define sys_cpu_to_le16(value) sys_le16_to_cpu(value)
#define sys_cpu_to_le32(value) sys_le32_to_cpu(value)

static inline void sys_put_le16(uint16_t value, uint8_t dst[2]) {
	dst[0] = (uint8_t)value;
	dst[1] = (uint8_t)(value >> 8);
}

static inline void sys_put_le32(uint32_t value, uint8_t dst[4]) {
	sys_put_le16((uint16_t)value, dst);
	sys_put_le16((uint16_t)(value >> 16), &dst[2]);
}

static inline uint16_t sys_get_le16(const uint8_t src[2]) {
	return (uint16_t)(src[0] | (src[1] << 8));
}

static inline uint32_t sys_get_le32(const uint8_t src[4]) {
	return (uint32_t)sys_get_le16(src) | ((uint32_t)sys_get_le16(&src[2]) << 16);
}

#endif
