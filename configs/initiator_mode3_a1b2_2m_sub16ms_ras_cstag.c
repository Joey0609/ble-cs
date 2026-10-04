/* Hand-written 2026-09-24 for the stack high-water-mark measurement; not a
 * ble-channel-sounding export. Regenerating this file from ble-channel-sounding overwrites everything here.
 *
 * Operation mode: CS initiator; IPT: requested
 * Reflector data: RAS real-time
 * Client log: console info, host debug
 *
 * The goal is the deepest and widest code path this pair can sustain, because
 * a stack watermark is only worth the paths the run actually reached. The
 * previous export (mode 2, one antenna path, reflector data none) is the
 * shallowest configuration in the system: no RAS discovery, no subscription,
 * no notification reassembly, one tone per step. Every choice below is the
 * heaviest value that still leaves a link that runs for minutes:
 *
 * - mode 3: every step carries RTT and tones, the widest step payload the
 *   controller will accept. A mode-2 sub-mode (0x23) was the first choice and
 *   was rejected by the controller - see the note on .mode below.
 * - reflector data RAS real-time: restores RAS discovery, subscription,
 *   segment reassembly and per-procedure buffering on the role thread, which
 *   is the deepest call chain the initiator has.
 * - two antenna paths (A1:B2): the most this pair can do. The initiator has
 *   CONFIG_BT_CTLR_SDC_CS_NUM_ANTENNAS=1 and the Tag has 2, so A1:B2 is the
 *   ceiling; A2:B2 would need a second initiator antenna. It doubles the tone
 *   data per step against the A1:B1 runs so far.
 * - three mode-0 steps: the maximum, and the most frequency-offset steps to
 *   parse per subevent.
 * - a 16 ms subevent: the largest that fits beside the ACL event in a 30 ms
 *   connection interval, so the controller fills it with as many steps as the
 *   channel map allows.
 * - T_PM 10 us: the shortest tone period, so the subevent holds the most
 *   steps. Longer T_PM buys air time per step, not depth.
 * - host log at debug: one line per subevent header from Bluetooth context,
 *   which is the heaviest the app_log queue and the protocol sink ever get
 *   (section 2.7 step 7). The console stays at info on purpose - see
 *   cs_generated_config_log() below.
 *
 * Rungs already stepped down after an LE CS Create Config rejection
 * (opcode 0x2090, status 0x11): the mode-2 sub-mode, then the 32-bit sounding
 * RTT type. Only three fields in Create Config still differ from the mode-2
 * configuration that ran on 2026-09-23, so if 0x11 comes back the remaining
 * suspects are .mode_0_steps (3, try 2) and .mode itself (3, try
 * CS_CONFIG_MODE_2). Change one field per build so the rejection stays
 * attributable, and read the capabilities report in ble-channel-sounding - modes_supported,
 * rtt_capability and subfeatures_supported name the limit directly instead of
 * leaving it to elimination.
 */
#include <cs_generated_config/cs_generated_config.h>
#include <cs_utils/cs_config.h>

/* Hand-written marker, not a CRC over the record. Its only job is to appear in
 * the boot line so a capture can be told apart from the 0xa52ea759 runs. */
const uint32_t cs_generated_config_crc32_initiator = 0x5A6F0001U;

