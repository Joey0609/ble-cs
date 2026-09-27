/* SPDX-License-Identifier: MIT */
/* CS initiator without a command host: generated configuration -> scan for a
 * CA Tag reflector -> connect -> initiator role. CS records are formatted and
 * emitted as binary protocol reports on USB CDC; CDC never controls this
 * state machine.
 */
#include <errno.h>
#include <string.h>

#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/atomic.h>

#include <app_log/app_log.h>
#include <cs_generated_config/cs_generated_config.h>
#include <cs_protocol/cs_protocol_packets.h>
#include <cs_roles/cs_role.h>
#include <host_link/host_link.h>
#include <host_link/host_link_reports.h>

APP_LOG_MODULE(cs_hostless_initiator);

static struct cs_initiator_config config;

static atomic_t procedures;
static atomic_t local_subevents;
static atomic_t peer_subevents;
static atomic_t steps;
static atomic_t aborted_subevents;
static atomic_t partial_subevents;
static atomic_t ras_lost;
static bool report_subevent_active;

/* Latest records of the current link, resent when the host opens the port:
 * subevent results cannot be interpreted without them. A valid flag is set
 * when its record arrives; all are cleared when the link ends. */
struct link_records {
	struct cs_capabilities capabilities[2]; /* Indexed by cs_capabilities_source. */
	bool capabilities_valid[2];
	struct cs_config_connection connection_params;
	uint16_t connection_mtu;
	bool connection_params_valid;
	struct {
		uint8_t hci_status;
		uint8_t lsb_denominator;
		bool entries_valid;
		int8_t entries[CS_PROTOCOL_FAE_TABLE_ENTRIES];
	} fae;
	bool fae_valid;
	struct cs_config_complete configuration;
	bool configuration_valid;
	/* CS_PEER_DATA, sent after the configuration. */
	bool peer_data_valid;
	struct cs_procedure_enable_complete procedure;
	bool procedure_valid;
};

static struct k_spinlock cache_lock;
static struct link_records cache;

static void report_connection_params_work(struct k_work *work);
static K_WORK_DEFINE(connection_params_report_work,
                     report_connection_params_work);

/* Application fallback configuration. These values intentionally live in the
 * image rather than inheriting future changes to cs_utils library defaults.
 *
 * One CS subevent per procedure, in one 17.5 ms ACL event: 72 mode-2 steps on
 * the 72 channels (repetition 1 ends the procedure) plus one mode-0 step take
 * 12.5 ms (1 path) or 15.3 ms (2 paths) at the SDC timings T_IP1 30, T_IP2 20,
 * T_FCS 60, T_PM 10, T_SW 10 us. Procedures repeat every 3 ACL events so the
 * two following events carry the RAS real-time notifications (about 740 bytes
 * per procedure for 1 path, three LL PDUs at ATT MTU 498). With a single RAS
 * event the reflector has only 4-5 ms after the subevent to queue them; when it
 * misses, the extended ACL event overlaps the next CS event and aborts it. */
#define APP_CONN_INTERVAL_MIN 20 /* 17.5 ms */
#define APP_CONN_INTERVAL_MAX 20
#define APP_CONN_LATENCY 0
#define APP_CONN_TIMEOUT 400
#define APP_CONFIG_ID 0
#define APP_MAX_PROCEDURE_LEN 28     /* 17.5 ms: one ACL event */
#define APP_PROCEDURE_INTERVAL_MIN 1 /* CS event + 2 RAS events: 52.5 ms */
#define APP_PROCEDURE_INTERVAL_MAX 1
#define APP_MAX_PROCEDURE_COUNT 0
#define APP_SUBEVENT_LEN_US 20000
#define APP_TONE_ANTENNA CS_CONFIG_TONE_ANTENNA_A1_B1
#define APP_PROCEDURE_PHY CS_CONFIG_PROCEDURE_PHY_1M
#define APP_MODE CS_CONFIG_MODE_2
#define APP_MIN_MAIN_MODE_STEPS 2
#define APP_MAX_MAIN_MODE_STEPS 10
#define APP_MODE_0_STEPS 1
#define APP_RTT_TYPE CS_CONFIG_RTT_TYPE_AA_ONLY
#define APP_SYNC_PHY CS_CONFIG_SYNC_PHY_1M
/* All 72 usable CS channels; Bluetooth-reserved channels remain clear. */
#define APP_CHANNEL_MAP { 0xFC, 0xFF, 0x7F, 0xFC, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x1F }

