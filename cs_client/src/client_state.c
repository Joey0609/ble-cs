/* SPDX-License-Identifier: MIT */
#include <zephyr/kernel.h>

#include "app_log/app_log.h"
#include "client_state.h"
#include "cs_protocol/cs_protocol_packets.h"
#include "host_link/host_link_names.h"
#include "host_link/host_link_reports.h"

APP_LOG_MODULE(client_state);

static K_MUTEX_DEFINE(lock);
static uint8_t state = CS_PROTOCOL_CLIENT_STATE_IDLE;
static uint8_t mode = CS_PROTOCOL_MODE_NONE;

/* Last change with an error the host has not received, sent after the next CONNECT. */
static struct {
	bool pending;
	uint8_t state;
	uint8_t mode;
	uint8_t reason;
	uint8_t hci_status;
	int32_t error;
} undelivered;

uint8_t client_state_get(void) {
	uint8_t value;

	k_mutex_lock(&lock, K_FOREVER);
	value = state;
	k_mutex_unlock(&lock);
	return value;
}

uint8_t client_state_mode(void) {
	uint8_t value;

	k_mutex_lock(&lock, K_FOREVER);
	value = mode;
	k_mutex_unlock(&lock);
	return value;
}

void client_state_set_mode(uint8_t new_mode) {
	k_mutex_lock(&lock, K_FOREVER);
	mode = new_mode;
	k_mutex_unlock(&lock);
}

/* States the host should treat as abnormal. */
static bool is_abnormal(uint8_t value, int32_t error) {
	return value == CS_PROTOCOL_CLIENT_STATE_LINK_LOST || value == CS_PROTOCOL_CLIENT_STATE_ERROR ||
	       error != 0;
}

/* Called with the lock held. */
static void set_locked(uint8_t new_state, uint8_t reason, uint8_t hci_status, int32_t error) {
	uint8_t old_state = state;
	int err;

	state = new_state;
	/* Without a host session the report is dropped and CONNECT reports the state;
	 * an error is kept so the host still learns why the operation ended.
	 */
	err = host_link_report_client_state(new_state, mode, reason, hci_status, error);
	if (error != 0) {
		undelivered.pending = err != 0;
		undelivered.state = new_state;
		undelivered.mode = mode;
		undelivered.reason = reason;
		undelivered.hci_status = hci_status;
		undelivered.error = error;
	} else if (err == 0) {
		/* The host has seen a newer state; an older interruption is stale. */
		undelivered.pending = false;
	}
	if (is_abnormal(new_state, error)) {
		APP_LOG_WRN("State %s -> %s, mode %s, reason %s, HCI status 0x%02x, error %d",
		            host_link_state_name(old_state), host_link_state_name(new_state),
		            host_link_mode_name(mode), host_link_reason_name(reason), hci_status,
		            (int)error);
	} else {
		APP_LOG_INF("State %s -> %s, mode %s, reason %s, HCI status 0x%02x",
		            host_link_state_name(old_state), host_link_state_name(new_state),
		            host_link_mode_name(mode), host_link_reason_name(reason), hci_status);
	}
}

void client_state_set(uint8_t new_state, uint8_t reason, uint8_t hci_status, int32_t error) {
	k_mutex_lock(&lock, K_FOREVER);
	set_locked(new_state, reason, hci_status, error);
	k_mutex_unlock(&lock);
}

bool client_state_change(uint8_t from, uint8_t to, uint8_t reason, int32_t error) {
	bool changed;

	k_mutex_lock(&lock, K_FOREVER);
	changed = state == from;
	if (changed) {
		set_locked(to, reason, 0U, error);
	}
	k_mutex_unlock(&lock);
	return changed;
}

void client_state_session_changed(bool active) {
	if (!active) {
		/* State and mode describe the device, not the host connection. */
		return;
	}
	k_mutex_lock(&lock, K_FOREVER);
	if (undelivered.pending &&
	    host_link_report_client_state(undelivered.state, undelivered.mode, undelivered.reason,
	                                  undelivered.hci_status, undelivered.error) == 0) {
		undelivered.pending = false;
		APP_LOG_WRN("Reported earlier state %s, reason %s, error %d",
		            host_link_state_name(undelivered.state),
		            host_link_reason_name(undelivered.reason), (int)undelivered.error);
	}
	k_mutex_unlock(&lock);
}