int cs_generated_config_initiator(struct cs_initiator_config *config) {
	int err = cs_initiator_config_get_default(config);
	if (err)
		return err;
	const struct cs_config_connection connection = {
		/* 30 ms, pinned. It has to hold a 16.25 ms CS event and the ACL
		 * event beside it, and it has to leave ACL events for the RAS
		 * notifications between procedures. The Tag accepts 7.5-50 ms and
		 * CONFIG_BT_GAP_AUTO_UPDATE_CONN_PARAMS=n there, so it will not ask
		 * to move it. */
		.interval_min = 24,
		.interval_max = 24,
		.latency = 0,
		.timeout = 400,
	};
	err = cs_initiator_config_set_connection(config, &connection);
	if (err)
		return err;
	const struct cs_config_default_settings default_settings = {
		.cs_sync_antenna_selection = CS_CONFIG_SYNC_ANTENNA_REPETITIVE,
		.max_tx_power = 20,
	};
	err = cs_initiator_config_set_default_settings(config, &default_settings);
	if (err)
		return err;
	const struct cs_config_procedure procedure = {
		/* One CS event per procedure and one subevent per event, so the
		 * procedure is the subevent: 16000 us needs ceil(16000/625) = 26
		 * units. 25 would truncate the subevent and silently drop steps,
		 * which is how 8000 us turned 74 steps into 59 on 2026-09-23. */
		.max_procedure_len = 26,
		/* 2 to 4 ACL events, the controller picks. Interval 1 is reachable
		 * without RAS but leaves no event for the reflector's notifications;
		 * at two paths and mode 3 each procedure is several times the RAS
		 * payload of the 2026-09-23 runs, so it needs at least one whole
		 * event to drain and 4 gives it three. Whatever the controller
		 * returns is in the CS configuration log line. */
		.min_procedure_interval = 2,
		.max_procedure_interval = 4,
		.max_procedure_count = 0,
		.min_subevent_len = 16000,
		.max_subevent_len = 16000,
		/* Two antenna paths: one initiator antenna, both Tag antennas. The
		 * Tag already requests A1:B2 and warned that the peer picked
		 * configuration 0 in the 2026-09-23 runs. */
		.tone_antenna_config_selection = CS_CONFIG_TONE_ANTENNA_A1_B2,
		.phy = CS_CONFIG_PROCEDURE_PHY_2M,
		.tx_power_delta = CS_CONFIG_TX_POWER_DELTA_NONE,
		.preferred_peer_antenna =
		        CS_CONFIG_PEER_ANTENNA_1 | CS_CONFIG_PEER_ANTENNA_2,
		.snr_control_initiator = CS_CONFIG_SNR_CONTROL_NOT_USED,
		.snr_control_reflector = CS_CONFIG_SNR_CONTROL_NOT_USED,
	};
	err = cs_initiator_config_set_procedure(config, &procedure);
	if (err)
		return err;
	const struct cs_config_creation creation = {
		/* Mode 3: RTT plus tones on every step.
		 *
		 * 2026-09-24: CS_CONFIG_MODE_3_SUB_MODE_2 (0x23) was tried first and
		 * the initiator's own controller rejected LE CS Create Config with
		 * "Unsupported Feature or Parameter Value" (opcode 0x2090, status
		 * 0x11) before anything reached the air - which is why the Tag never
		 * logged a configuration line. RAS discovery and subscription had
		 * already succeeded on that link, so the sub-mode is the only thing
		 * the rejection can be about. The SDC appears not to accept a
		 * sub-mode at all. */
		.mode = CS_CONFIG_MODE_3,
		/* No sub-mode, so these bound nothing; 1, 1 is the neutral pair the
		 * planner substitutes in that case (section 14). */
		.min_main_mode_steps = 1,
		.max_main_mode_steps = 1,
		.main_mode_repetition = 0,
		/* The maximum. */
		.mode_0_steps = 3,
		/* 2026-09-24: CS_CONFIG_RTT_TYPE_32_BIT_SOUNDING was tried and Create
		 * Config was rejected 0x11 with it, both with and without a sub-mode.
		 * A sounding sequence needs rtt_sounding_n > 0 in the controller's
		 * capabilities; AA-only is the one every controller must support.
		 * Mode-3 steps still carry RTT this way, timed from the access
		 * address instead of a sounding sequence. */
		.rtt_type = CS_CONFIG_RTT_TYPE_AA_ONLY,
		.cs_sync_phy = CS_CONFIG_SYNC_PHY_2M,
		/* All 72 usable channels. */
		.channel_map = { 0xfc, 0xff, 0x7f, 0xfc, 0xff, 0xff, 0xff, 0xff, 0xff, 0x1f },
		.channel_map_repetition = 1,
		.channel_selection_type = CS_CONFIG_CHSEL_TYPE_3B,
		.ch3c_shape = CS_CONFIG_CH3C_SHAPE_HAT,
		.ch3c_jump = 2,
		.cs_enhancements_1 = CS_CONFIG_ENHANCEMENTS_1_IPT,
		.context = CS_CONFIG_CREATION_CONTEXT_LOCAL_AND_REMOTE,
	};
	err = cs_initiator_config_set_creation(config, &creation);
	if (err)
		return err;
	err = cs_initiator_config_set_config_id(config, 0);
	if (err)
		return err;
	err = cs_initiator_config_set_channel_map(config, creation.channel_map);
	if (err)
		return err;
	err = cs_initiator_config_set_creation_context(config, creation.context);
	if (err)
		return err;
	err = cs_initiator_config_enable_ipt(config);
	if (err)
		return err;
	/* RAS real-time, not none: the RAS path is the measurement. IPT stays
	 * requested above, which is legal with RAS - only reflector data none
	 * requires it. */
	err = cs_initiator_config_set_peer_data(config, CS_CONFIG_PEER_DATA_RAS_REALTIME);
	if (err)
		return err;
	/* The shortest tone period, so the 16 ms subevent holds the most steps. */
	err = cs_initiator_config_set_t_pm(config, CS_CONFIG_T_PM_10_US);
	if (err)
		return err;
	return 0;
}