static const char *const app_default_patterns[] = { "CSTag" };

static bool ras_used(void) {
	return config.peer_data == CS_CONFIG_PEER_DATA_RAS_REALTIME;
}

static int load_initiator_config(struct cs_initiator_config *out,
                                 bool *generated) {
	const struct cs_config_connection connection = {
		.interval_min = APP_CONN_INTERVAL_MIN,
		.interval_max = APP_CONN_INTERVAL_MAX,
		.latency = APP_CONN_LATENCY,
		.timeout = APP_CONN_TIMEOUT,
	};
	const struct cs_config_default_settings settings = {
		.cs_sync_antenna_selection = CS_CONFIG_SYNC_ANTENNA_REPETITIVE,
		.max_tx_power = CS_CONFIG_MAX_TX_POWER_MAX,
	};
	const struct cs_config_procedure procedure = {
		.max_procedure_len = APP_MAX_PROCEDURE_LEN,
		.min_procedure_interval = APP_PROCEDURE_INTERVAL_MIN,
		.max_procedure_interval = APP_PROCEDURE_INTERVAL_MAX,
		.max_procedure_count = APP_MAX_PROCEDURE_COUNT,
		.min_subevent_len = APP_SUBEVENT_LEN_US,
		.max_subevent_len = APP_SUBEVENT_LEN_US,
		.tone_antenna_config_selection = APP_TONE_ANTENNA,
		.phy = APP_PROCEDURE_PHY,
		.tx_power_delta = CS_CONFIG_TX_POWER_DELTA_NONE,
		/* Reflector antennas 1 and 2, the two Tag antennas. Never set a
		 * bit above the reflector's antenna count: the Tag controller
		 * switches to that antenna unchecked and faults on its
		 * unconfigured GPIO. */
		.preferred_peer_antenna = CS_CONFIG_PEER_ANTENNA_1 | CS_CONFIG_PEER_ANTENNA_2,
		.snr_control_initiator = CS_CONFIG_SNR_CONTROL_NOT_USED,
		.snr_control_reflector = CS_CONFIG_SNR_CONTROL_NOT_USED,
	};
	const struct cs_config_creation creation = {
		.mode = APP_MODE,
		.min_main_mode_steps = APP_MIN_MAIN_MODE_STEPS,
		.max_main_mode_steps = APP_MAX_MAIN_MODE_STEPS,
		.main_mode_repetition = 0,
		.mode_0_steps = APP_MODE_0_STEPS,
		.rtt_type = APP_RTT_TYPE,
		.cs_sync_phy = APP_SYNC_PHY,
		.channel_map = APP_CHANNEL_MAP,
		.channel_map_repetition = 1,
		.channel_selection_type = CS_CONFIG_CHSEL_TYPE_3B,
		.ch3c_shape = CS_CONFIG_CH3C_SHAPE_HAT,
		.ch3c_jump = 2,
		.cs_enhancements_1 = 0,
		.context = CS_CONFIG_CREATION_CONTEXT_LOCAL_AND_REMOTE,
	};
	int err = cs_generated_config_initiator(out);

	*generated = err == 0;
	if (err != -ENOENT) {
		/* The export sets reflector data without checking it against IPT. */
		return err ?: cs_initiator_config_check_peer_data(out);
	}
	APP_LOG_WRN("No planner configuration linked: applying hostless application defaults");
	err = cs_initiator_config_get_default(out);
	if (!err)
		err = cs_initiator_config_set_connection(out, &connection);
	if (!err)
		err = cs_initiator_config_set_default_settings(out, &settings);
	if (!err)
		err = cs_initiator_config_set_procedure(out, &procedure);
	if (!err)
		err = cs_initiator_config_set_creation(out, &creation);
	if (!err)
		err = cs_initiator_config_set_config_id(out, APP_CONFIG_ID);
	return err;
}

