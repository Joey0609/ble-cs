/* SPDX-License-Identifier: MIT */
/* Discovery and link commands -> cs_role_link_*; scan reports -> SCAN_RESULT frames. */
#include <errno.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/addr.h>
#include <zephyr/sys/atomic.h>
#include "app_log/app_log.h"
#include "cs_utils/cs_config.h"
#include "host_link/host_link_reports.h"
#include "cs_protocol/cs_protocol.h"
#include "client_state.h"
#include "cs_roles/cs_role.h"
#include "peer_discovery.h"

APP_LOG_MODULE(peer_discovery);

/* Never block the Bluetooth receive thread on serial backpressure. */
K_MSGQ_DEFINE(scan_reports, sizeof(struct cs_protocol_scan_result_frame_t), 32, 4);
static atomic_t scan_dropped;
static atomic_t discovering;

static void report_scans(void *a, void *b, void *c) {
    ARG_UNUSED(a); ARG_UNUSED(b); ARG_UNUSED(c);
    struct cs_protocol_scan_result_frame_t frame;
    for (;;) {
        k_msgq_get(&scan_reports, &frame, K_FOREVER);
        if (!atomic_get(&discovering)) {
            continue;
        }
        cs_protocol_finalize_frame(&frame, sizeof(frame), CS_PROTOCOL_PACKET_SCAN_RESULT);
        host_link_report_frame((const uint8_t *)&frame, sizeof(frame));
        atomic_val_t dropped = atomic_clear(&scan_dropped);
        if (dropped) {
            APP_LOG_WRN("%ld scan reports dropped: queue full", (long)dropped);
        }
    }
}
K_THREAD_DEFINE(scan_report_thread, 1536, report_scans, NULL, NULL, NULL, 7, 0, 0);

static uint8_t gap_role;
static uint8_t operation_mode;
static struct cs_config_connection connection_params;

bool peer_discovery_active(void) {
    return cs_role_link_active();
}

void peer_discovery_configure(uint8_t role, uint8_t mode,
                              const struct cs_config_connection *params) {
    gap_role = role;
    operation_mode = mode;
    connection_params = *params;
}

static struct host_link_result failure(uint8_t reason, int err) {
    client_state_set(CS_PROTOCOL_CLIENT_STATE_ERROR, reason, 0, err);
    return (struct host_link_result){CS_PROTOCOL_STATUS_FAILED, reason, err};
}

/* Bluetooth context (cs_roles scan_result callback). */
void peer_discovery_scan_result(const struct cs_role_scan_result *result) {
    struct cs_protocol_scan_result_frame_t frame = {
        .address_type = result->address.type,
        .rssi_dbm = result->rssi,
        .flags = result->connectable ? 1 : 0,
    };

    if (!atomic_get(&discovering) || result->address.type > BT_ADDR_LE_RANDOM) {
        return;
    }
    memcpy(frame.address, result->address.a.val, sizeof(frame.address));
    if (result->name_len) {
        frame.name_length = MIN(result->name_len, sizeof(frame.name));
        memcpy(frame.name, result->name, frame.name_length);
        frame.flags |= result->name_complete ? 2 : 0;
    }
    if (k_msgq_put(&scan_reports, &frame, K_NO_WAIT)) {
        atomic_inc(&scan_dropped);
    }
}

struct host_link_result peer_discovery_command(uint16_t type, const uint8_t *payload) {
    bool central = type != CS_PROTOCOL_PACKET_ADVERTISE_START;
    int err;

    if ((central && gap_role != CS_PROTOCOL_GAP_CENTRAL) ||
        (!central && gap_role == CS_PROTOCOL_GAP_CENTRAL)) {
        return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_MODE_MISMATCH);
    }
    if (cs_role_link_active() &&
        !(atomic_get(&discovering) && type == CS_PROTOCOL_PACKET_PEER_CONNECT)) {
        return HOST_LINK_RESULT(CS_PROTOCOL_STATUS_BAD_STATE, CS_PROTOCOL_REASON_LINK_ACTIVE);
    }
    if (type == CS_PROTOCOL_PACKET_PEER_CONNECT && payload[0] > BT_ADDR_LE_RANDOM) {
        return HOST_LINK_RESULT_OUT_OF_RANGE(-EINVAL);
    }
    if (type == CS_PROTOCOL_PACKET_SCAN_START) {
        /* Active scanning, no filtering: the host filters by name pattern
         * and can still show every peer. */
        k_msgq_purge(&scan_reports);
        atomic_clear(&scan_dropped);
        atomic_set(&discovering, 1);
        err = cs_role_scan_start();
        if (err) {
            atomic_clear(&discovering);
            return failure(CS_PROTOCOL_REASON_SCAN_FAILED, err);
        }
        client_state_set(CS_PROTOCOL_CLIENT_STATE_SCANNING, CS_PROTOCOL_REASON_NONE, 0, 0);
        return HOST_LINK_RESULT_OK;
    }

    bt_addr_le_t addr = {.type = payload ? payload[0] : 0};
    struct cs_role_link_params params = {
        .central = central,
        .connection = connection_params,
        /* Reflector advertisements carry the Ranging Service UUID. */
        .advertise_ras_uuid = operation_mode == CS_PROTOCOL_MODE_CS_REFLECTOR,
    };

    if (central) {
        memcpy(addr.a.val, payload + 1, sizeof(addr.a.val));
        params.peer = &addr;
    }
    atomic_clear(&discovering);
    err = cs_role_link_start(&params);
    if (err) {
        return failure(central ? CS_PROTOCOL_REASON_CONNECT_FAILED :
                                 CS_PROTOCOL_REASON_ADVERTISE_FAILED, err);
    }
    client_state_set(central ? CS_PROTOCOL_CLIENT_STATE_LINK_CONNECTING :
                               CS_PROTOCOL_CLIENT_STATE_ADVERTISING,
                     CS_PROTOCOL_REASON_NONE, 0, 0);
    return HOST_LINK_RESULT_OK;
}

struct host_link_result peer_discovery_stop(void) {
    atomic_clear(&discovering);
    int err = cs_role_link_disconnect(K_SECONDS(3));

    if (err) {
        return failure(CS_PROTOCOL_REASON_CONNECT_FAILED, err);
    }
    client_state_set(CS_PROTOCOL_CLIENT_STATE_LINK_DISCONNECTED, CS_PROTOCOL_REASON_NONE, 0, 0);
    return HOST_LINK_RESULT_OK;
}
