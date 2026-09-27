/* SPDX-License-Identifier: MIT */
/* Stands in for a cs_app planner export: strong definitions of every symbol. */
#include <errno.h>

#include <cs_generated_config/cs_generated_config.h>

#include "generated_fixture.h"

const uint32_t cs_generated_config_crc32_initiator = FIXTURE_CRC32_INITIATOR;
const uint32_t cs_generated_config_crc32_reflector = FIXTURE_CRC32_REFLECTOR;

int cs_generated_config_initiator(struct cs_initiator_config *config) {
	int err = cs_initiator_config_get_default(config);
	if (err) return err;
	config->config_id = FIXTURE_CONFIG_ID;
	return 0;
}

int cs_generated_config_reflector(struct cs_reflector_config *config) {
	int err = cs_reflector_config_get_default(config);
	if (err) return err;
	config->config_id = FIXTURE_CONFIG_ID;
	return 0;
}

int cs_generated_config_patterns(const char *const **patterns, size_t *count) {
	if (!patterns || !count) return -EINVAL;
	static const char *const names[] = { FIXTURE_PATTERN };
	*patterns = names;
	*count = 1;
	return 0;
}

int cs_generated_config_log(struct app_log_config *config) {
	if (!config) return -EINVAL;
	config->console_level = FIXTURE_LOG_CONSOLE;
	config->protocol_level = FIXTURE_LOG_PROTOCOL;
	return 0;
}