static const char *const state_names[] = {
	[CS_ROLE_STATE_SCANNING] = "scanning",
	[CS_ROLE_STATE_ADVERTISING] = "advertising",
	[CS_ROLE_STATE_LINK_CONNECTING] = "connecting",
	[CS_ROLE_STATE_LINK_CONNECTED] = "connected",
	[CS_ROLE_STATE_LINK_ENCRYPTED] = "encrypted",
	[CS_ROLE_STATE_RAS_READY] = "RAS subscribed",
	[CS_ROLE_STATE_RUNNING] = "running",
	[CS_ROLE_STATE_STOPPED] = "stopped",
	[CS_ROLE_STATE_LINK_LOST] = "link lost",
	[CS_ROLE_STATE_LINK_DISCONNECTED] = "disconnected",
	[CS_ROLE_STATE_ERROR] = "error",
};

static void on_state(enum cs_role_state state,
                     enum cs_role_failure_stage failure,
                     enum cs_role_stop_reason stop_reason,
                     uint8_t hci_status,
                     int error) {
	const char *name = state < ARRAY_SIZE(state_names) ? state_names[state] : "?";

	if (state == CS_ROLE_STATE_ERROR || state == CS_ROLE_STATE_LINK_LOST || error) {
		APP_LOG_WRN("State %s: failure %u, stop reason %u, HCI status 0x%02x, error %d",
		            name,
		            failure,
		            stop_reason,
		            hci_status,
		            error);
	} else if (state == CS_ROLE_STATE_STOPPED && stop_reason == CS_ROLE_STOP_COMPLETE) {
		APP_LOG_INF("State stopped: max_procedure_count completed");
	} else {
		APP_LOG_INF("State %s", name);
	}
	if (state == CS_ROLE_STATE_LINK_LOST || state == CS_ROLE_STATE_LINK_DISCONNECTED) {
		K_SPINLOCK(&cache_lock) {
			memset(&cache, 0, sizeof(cache));
		}
	}
	if (state == CS_ROLE_STATE_ERROR &&
	    (failure == CS_ROLE_FAILURE_PEER_IPT || failure == CS_ROLE_FAILURE_PEER_ANTENNA)) {
		/* A new link would likely find the same Tag and fail again: stop
		 * until reset. Disconnecting ends the automatic link restarts; from
		 * the event thread the request does not wait.
		 */
		APP_LOG_ERR("%s: halted, no radio activity until reset",
		            failure == CS_ROLE_FAILURE_PEER_IPT
		                    ? "Reflector data none needs IPT, which the peer or its configuration lacks"
		                    : "The peer lacks the preferred peer antennas");
		(void)cs_role_link_disconnect(K_SECONDS(1));
		return;
	}
	if (state == CS_ROLE_STATE_LINK_ENCRYPTED) {
		/* Called from the event thread: the request does not wait. */
		(void)cs_role_start_initiator(&config);
	}
}

