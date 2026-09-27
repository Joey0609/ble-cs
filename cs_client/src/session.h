/* SPDX-License-Identifier: MIT */
#ifndef SESSION_H_
#define SESSION_H_

#include "host_link/host_link_handlers.h"

/**
 * @file
 * @brief Operation-mode session of one build, behind the host link handlers.
 *
 * Implemented by cs_session.c in the Bluetooth build and by radio_session.c in
 * the radio test build.
 */

/**
 * @brief Prepare the radio for the build's modes. Starts no radio activity.
 * @return 0 or a negative error from the Bluetooth stack or radio test driver.
 */
int session_init(void);

/** @brief Handler table for host_link_init(). */
const struct host_link_handlers *session_handlers(void);

/** @brief Name of the build, for the boot log. */
const char *session_build_name(void);

#endif /* SESSION_H_ */
