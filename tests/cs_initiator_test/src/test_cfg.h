/* SPDX-License-Identifier: MIT */
#ifndef TEST_CFG_H_
#define TEST_CFG_H_

#include <cs_utils/cs_config.h>

/**
 * @brief Build the initiator record from the TEST_* block in test_cfg.c.
 *
 * Starts from cs_initiator_config_get_default() and applies every setting
 * through the cs_initiator_config_set_*() setters, so their validation holds.
 *
 * @param[out] config Record to fill.
 * @retval 0 Record ready to apply.
 * @retval -EINVAL A setter rejected a TEST_* value; @p config is unusable.
 */
int test_cfg_get(struct cs_initiator_config *config);

/**
 * @brief Advertised name the peer must carry.
 * @return TEST_PEER_NAME; an empty string accepts any Ranging Service advertiser.
 */
const char *test_cfg_peer_name(void);

/**
 * @brief Procedures to observe before reporting a verdict.
 * @return TEST_EXPECTED_PROCEDURES; 0 means run without a verdict.
 */
unsigned int test_cfg_expected_procedures(void);

#endif /* TEST_CFG_H_ */