static void on_configuration(const struct cs_config_complete *record) {
	bool peer_data = record->status == 0U;

	K_SPINLOCK(&cache_lock) {
		cache.configuration = *record;
		cache.configuration_valid = true;
		cache.peer_data_valid = peer_data;
	}
	(void)host_link_report_cs_configuration(record);
	/* A hostless host has no applied configuration: tell it how to read the subevents. */
	if (peer_data) {
		(void)host_link_report_peer_data(config.peer_data);
	}
	APP_LOG_INF("CS configuration %u: status 0x%02x, mode 0x%02x, RTT type %u, "
	            "T_IP1 %u T_IP2 %u T_FCS %u T_PM %u us",
	            record->config_id,
	            record->status,
	            record->mode,
	            record->rtt_type,
	            record->t_ip1_time_us,
	            record->t_ip2_time_us,
	            record->t_fcs_time_us,
	            record->t_pm_time_us);
}

static void on_procedure(const struct cs_procedure_enable_complete *record) {
	K_SPINLOCK(&cache_lock) {
		cache.procedure = *record;
		cache.procedure_valid = true;
	}
	(void)host_link_report_cs_procedure(record);
	APP_LOG_INF("Procedures %s: status 0x%02x, interval %u, count %u",
	            record->state ? "on" : "off",
	            record->status,
	            record->procedure_interval,
	            record->procedure_count);
}

static void on_fae(uint8_t hci_status,
                   uint8_t lsb_denominator,
                   const int8_t *entries) {
	bool entries_valid = !hci_status && entries;

	K_SPINLOCK(&cache_lock) {
		cache.fae.hci_status = hci_status;
		cache.fae.lsb_denominator = lsb_denominator;
		cache.fae.entries_valid = entries_valid;
		if (entries_valid) {
			memcpy(cache.fae.entries, entries, sizeof(cache.fae.entries));
		}
		cache.fae_valid = true;
	}
	(void)host_link_report_fae_table(hci_status, entries_valid ? entries : NULL, lsb_denominator);
	if (hci_status) {
		APP_LOG_WRN("Remote FAE table read failed: HCI status 0x%02x", hci_status);
	} else {
		APP_LOG_INF("Remote FAE table read");
	}
}

static void on_procedures_complete(uint16_t procedures_completed) {
	(void)host_link_report_cs_procedures_complete(procedures_completed);
	APP_LOG_INF("max_procedure_count reached: %u procedures completed", procedures_completed);
}

static void on_ras_lost(uint16_t procedure_counter,
                        int error) {
	(void)host_link_report_ras_data_lost(procedure_counter, error);
	atomic_inc(&ras_lost);
}

static void on_capabilities(const struct cs_capabilities *record) {
	if (record->source < ARRAY_SIZE(cache.capabilities)) {
		K_SPINLOCK(&cache_lock) {
			cache.capabilities[record->source] = *record;
			cache.capabilities_valid[record->source] = true;
		}
	}
	(void)host_link_report_cs_capabilities(record);
}

/* Called from Bluetooth context; only cache here. The report is replayed from
 * the system work queue when USB DTR rises. */
static void on_connection_params(const struct cs_config_connection *params,
                                 uint16_t mtu) {
	if (!params) {
		return;
	}
	K_SPINLOCK(&cache_lock) {
		cache.connection_params = *params;
		cache.connection_mtu = mtu;
		cache.connection_params_valid = true;
	}
	(void)k_work_submit(&connection_params_report_work);
}

static void report_connection_params_work(struct k_work *work) {
	struct cs_config_connection params;
	uint16_t mtu;
	bool valid;

	ARG_UNUSED(work);
	K_SPINLOCK(&cache_lock) {
		params = cache.connection_params;
		mtu = cache.connection_mtu;
		valid = cache.connection_params_valid;
	}
	if (valid) {
		(void)host_link_report_connection_parameters(params.interval_min,
		                                             params.latency,
		                                             params.timeout,
		                                             mtu);
	}
}

/* Bluetooth context: count, then report; returning nonzero skips decoding the
 * steps. Counted before the report, which fails while the USB port is closed.
 */
