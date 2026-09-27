/* SPDX-License-Identifier: MIT */
/* Weak defaults for cs_generated_config.h. A planner export linked into the
 * application defines the same symbols and replaces these.
 */
#include <errno.h>
#include <zephyr/toolchain.h>

#include "cs_generated_config.h"

__weak const uint32_t cs_generated_config_crc32_initiator = 0U;
__weak const uint32_t cs_generated_config_crc32_reflector = 0U;

__weak int cs_generated_config_initiator(struct cs_initiator_config *config) {
	int err = cs_initiator_config_get_default(config);

	return err ? err : -ENOENT;
}

__weak int cs_generated_config_reflector(struct cs_reflector_config *config) {
	int err = cs_reflector_config_get_default(config);

	return err ? err : -ENOENT;
}

__weak int cs_generated_config_patterns(const char *const **patterns,
                                        size_t *count) {
	if (!patterns || !count) {
		return -EINVAL;
	}
	*patterns = NULL;
	*count = 0U;
	return -ENOENT;
}

__weak int cs_generated_config_log(struct app_log_config *config) {
	if (!config) {
		return -EINVAL;
	}
	app_log_defaults(config);
	return -ENOENT;
}

__weak const char *cs_generated_config_device_name(void) {
	return NULL;
}
