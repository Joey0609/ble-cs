/* SPDX-License-Identifier: MIT */
#ifndef TEST_CFG_H_
#define TEST_CFG_H_

#include <stdbool.h>

#include <cs_utils/cs_config.h>

/**
 * @brief Build the reflector record.
 *
 * Uses the planner export linked with -DCS_CONFIG_SOURCE when there is one.
 * Otherwise starts from cs_reflector_config_get_default() and applies the
 * TEST_* block in test_cfg.c through the cs_reflector_config_set_*() setters,
 * so their validation holds.
 *
 * @param[out] config Record to fill.
 * @param[out] generated True when the record comes from a planner export.
 * @retval 0 Record ready to apply.
 * @retval -EINVAL A setter rejected a generated or TEST_* value; @p config is
 *         unusable.
 */
int test_cfg_get(struct cs_reflector_config *config, bool *generated);

#endif /* TEST_CFG_H_ */