static int on_subevent_begin(const struct cs_subevent *header,
                             uint16_t num_tones) {
	APP_LOG_DBG("CS subevent: role %u, event %u, subevent %u, procedure %u, steps %u, "
	            "status 0x%02x",
	            header->role,
	            header->event_id,
	            header->subevent_id,
	            header->procedure_id,
	            header->num_steps,
	            header->subevent_done_status);
	int err;

	if (header->role == BT_CONN_LE_CS_ROLE_INITIATOR) {
		atomic_inc(&local_subevents);
		if (header->procedure_done_status != BT_CONN_LE_CS_PROCEDURE_INCOMPLETE) {
			atomic_inc(&procedures);
		}
	} else {
		atomic_inc(&peer_subevents);
	}
	atomic_add(&steps, header->num_steps);
	if (header->subevent_done_status == BT_CONN_LE_CS_SUBEVENT_ABORTED) {
		atomic_inc(&aborted_subevents);
	}
	err = host_link_report_cs_subevent_begin(header, num_tones);
	report_subevent_active = err == 0;
	return err;
}

static void on_subevent_step(const struct cs_step_header *step) {
	if (report_subevent_active) {
		host_link_report_cs_subevent_step(step);
	}
}

static void on_subevent_end(bool complete) {
	if (report_subevent_active) {
		(void)host_link_report_cs_subevent_end();
	}
	report_subevent_active = false;
	if (!complete) {
		atomic_inc(&partial_subevents);
	}
}

static const struct cs_role_callbacks callbacks = {
	.state = on_state,
	.connection_params = on_connection_params,
	.capabilities = on_capabilities,
	.configuration = on_configuration,
	.procedure = on_procedure,
	.subevent_begin = on_subevent_begin,
	.subevent_step = on_subevent_step,
	.subevent_end = on_subevent_end,
	.fae_table = on_fae,
	.ras_data_lost = on_ras_lost,
	.procedures_complete = on_procedures_complete,
};

/* System work queue: copy under the lock, report outside it (reports may wait).
 * Replayed in the order the link produced them. The snapshot is static to keep
 * it off the work queue stack; this is its only user. */
static void on_port_opened(void) {
	static struct link_records snapshot;

	K_SPINLOCK(&cache_lock) {
		snapshot = cache;
	}
	for (size_t i = 0; i < ARRAY_SIZE(snapshot.capabilities); i++) {
		if (snapshot.capabilities_valid[i]) {
			(void)host_link_report_cs_capabilities(&snapshot.capabilities[i]);
		}
	}
	if (snapshot.connection_params_valid) {
		(void)host_link_report_connection_parameters(snapshot.connection_params.interval_min,
		                                             snapshot.connection_params.latency,
		                                             snapshot.connection_params.timeout,
		                                             snapshot.connection_mtu);
	}
	if (snapshot.fae_valid) {
		(void)host_link_report_fae_table(snapshot.fae.hci_status,
		                                 snapshot.fae.entries_valid ? snapshot.fae.entries : NULL,
		                                 snapshot.fae.lsb_denominator);
	}
	if (snapshot.configuration_valid) {
		(void)host_link_report_cs_configuration(&snapshot.configuration);
	}
	if (snapshot.peer_data_valid) {
		(void)host_link_report_peer_data(config.peer_data);
	}
	if (snapshot.procedure_valid) {
		(void)host_link_report_cs_procedure(&snapshot.procedure);
	}
	APP_LOG_INF("Host port opened: resent capabilities %u/%u, connection parameters %u, "
	            "FAE %u, configuration %u, reflector data %u, procedure %u",
	            snapshot.capabilities_valid[CS_CAPABILITIES_SOURCE_LOCAL],
	            snapshot.capabilities_valid[CS_CAPABILITIES_SOURCE_REMOTE],
	            snapshot.connection_params_valid,
	            snapshot.fae_valid,
	            snapshot.configuration_valid,
	            snapshot.peer_data_valid,
	            snapshot.procedure_valid);
}

