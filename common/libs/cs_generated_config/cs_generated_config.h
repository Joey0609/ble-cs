/* SPDX-License-Identifier: MIT */
/**
 * @file cs_generated_config.h
 * @brief Interface implemented by planner-generated CS configuration sources.
 *
 * cs_app exports a configuration as a C source that defines these symbols for
 * the role(s) it was exported for. cs_generated_config.c provides weak
 * defaults, so an application without an export still links: its role
 * functions load the cs_utils default configuration and return -ENOENT.
 * Generated sources return 0 on success and never -ENOENT.
 */
#ifndef CS_GENERATED_CONFIG_H_
#define CS_GENERATED_CONFIG_H_

#include <stddef.h>
#include <stdint.h>

#include <app_log/app_log.h>
#include <cs_utils/cs_config.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Fill @p config with the generated initiator configuration.
 *
 * @retval 0 Generated configuration loaded.
 * @retval -ENOENT No generated configuration linked; @p config holds the
 *         defaults of cs_initiator_config_get_default().
 * @retval -EINVAL @p config is NULL or a generated value was rejected by a setter.
 */
int cs_generated_config_initiator(struct cs_initiator_config *config);

/**
 * @brief Fill @p config with the generated reflector configuration.
 *
 * @retval 0 Generated configuration loaded.
 * @retval -ENOENT No generated configuration linked; @p config holds the
 *         defaults of cs_reflector_config_get_default().
 * @retval -EINVAL @p config is NULL or a generated value was rejected by a setter.
 */
int cs_generated_config_reflector(struct cs_reflector_config *config);

/**
 * @brief Peripheral name prefixes for a GAP central.
 *
 * @p count is 0 (and @p patterns NULL) when there are none.
 *
 * @retval 0 Generated patterns returned.
 * @retval -ENOENT No generated configuration linked; no patterns.
 * @retval -EINVAL @p patterns or @p count is NULL.
 */
int cs_generated_config_patterns(const char *const **patterns, size_t *count);

/**
 * @brief Log levels for app_log_configure(), applied before Bluetooth starts.
 *
 * A reflector image has no protocol consumer: @c protocol_level has no effect there.
 *
 * @retval 0 Generated levels returned.
 * @retval -ENOENT No generated levels linked; @p config holds the app_log defaults.
 * @retval -EINVAL @p config is NULL.
 */
int cs_generated_config_log(struct app_log_config *config);

/** Local Bluetooth name, or NULL for the firmware default. Apply before advertising. */
const char *cs_generated_config_device_name(void);

/** CRC-32 of the generated initiator configuration; 0 when none is linked. */
extern const uint32_t cs_generated_config_crc32_initiator;
/** CRC-32 of the generated reflector configuration; 0 when none is linked. */
extern const uint32_t cs_generated_config_crc32_reflector;

#ifdef __cplusplus
}
#endif

#endif /* CS_GENERATED_CONFIG_H_ */
