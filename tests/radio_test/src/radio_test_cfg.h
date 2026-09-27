/* SPDX-License-Identifier: MIT */
#ifndef RADIO_TEST_CFG_H_
#define RADIO_TEST_CFG_H_

#include <radio_test_utils/radio_test_mode.h>

/** Populate role settings from the TEST_* macros.
 * Returns 0 on success or -EINVAL for NULL output or unsupported TEST_MODE.
 */
int radio_test_cfg_get(struct radio_test_mode_config *config);

/**
 * @brief Print the configured test to the console.
 *
 * @param[in] config Configuration to describe, populated by
 *                   radio_test_cfg_get().
 */
void radio_test_cfg_print(const struct radio_test_mode_config *config);

#endif /* RADIO_TEST_CFG_H_ */