static void log_counters(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(counters_work,
                               log_counters);

static void log_counters(struct k_work *work) {
	ARG_UNUSED(work);
	if (ras_used()) {
		APP_LOG_INF("Procedures %ld, subevents local %ld / RAS %ld (aborted %ld, partial %ld), "
		            "steps %ld, RAS data lost %ld",
		            (long)atomic_get(&procedures),
		            (long)atomic_get(&local_subevents),
		            (long)atomic_get(&peer_subevents),
		            (long)atomic_get(&aborted_subevents),
		            (long)atomic_get(&partial_subevents),
		            (long)atomic_get(&steps),
		            (long)atomic_get(&ras_lost));
	} else {
		APP_LOG_INF("Procedures %ld, subevents %ld (aborted %ld, partial %ld), steps %ld",
		            (long)atomic_get(&procedures),
		            (long)atomic_get(&local_subevents),
		            (long)atomic_get(&aborted_subevents),
		            (long)atomic_get(&partial_subevents),
		            (long)atomic_get(&steps));
	}
	(void)k_work_schedule(&counters_work, K_SECONDS(CONFIG_CS_HOSTLESS_STATS_INTERVAL_S));
}

/* Planner log levels, before Bluetooth starts; the app_log defaults without an export. */
static void apply_log_config(void) {
	struct app_log_config log_config;
	int err = cs_generated_config_log(&log_config);

	if (!err) {
		err = app_log_configure(&log_config);
	}
	if (err && err != -ENOENT) {
		APP_LOG_WRN("Planner log levels rejected (%d): defaults kept", err);
	}
}

int main(void) {
	const char *const *patterns = NULL;
	size_t pattern_count = 0U;
	const char *name;
	bool generated;
	int err;

	apply_log_config();
	err = load_initiator_config(&config, &generated);
	if (err) {
		APP_LOG_ERR("Planner configuration rejected (%d): halted, no radio activity", err);
		return 0;
	} else {
		APP_LOG_INF("%s configuration, CRC-32 0x%08x, reflector data %s, preferred T_PM %u us",
		            generated ? "Planner" : "Application default",
		            (unsigned int)cs_generated_config_crc32_initiator,
		            ras_used() ? "RAS real-time" : "none (initiator only, IPT)",
		            config.t_pm_us);
	}
	err = cs_generated_config_patterns(&patterns, &pattern_count);
	if (!generated && (err == -ENOENT || pattern_count == 0U)) {
		patterns = app_default_patterns;
		pattern_count = ARRAY_SIZE(app_default_patterns);
	}
	for (size_t i = 0; i < pattern_count; i++) {
		APP_LOG_INF("Peer name pattern \"%s\"", patterns[i]);
	}
	if (pattern_count == 0U) {
		APP_LOG_INF("No name patterns: connecting to the first Ranging Service advertiser");
	}

	err = bt_enable(NULL);
	if (err) {
		APP_LOG_ERR("Bluetooth init failed: %d", err);
		return 0;
	}
	name = cs_generated_config_device_name();
	if (name) {
		err = bt_set_name(name);
		if (err) {
			APP_LOG_WRN("Device name not applied: %d", err);
		}
	}
	err = host_link_report_only_init(on_port_opened);
	if (err) {
		APP_LOG_ERR("Binary CDC report transport init failed: %d", err);
		return 0;
	}
	err = cs_role_init(&callbacks);
	if (!err) {
		const struct cs_role_link_params link = {
			.central = true,
			.connection = config.connection,
			.patterns = patterns,
			.pattern_count = pattern_count,
			.auto_restart = true,
		};

		err = cs_role_link_start(&link);
	}
	if (err) {
		APP_LOG_ERR("CS role start failed: %d", err);
		return 0;
	}
	APP_LOG_INF("Config ID %u", config.config_id);
	(void)k_work_schedule(&counters_work, K_SECONDS(CONFIG_CS_HOSTLESS_STATS_INTERVAL_S));
	return 0;
}
