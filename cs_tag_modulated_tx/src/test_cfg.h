/* SPDX-License-Identifier: MIT */
#ifndef CS_TAG_MODULATED_TX_TEST_CFG_H_
#define CS_TAG_MODULATED_TX_TEST_CFG_H_

#include <radio_test_utils/radio_test_mode.h>

int test_cfg_get(struct radio_test_mode_config *config);
void test_cfg_print(const struct radio_test_mode_config *config);

#endif /* CS_TAG_MODULATED_TX_TEST_CFG_H_ */
