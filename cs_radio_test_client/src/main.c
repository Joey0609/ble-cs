/* SPDX-License-Identifier: MIT */
#include <zephyr/kernel.h>

#include "app_log/app_log.h"
#include "host_link/host_link.h"
#include "session.h"

APP_LOG_MODULE(cs_radio_test_client);

int main(void) {
	int err;

	APP_LOG_INF("CS radio-test client starting");
	err = session_init();
	if (err) {
		APP_LOG_ERR("Radio-test session init failed: %d", err);
		return 0;
	}

	err = host_link_init(session_handlers());
	if (err) {
		APP_LOG_ERR("Host-link init failed: %d", err);
		return 0;
	}
	APP_LOG_INF("Waiting for the host link");
	return 0;
}
