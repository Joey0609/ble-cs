/* SPDX-License-Identifier: MIT */
/* cs_config.c needs the Zephyr Bluetooth headers; these stand-ins fill the
 * record header and one recognisable field, which is enough to check that the
 * weak defaults hand out what get_default produced.
 */
#include <errno.h>
#include <string.h>

#include "stub_cs_config.h"

int cs_initiator_config_get_default(struct cs_initiator_config *config) {
	if (!config) {
		return -EINVAL;
	}
	memset(config, 0, sizeof(*config));
	config->role = CS_CONFIG_ROLE_INITIATOR;
	config->size = sizeof(*config);
	config->connection.timeout = STUB_DEFAULT_TIMEOUT;
	return 0;
}

int cs_reflector_config_get_default(struct cs_reflector_config *config) {
	if (!config) {
		return -EINVAL;
	}
	memset(config, 0, sizeof(*config));
	config->role = CS_CONFIG_ROLE_REFLECTOR;
	config->size = sizeof(*config);
	config->connection.timeout = STUB_DEFAULT_TIMEOUT;
	return 0;
}
