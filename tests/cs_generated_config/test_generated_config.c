/* SPDX-License-Identifier: MIT */
/* Weak defaults of cs_generated_config.h, alone (default build) and overridden
 * by a generated source (TEST_WITH_GENERATED).
 */
#undef NDEBUG
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#include <cs_generated_config/cs_generated_config.h>

#include "generated_fixture.h"
#include "stub_cs_config.h"

#ifndef TEST_WITH_GENERATED
static void test_weak_defaults(void) {
	struct cs_initiator_config initiator, initiator_default;
	struct cs_reflector_config reflector, reflector_default;
	const char *const *patterns = (const char *const *)&patterns;
	size_t count = 99;

	memset(&initiator, 0xa5, sizeof(initiator));
	memset(&reflector, 0xa5, sizeof(reflector));
	assert(cs_initiator_config_get_default(&initiator_default) == 0);
	assert(cs_reflector_config_get_default(&reflector_default) == 0);

	assert(cs_generated_config_initiator(&initiator) == -ENOENT);
	assert(memcmp(&initiator, &initiator_default, sizeof(initiator)) == 0);
	assert(cs_generated_config_reflector(&reflector) == -ENOENT);
	assert(memcmp(&reflector, &reflector_default, sizeof(reflector)) == 0);

	assert(cs_generated_config_patterns(&patterns, &count) == -ENOENT);
	assert(patterns == NULL && count == 0);
	assert(cs_generated_config_crc32_initiator == 0U);
	assert(cs_generated_config_crc32_reflector == 0U);

	struct app_log_config log = {0xa5, 0xa5};

	assert(cs_generated_config_log(&log) == -ENOENT);
	assert(log.console_level == APP_LOG_CONSOLE_LEVEL_DEFAULT &&
	       log.protocol_level == APP_LOG_PROTOCOL_LEVEL_DEFAULT);
	assert(cs_generated_config_log(NULL) == -EINVAL);

	/* Argument errors are not reported as "no generated configuration". */
	assert(cs_generated_config_initiator(NULL) == -EINVAL);
	assert(cs_generated_config_reflector(NULL) == -EINVAL);
	assert(cs_generated_config_patterns(NULL, &count) == -EINVAL);
	assert(cs_generated_config_patterns(&patterns, NULL) == -EINVAL);
}

#else
static void test_generated_overrides(void) {
	struct cs_initiator_config initiator;
	struct cs_reflector_config reflector;
	const char *const *patterns = NULL;
	size_t count = 0;

	assert(cs_generated_config_initiator(&initiator) == 0);
	assert(initiator.config_id == FIXTURE_CONFIG_ID);
	assert(initiator.connection.timeout == STUB_DEFAULT_TIMEOUT);
	assert(cs_generated_config_reflector(&reflector) == 0);
	assert(reflector.config_id == FIXTURE_CONFIG_ID);

	assert(cs_generated_config_patterns(&patterns, &count) == 0);
	assert(count == 1 && strcmp(patterns[0], FIXTURE_PATTERN) == 0);
	assert(cs_generated_config_crc32_initiator == FIXTURE_CRC32_INITIATOR);
	assert(cs_generated_config_crc32_reflector == FIXTURE_CRC32_REFLECTOR);

	struct app_log_config log;

	assert(cs_generated_config_log(&log) == 0);
	assert(log.console_level == FIXTURE_LOG_CONSOLE && log.protocol_level == FIXTURE_LOG_PROTOCOL);
}
#endif

int main(void) {
#ifdef TEST_WITH_GENERATED
	test_generated_overrides();
	puts("cs_generated_config: generated source overrides weak defaults");
#else
	test_weak_defaults();
	puts("cs_generated_config: weak defaults");
#endif
	return 0;
}