int cs_generated_config_patterns(const char *const **patterns,
                                 size_t *count) {
	if (!patterns || !count)
		return -22;
	static const char *const names[] = { "CSTag" };
	*patterns = names;
	*count = 1;
	return 0;
}

int cs_generated_config_log(struct app_log_config *config) {
	if (!config)
		return -22;
	/* Console stays at INF. The sinks filter independently
	 * (app_log.c: level <= sink_levels[sink]), so DBG on the protocol sink
	 * alone puts the per-subevent lines on USB without flooding the debug
	 * UART - which is where CONFIG_THREAD_ANALYZER writes its blocks. At DBG
	 * on both, the analyzer output is what gets dropped, and the measurement
	 * is lost. */
	config->console_level = APP_LOG_LEVEL_INF;
	/* DBG: one line per subevent header, logged from Bluetooth context. The
	 * heaviest the app_log queue and the protocol sink ever get, and the drop
	 * count is itself the section 2.7 step 7 measurement. */
	config->protocol_level = APP_LOG_LEVEL_DBG;
	return 0;
}

const char *cs_generated_config_device_name(void) {
	return NULL;
}

/* CS_PLANNER_SCENARIO_JSON
   Hand-updated alongside the record above so ble-channel-sounding shows something close to
   what runs, but it was not produced by the planner: check it in the planner
   before trusting it as a scenario.
{
  "schema_version": 1,
  "connection": {
    "interval_min": 24,
    "interval_max": 24,
    "interval": 30,
    "latency": 0,
    "timeout": 400,
    "activity_us": 1000
  },
  "configuration": {
    "id": 0,
    "mode": 3,
    "min_main_mode_steps": 1,
    "max_main_mode_steps": 1,
    "main_mode_repetition": 0,
    "mode_0_steps": 3,
    "role": 0,
    "rtt_type": 0,
    "cs_sync_phy": 2,
    "channel_map_repetition": 1,
    "channel_selection_type": 0,
    "ch3c_shape": 0,
    "ch3c_jump": 2,
    "cs_enhancements_1": 1,
    "t_ip1_time_us": 10,
    "t_ip2_time_us": 10,
    "t_fcs_time_us": 50,
    "t_pm_time_us": 10,
    "channel_map": "fcff7ffcffffffffff1f"
  },
  "procedure": {
    "config_id": 0,
    "state": 1,
    "tone_antenna_config_selection": 4,
    "selected_tx_power": 0,
    "subevent_len": 16000,
    "subevents_per_event": 1,
    "subevent_interval": 0,
    "event_interval": 2,
    "procedure_interval": 2,
    "procedure_count": 0,
    "max_procedure_len": 26
  },
  "target_steps": 72,
  "main_steps": 1,
  "t_sw_us": 2,
  "t_sw_ipt_us": 2,
  "event_offset_us": 1500,
  "preview_count": 3,
  "provenance": "Hand-written maximum-depth configuration for the stack measurement",
  "channel_seed": 1,
  "host_settings": {
    "gap_role": 0,
    "cs_sync_antenna_selection": 254,
    "max_tx_power": 20,
    "phy": 1,
    "tx_power_delta": -128,
    "preferred_peer_antenna": 3,
    "snr_control_initiator": 255,
    "snr_control_reflector": 255,
    "creation_context": 1,
    "peer_data": 0,
    "log": {
      "console": 3,
      "host": 4
    },
    "peripheral_patterns": [
      "CSTag"
    ]
  }
}

*/
