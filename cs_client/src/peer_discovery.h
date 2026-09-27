/* SPDX-License-Identifier: MIT */
#ifndef PEER_DISCOVERY_H_
#define PEER_DISCOVERY_H_
#include "cs_utils/cs_config.h"
#include "host_link/host_link_types.h"
struct cs_role_scan_result;
bool peer_discovery_active(void);
void peer_discovery_configure(uint8_t role, uint8_t operation_mode,
                              const struct cs_config_connection *params);
/** cs_role_callbacks.scan_result: queue a SCAN_RESULT frame (Bluetooth context). */
void peer_discovery_scan_result(const struct cs_role_scan_result *result);
struct host_link_result peer_discovery_command(uint16_t type, const uint8_t *payload);
struct host_link_result peer_discovery_stop(void);
#endif
