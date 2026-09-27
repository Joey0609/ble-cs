/* SPDX-License-Identifier: MIT */
#include <app_version.h>
#include <zephyr/kernel.h>

#include "app_log/app_log.h"
#include "host_link/host_link.h"
#include "session.h"

APP_LOG_MODULE(cs_client);

int main(void) {
	int err;

	APP_LOG_INF("CS client %s, %s build", APP_VERSION_STRING, session_build_name());

	/* Boots to IDLE: no radio activity before APPLY_CONFIG and START. */
	err = session_init();
	if (err) {
		APP_LOG_ERR("Session init failed: %d", err);
		return 0;
	}

	err = host_link_init(session_handlers());
	if (err) {
		APP_LOG_ERR("Host link init failed: %d", err);
		return 0;
	}
	APP_LOG_INF("Waiting for the host on USB CDC ACM");
	return 0;
}
