"""Planner help texts: tooltips, tab overviews and a detailed entry for every setting.

Each setting has one key. Its tooltip (the *_CONTROL_HELP dictionaries) is the short form; its
Detail adds what the setting or example value represents, how a controller selects it
when relevant, where the Bluetooth Core Specification v6.3 (docs/Core_v6.3.pdf)
defines it and what a change does to the plan.
"""

from html import escape
from typing import NamedTuple


class Detail(NamedTuple):
    defines: str
    standard: str
    effect: str
    selection: str = ""
    defines_heading: str = "What it defines"


CONNECTION_CONTROL_HELP = {
    "connection.interval_min": "A range requested during connection setup; not a second timing period.",
    "connection.interval_max": "Upper end of the interval range requested during connection setup. The central selects the actual interval within the range.",
    "connection.latency": "Maximum events the peripheral may skip under allowed conditions. Anchors remain periodic.",
    "connection.timeout": "Maximum time without valid reception before link loss; not an airtime reservation.",
}
CS_CONTROL_HELP = {
    "configuration.mode": "Select the main measurement mode and optional interleaved sub-mode. Mode 1 uses RTT packets, Mode 2 uses PBR tones, and Mode 3 combines both. Every subevent also starts with Mode-0 calibration.",
    "configuration.mode_0_steps": "Number of Mode-0 calibration steps at the start of every subevent (1–3). More calibration steps leave less time for ranging measurements.",
    "configuration.main_mode_repetition": "Number of available main-mode steps repeated from the previous subevent after the Mode-0 prefix (0–3). Repetitions consume time and total steps without advancing the fresh-step workload.",
    "configuration.min_main_mode_steps": "Lower bound on the main-mode run between sub-mode insertions. Keep Minimum main run ≤ Illustrative main run ≤ Maximum main run. This cadence matters only when a sub-mode is enabled. Held at the default and read-only without a sub-mode.",
    "configuration.max_main_mode_steps": "Upper bound on the main-mode run between sub-mode insertions. The controller randomizes the run within the configured bounds; this planner uses Illustrative main run (example values below). Held at the default and read-only without a sub-mode.",
    "configuration.cs_sync_phy": "PHY used for CS_SYNC packets. LE 1M and LE 2M have different packet durations; LE 2M 2BT uses the same bit rate as LE 2M. This choice does not change the ACL connection interval.",
    "configuration.rtt_type": "Optional sounding or random sequence carried in Mode-1/3 CS_SYNC packets. Longer sequences take more airtime and can reduce steps per subevent. AA only omits the optional sequence. Mode-0 packets never include this sequence. Held at the default and read-only without Mode 1 or 3.",
    "procedure.tone_antenna_config_selection": "A and B specify antenna counts on the CS initiator and reflector. Their combination sets the number of antenna paths per tone exchange (for example, A2:B2 gives four paths). More paths increase Mode-2/3 duration; each direction also reserves an extension slot. Held at the default and read-only without Mode 2 or 3.",
    "configuration.cs_enhancements_1": "CS enhancements 1 bit 0 (IPT): the reflector pre-rotates its tones by the phase it measured and reports amplitude only. Needs Mode 2 or 3 and reflector IPT support. When requested, tone switch periods use T_SW_IPT and T_IP2 must come from the reflector's IPT list, so the step, event and schedule timing views change. Sent in the initiator configuration only (creation fields). Held at the default and read-only without Mode 2 or 3.",
}
CHANNEL_CONTROL_HELP = {
    "configuration.channel_map": "CS channels available for hopping. Channel k is centered at 2402 + k MHz. Channels 0–1, 23–25 and 77–78 surround the advertising channels and are never used. At least 15 channels are required.",
    "configuration.channel_map_repetition": "CSNumRepetitions: number of non-mode-0 channel arrays generated per procedure (#3b shuffles or #3c invocations). Each #3b array uses every enabled channel once. The procedure closes when all are used, even if the workload is unfinished. #3c limits this to 1–3 depending on the jump.",
    "configuration.channel_selection_type": "Algorithm ordering the non-mode-0 channels. CSA #3b shuffles the enabled channels; CSA #3c builds Hat or X shaped ramps, mixes in salt channels, filters them by the map and shuffles in blocks. Mode-0 steps always use their own CSA #3a shuffle.",
    "configuration.ch3c_shape": "CSA #3c ramp shape: Hat places a rising ramp before a falling ramp; X interleaves the rising and falling ramps. Held at the default and read-only with CSA #3b.",
    "configuration.ch3c_jump": "CSA #3c channel jump: channel spacing within each ramp (2–8). It selects the ramp start channels, maximum repetitions and salt rate from Table 4.2. Held at the default and read-only with CSA #3b.",
}
SCHEDULE_CONTROL_HELP = {
    "procedure.subevent_len": "Subevent length for this prediction, in microseconds (1250–4000000). Steps are packed into each subevent while they fit. The planner shows the calculated minimum for the first fresh step, including its Mode-0 prefix. Arrow buttons change by 1,000 µs; type any whole-microsecond value for fine adjustment. Sent as the minimum and maximum suggested subevent length (equal, unless a loaded range is kept while this value is unchanged); the controller selects the actual length.",
    "procedure.max_procedure_len": "Maximum duration of each procedure, in 625 µs units (1–65535). Subevents that would run past it are shortened or dropped, which can leave the workload incomplete. Sent as the maximum procedure length.",
    "procedure.procedure_interval": "ACL connection intervals from the start of one procedure to the next (1–65535). A repeating procedure must end at least 150 µs before the next begins; ignored when Procedure count is 1. Sent as the minimum and maximum procedure interval (equal, unless a loaded range is kept while this value is unchanged); the controller selects the actual interval.",
    "procedure.procedure_count": "Number of consecutive procedures; 0 repeats until disabled. Sent as the maximum procedure count. The Procedures view draws at most Preview instances (example values below).",
}
HOST_CONTROL_HELP = {
    "gap_role": "GAP role on the connection, independent of the CS role. Central scans for and connects to a peer whose name starts with a Peripheral prefix; Peripheral advertises and waits for a connection.",
    "cs_sync_antenna_selection": "Local antenna for CS_SYNC packets: a fixed antenna (ANT1–ANT4, within the controller's antenna count) or all antennas in repetitive order. No recommendation leaves the choice to the controller. Sent in the CS default settings.",
    "max_tx_power": "Maximum output power (EIRP) for all CS transmissions, in dBm (−127 to 20). The controller caps it at its own maximum and otherwise uses the closest lower power it supports. Sent in the CS default settings.",
    "phy": "Reference PHY for TX power delta: the delta is relative to the peer's power level on this PHY. It does not change the ACL connection PHY or the CS_SYNC PHY. Sent in the procedure parameters. The views also assume the ACL runs on it, which sets the air time of the RAS real-time transfer.",
    "tx_power_delta": "Recommended difference, in signed dB, between the peer's power for CS tones and CS_SYNC packets and its power on the procedure PHY. −128 means no recommendation. The controller may adjust it to the peer's supported power range. Sent in the procedure parameters.",
    "preferred_peer_antenna": "Peer antennas this device prefers the peer to use, in the peer's antenna order: check ANT1–ANT4 (bits 0–3 of the mask shown beside them, for example 0x03 = first and second). Check at least as many as the peer's antenna count in the antenna configuration (B for an initiator, A for a reflector); a warning beside the boxes shows the count while fewer are checked. Sent in the procedure parameters. Held at the default and read-only without Mode 2 or 3.",
    "snr_control_initiator": "SNR control adjustment for the initiator's CS_SYNC transmissions (18–30 dB), or Not used. Sent in the procedure parameters. Held at the default and read-only without Mode 1 or 3.",
    "snr_control_reflector": "SNR control adjustment for the reflector's CS_SYNC transmissions (18–30 dB), or Not used. Sent in the procedure parameters. Held at the default and read-only without Mode 1 or 3.",
    "creation_context": "Where the initiator writes the CS configuration. Local: the local controller only. Local and remote: also the peer, through the CS configuration procedure. Initiator configuration only: held at the default and read-only for a reflector configuration.",
    "peer_data": "Reflector data for CS initiator runs: RAS real-time includes reflector subevents for amplitude weighting and RTT timing; None (initiator only) relies on IPT and omits RAS notifications. Enabled only when IPT is requested for an initiator configuration. With RAS real-time the Connection and Procedures views draw the transfer on the ACL events after each procedure.",
    "t_pm": "Phase measurement period the CS initiator asks its controller to use for every tone slot. The UI defaults to the Bluetooth Core Specification's mandatory 40 µs option. 20 µs is conditional and 10 µs is optional; selecting either 20 or 40 µs sends SET_T_PM before each CS configuration, while 10 µs sends nothing and leaves the controller's own preference. Selecting a requested value also sets the example T_PM, so the prediction follows it; configuration complete reports the value actually in use. Enabled only for an initiator configuration with Mode 2 or 3.",
    "peripheral_patterns": "Scan filter for a central: connect only to peers whose advertised name starts with one of these case-sensitive prefixes (1–8 lines, 1–32 bytes each). Unused as a peripheral.",
}
GENERAL_CONTROL_HELP = {
    "operation_mode": "Selects CS or CS Hostless operation. Radio Test is temporarily disabled. Choose the CS initiator or reflector role in the CS setup tab.",
    "gap_role": HOST_CONTROL_HELP["gap_role"],
    "peripheral_patterns": HOST_CONTROL_HELP["peripheral_patterns"],
    "device_name": "This board's advertised Bluetooth name, 1–32 UTF-8 bytes. Empty uses the firmware default.",
    "log_console": "Messages at this level and below are sent to the client's local debug console (UART or RTT).",
    "log_host": "Messages at this level and below are sent to the host as LOG_MESSAGE frames.",
}
EXAMPLE = " Example value: not sent to the client or exported to C."
TIMING_IP_VALUES = "10, 20, 30, 40, 50, 60, 80, 145 µs"
TIMING_FCS_VALUES = "15, 20, 30, 40, 50, 60, 80, 100, 120, 150 µs"
TIMING_PM_VALUES = "10, 20, 40 µs"
TIMING_SWITCH_VALUES = "0, 1, 2, 4, 10 µs"
TIMING_MANDATORY_VALUES = {
    "configuration.t_ip1_time_us": "145 µs",
    "configuration.t_ip2_time_us": "145 µs",
    "configuration.t_fcs_time_us": "150 µs",
    "configuration.t_pm_time_us": "40 µs",
}
TIMING_SELECTION_NOTE = (
    "The controller selects this value during the Channel Sounding Configuration procedure, after the "
    "Channel Sounding Capabilities Exchange. Selection is constrained by the local controller's "
    "capability bitmask, the peer controller's capability bitmask/constraint, and mandatory or "
    "conditional support."
)
CONTROLLER_SELECTED_NOTE = (
    "At runtime, T_IP1, T_IP2, T_FCS and T_PM are selected during the Channel Sounding Configuration "
    "procedure after the Channel Sounding Capabilities Exchange. Selection is constrained by the local "
    "controller's capability bitmask, the peer controller's capability bitmask/constraint, mandatory "
    "or conditional support, and, for IPT, the reflector's T_IP2_IPT capability. The mandatory values "
    "are T_IP1/T_IP2 = 145 µs, T_FCS = 150 µs and T_PM = 40 µs; the other listed values are optional "
    "shorter durations. Possible values are T_IP1/T_IP2 = 10, 20, 30, "
    "40, 50, 60, 80 or 145 µs; T_FCS = 15, 20, 30, 40, 50, 60, 80, 100, 120 or 150 µs; and T_PM = 10, 20 or 40 µs."
)
# Kept as compatibility aliases for callers that imported the old names. The UI now presents
# these as neutral selection notes rather than warnings.
TIMING_SELECTION_WARNING = TIMING_SELECTION_NOTE
CONTROLLER_SELECTED_WARNING = CONTROLLER_SELECTED_NOTE


def timing_selection(mandatory, ipt=False):
    note = (f"{TIMING_SELECTION_NOTE} The mandatory supported value is {mandatory}; the other listed "
            "values are optional shorter durations.")
    if ipt:
        note += " With IPT, T_IP2 also has to come from the reflector's T_IP2_IPT capability list."
    return note


def timing_tooltip(description, values, suffix="", mandatory=None):
    support = (f" The mandatory supported value is {mandatory}; the other listed values are optional shorter durations."
               if mandatory else "")
    return f"{description} Possible values: {values}. {TIMING_SELECTION_NOTE}{support}{suffix}" + EXAMPLE


EXAMPLE_CONTROL_HELP = {
    "connection.activity_us": "Assumed ACL airtime at each anchor, in microseconds, for the Connection view. Actual airtime depends on PHY, packets and traffic." + EXAMPLE,
    "event_offset_us": "Start of the first CS subevent after its ACL anchor, in microseconds. Not present in any controller report; a planning assumption." + EXAMPLE,
    "main_steps": "Fixed number of main-mode steps before each sub-mode step in this prediction. Must be within Minimum/Maximum main run; the controller randomizes the run within those bounds. The cadence continues across subevent boundaries. Held at the default and read-only without a sub-mode." + EXAMPLE,
    "target_steps": "Fresh steps the procedure should complete (1–256): main- and sub-mode steps, excluding Mode-0 and repeated main steps. Not a distinct-channel count. Steps are packed into subevents until the workload is placed or a limit stops it." + EXAMPLE,
    "preview_count": "Procedure instances drawn in the Procedures view (1–10)." + EXAMPLE,
    "channel_seed": "Seed for the stand-in random generator used by the Channels view. The real hop sequence depends on the CS DRBG state, derived from security setup and advancing every procedure, so it cannot be predicted offline. Change the seed to see other possible sequences with the same structure." + EXAMPLE,
    "connection.interval": "Spacing between consecutive ACL anchor points. The central selects it within the requested minimum and maximum." + EXAMPLE,
    "connection.mtu": "ATT MTU of the link, in bytes: 23 until an MTU exchange raises it, and the value a client reports with the connection parameters once there is a link. It sizes the reflector's RAS real-time transfer in the Connection and Procedures views and nothing else; the host never requests an MTU." + EXAMPLE,
    "configuration.t_ip1_time_us": timing_tooltip("Interlude between the initiator and reflector exchanges in Mode-0 and Mode-1, in microseconds. Increasing T_IP1 lengthens those steps.", TIMING_IP_VALUES, mandatory="145 µs"),
    "configuration.t_ip2_time_us": timing_tooltip("Interlude between the initiator and reflector tone-bearing exchanges in Mode-2 and Mode-3, in microseconds. Increasing T_IP2 lengthens those steps. With IPT it comes from the reflector's T_IP2_IPT capability list.", TIMING_IP_VALUES, " Held at the default and read-only without Mode 2 or 3.", mandatory="145 µs"),
    "configuration.t_fcs_time_us": timing_tooltip("Frequency-change and settling gap between consecutive steps in a subevent, in microseconds. Each gap consumes subevent capacity; no trailing gap is charged after the last step.", TIMING_FCS_VALUES, mandatory="150 µs"),
    "configuration.t_pm_time_us": timing_tooltip("Phase-measurement duration of each tone slot in microseconds. It applies to every antenna-path slot and the reserved extension slot in both directions; longer T_PM increases Mode-2/3 duration. A CS initiator can ask for 20 or 40 µs with Preferred T_PM, which also sets this example value.", TIMING_PM_VALUES, " Held at the default and read-only without Mode 2 or 3.", mandatory="40 µs"),
    "t_sw_us": "Antenna switching/settling time before each tone measurement slot, in microseconds. Possible values: " + TIMING_SWITCH_VALUES + ". Each device declares it in its CS capabilities; the planner's 2 µs default is an example, not a mandatory value. Held at the default and read-only without Mode 2 or 3, or when IPT is requested." + EXAMPLE,
    "t_sw_ipt_us": "Antenna switching/settling time used instead of T_SW when IPT is requested, in microseconds. Possible values: " + TIMING_SWITCH_VALUES + ". The reflector declares it in its CS capabilities, separately from T_SW; the planner's 2 µs default is an example, not a mandatory value. Held at the default and read-only unless IPT is requested with Mode 2 or 3." + EXAMPLE,
    "procedure.subevents_per_event": "Subevents in each CS event (1–32). Selected by the controller and reported at procedure enable complete." + EXAMPLE,
    "procedure.subevent_interval": "Start-to-start spacing of subevents within a CS event, in 625 µs units. Must be 0 with one subevent per event (held at 0 and read-only then); otherwise longer than Subevent budget + 150 µs. Selected by the controller and reported at procedure enable complete." + EXAMPLE,
    "procedure.event_interval": "ACL connection intervals from the start of one CS event to the next within a procedure (1–65535). Must leave at least 150 µs after the event's last subevent. Selected by the controller and reported at procedure enable complete." + EXAMPLE,
}
ROLE_HELP = ("CS role for the host configuration packet. The integrated client currently supports only Initiator; "
             "the role is fixed until reflector mode is supported.")

# Core v6.3 locations cited by several entries.
CREATE_CONNECTION = "Vol 4, Part E, §7.8.12 HCI_LE_Create_Connection (and §7.8.66 HCI_LE_Extended_Create_Connection)"
CAPABILITIES = "Vol 4, Part E, §7.8.130 HCI_LE_CS_Read_Local_Supported_Capabilities"
DEFAULT_SETTINGS = "Vol 4, Part E, §7.8.134 HCI_LE_CS_Set_Default_Settings"
CREATE_CONFIG = "Vol 4, Part E, §7.8.137 HCI_LE_CS_Create_Config"
PROCEDURE_PARAMETERS = "Vol 4, Part E, §7.8.140 HCI_LE_CS_Set_Procedure_Parameters"
CONFIG_COMPLETE = "Vol 4, Part E, §7.7.65.42 HCI_LE_CS_Config_Complete"
ENABLE_COMPLETE = "Vol 4, Part E, §7.7.65.43 HCI_LE_CS_Procedure_Enable_Complete"
CONFIG_PROCEDURE = "Vol 6, Part B, §5.1.25 (CS Configuration procedure, LL_CS_CONFIG_REQ)"
START_PROCEDURE = "Vol 6, Part B, §5.1.26 (CS Start procedure, LL_CS_REQ / LL_CS_RSP / LL_CS_IND)"
CS_PROCEDURES = "Vol 6, Part B, §4.5.18.1 (CS procedures and subevents)"
NO_TIMING = "It does not change the timing prediction."


def negotiated_timing(name, sections, capability, values, mandatory):
    """Where the standard defines a step timing value selected by the controllers."""
    return (f"Vol 6, Part H, {sections}. Possible values: {values}. The mandatory supported value is "
            f"{mandatory}; the other listed values are optional shorter durations. Selected in LL_CS_CONFIG_REQ "
            f"(Vol 6, Part B, §5.1.25) from {capability} (Vol 4, Part E, §7.8.130); the resulting "
            f"value is reported as {name} in {CONFIG_COMPLETE}.")


CONTROL_DETAILS = {
    # Connection
    "connection.interval_min": Detail(
        "This setting defines Connection_Interval_Min, the shortest ACL connection interval requested, in LE Create Connection.",
        f"{CREATE_CONNECTION}: Connection_Interval_Min, 0x0006–0x0C80 × 1.25 ms (7.5 ms–4 s). connInterval: Vol 6, Part B, §4.5.1.",
        "Bounds Selected interval from below; validation requires Requested minimum ≤ Selected interval. The request does not "
        "move the views by itself: they follow Selected interval."),
    "connection.interval_max": Detail(
        "This setting defines Connection_Interval_Max, the longest ACL connection interval requested, in LE Create Connection.",
        f"{CREATE_CONNECTION}: Connection_Interval_Max, 0x0006–0x0C80 × 1.25 ms. connInterval: Vol 6, Part B, §4.5.1.",
        "Bounds Selected interval from above; validation requires Selected interval ≤ Requested maximum. The request does not "
        "move the views by itself: they follow Selected interval."),
    "connection.latency": Detail(
        "This setting defines Max_Latency (connPeripheralLatency), the connection events the peripheral may skip, in LE Create Connection.",
        f"{CREATE_CONNECTION}: Max_Latency, 0x0000–0x01F3. connPeripheralLatency: Vol 6, Part B, §4.5.1.",
        "Raises the shortest valid supervision timeout: validation requires Supervision timeout > 2 × (latency + 1) × Selected "
        "interval. The Connection view marks the events the peripheral may skip. ACL anchors, CS events and step timing do not move."),
    "connection.timeout": Detail(
        "This setting defines Supervision_Timeout (connSupervisionTimeout), the time without a valid packet before the link is lost, in LE Create Connection.",
        f"{CREATE_CONNECTION}: Supervision_Timeout, 0x000A–0x0C80 × 10 ms. Supervision timeout: Vol 6, Part B, §4.5.2.",
        "Changes only the lower timeline of the Connection view. It must exceed 2 × (Peripheral latency + 1) × Selected interval, "
        "so raising latency or the interval can make it invalid. It reserves no airtime and does not change the CS schedule."),
    "connection.interval": Detail(
        "This setting defines connInterval, the ACL connection interval the central selects within the requested range.",
        f"Vol 6, Part B, §4.5.1 (connInterval), selected at connection setup from the range in {CREATE_CONNECTION}. "
        "No CS command or event carries it.",
        "Sets the anchor spacing in the Connection view. Procedure spacing and CS event spacing count in connection intervals, so "
        "the procedure and event periods, the Procedures view and the CS event spacing check (event span + 150 µs) scale with it. "
        "It must lie within Requested minimum–maximum and enters the supervision timeout check. Steps per subevent do not change."),
    "connection.activity_us": Detail(
        "This setting defines the airtime drawn at each ACL anchor in the Connection view. It is a drawing assumption, not a protocol parameter.",
        "No Core Specification parameter. Connection event length depends on the packets exchanged (Vol 6, Part B, §4.5.1 and §4.5.6).",
        "Changes only the width of the ACL blocks in the Connection view. It must be shorter than Selected interval; 0 hides them."),
    "connection.mtu": Detail(
        "This setting defines the ATT MTU the link uses, which decides how the reflector's ranging data is segmented "
        "into notifications. It is not a host parameter: the host never requests an MTU.",
        "Vol 3, Part F, §3.4.2 (ATT_EXCHANGE_MTU_REQ) and §5.2.1: a link starts at the default ATT_MTU of 23 and "
        "keeps it unless a client exchanges a larger one. Ranging Service 1.0 segments ranging data at MTU - 4.",
        "Changes the notification count, the LL PDUs and the air time drawn in the RAS (reflector) lane; it changes "
        "no CS step, subevent or procedure timing. A client reports the negotiated value with the connection "
        "parameters and replaces what is shown here; 23 is what a link that never exchanged an MTU uses."),
    "event_offset_us": Detail(
        "This setting defines T_EVENT_OFFSET, the time from an ACL anchor point to the start of the CS event.",
        f"{CS_PROCEDURES} (T_EVENT_OFFSET); negotiated in {START_PROCEDURE} (Offset_Min, Offset_Max). No HCI command or event carries it.",
        "Shifts every subevent, CS event and procedure instance later on the shared time origin (Connection, Procedures, Events and "
        "Step views). Durations, steps per subevent and validation do not change."),
    # CS modes
    "configuration.mode": Detail(
        "This setting defines Main_Mode_Type and Sub_Mode_Type in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Main_Mode_Type (1–3), Sub_Mode_Type (1–3 or 0xFF unused); reported in {CONFIG_COMPLETE}. "
        "Step structures: Vol 6, Part H, §4.3.1–4.3.4. Sub_Mode insertion: §4.4.3.",
        "Changes the structure and duration of the main-mode steps, so steps per subevent, subevents and procedure duration change. "
        "Enables Minimum/Maximum main run and Illustrative main run with a sub-mode; RTT sequence and SNR control with Mode 1 or 3; "
        "T_IP2, T_PM, T_SW, Antenna configuration, IPT and Preferred peer antenna with Mode 2 or 3. Controls that become unused "
        "return to their defaults and turn read-only."),
    "configuration.mode_0_steps": Detail(
        "This setting defines Mode_0_Steps, the mode-0 calibration steps at the start of every CS subevent, in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Mode_0_Steps, 0x01–0x03. Mode-0 step: Vol 6, Part H, §4.3.1. Subevent structure: §4.4.2.",
        "Each extra mode-0 step takes subevent time and counts toward the 256 steps of a procedure without advancing the workload, "
        "so fewer fresh steps fit per subevent and the procedure needs more subevents or stops at a limit. Mode-0 channels come "
        "from CSA #3a."),
    "configuration.main_mode_repetition": Detail(
        "This setting defines Main_Mode_Repetition, the main-mode steps from the end of the previous subevent repeated after the "
        "mode-0 steps, in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Main_Mode_Repetition, 0x00–0x03. Main_mode repetition: Vol 6, Part H, §4.4.4.",
        "Repeated steps reuse earlier channels and take subevent time without advancing the workload, so fewer fresh steps fit per "
        "subevent. They are marked R in the Events view and hollow in the Channels view."),
    "configuration.min_main_mode_steps": Detail(
        "This setting defines Min_Main_Mode_Steps, the fewest main-mode steps before a sub-mode step, in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Min_Main_Mode_Steps, 0x01–0xFF. Sub_Mode insertion: Vol 6, Part H, §4.4.3.",
        "Bounds Illustrative main run from below; the prediction follows Illustrative main run, so the schedule changes only "
        "through it. Minimum ≤ Illustrative ≤ Maximum main run is required. Read-only at the default without a sub-mode."),
    "configuration.max_main_mode_steps": Detail(
        "This setting defines Max_Main_Mode_Steps, the most main-mode steps before a sub-mode step, in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Max_Main_Mode_Steps, 0x01–0xFF. Sub_Mode insertion: Vol 6, Part H, §4.4.3.",
        "Bounds Illustrative main run from above; the prediction follows Illustrative main run, so the schedule changes only "
        "through it. Minimum ≤ Illustrative ≤ Maximum main run is required. Read-only at the default without a sub-mode."),
    "configuration.cs_sync_phy": Detail(
        "This setting defines CS_SYNC_PHY, the PHY of CS_SYNC packets, in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: CS_SYNC_PHY (0x01 LE 1M, 0x02 LE 2M, 0x03 LE 2M 2BT); reported in {CONFIG_COMPLETE}. "
        "Packet formats: Vol 6, Part H, §2.",
        "Changes the CS_SYNC packet duration of mode-0, mode-1 and mode-3 steps, and with it steps per subevent. Mode-2 steps carry "
        "no CS_SYNC packet. The ACL PHY and the procedure PHY (Host tab) do not change."),
    "configuration.rtt_type": Detail(
        "This setting defines RTT_Type, the sounding or random sequence added to mode-1 and mode-3 CS_SYNC packets, in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: RTT_Type, 0x00–0x06. Sounding sequence: Vol 6, Part H, §2.4. Random sequence: §2.5. RTT: §3.",
        "A longer sequence lengthens every mode-1 and mode-3 step, so fewer steps fit per subevent. Mode-0 packets do not change. "
        "Read-only at AA only without Mode 1 or 3."),
    "procedure.tone_antenna_config_selection": Detail(
        "This setting defines Tone_Antenna_Config_Selection, the antenna configuration index (A initiator antennas : B reflector "
        "antennas), in HCI_LE_CS_Set_Procedure_Parameters.",
        f"{PROCEDURE_PARAMETERS}: Tone_Antenna_Config_Selection, 0x00–0x07; reported in {ENABLE_COMPLETE}. "
        "Antenna switching: Vol 6, Part H, §4.7. Tone extension slots: §4.4.1.",
        "Sets the number of antenna paths N_AP (1–4). A mode-2 or mode-3 step has N_AP + 1 tone slots (T_SW + T_PM each, the last "
        "an extension slot) per direction, so its duration grows with the paths and fewer steps fit per subevent; the Step view "
        "shows the slots. Preferred peer antenna must cover the peer's antennas. Read-only without Mode 2 or 3."),
    "configuration.cs_enhancements_1": Detail(
        "This setting defines bit 0 (IPT enabled in the CS reflector) of CS_Enhancements in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: CS_Enhancements. Support: T_IP2_IPT_Times_Supported and T_SW_IPT_Times_Supported in {CAPABILITIES}. "
        f"Mode-2 and mode-3 steps: Vol 6, Part H, §4.3.3–4.3.4. Selection rule: {CONFIG_PROCEDURE}.",
        "When requested, tone switch periods use T_SW_IPT instead of T_SW (T_SW turns read-only, T_SW_IPT editable), so mode-2 and "
        "mode-3 step durations change. The Step view marks the pre-rotated reflector tones and reports the T_RD + T_IP2 margin. "
        "Needs Mode 2 or 3; otherwise read-only at Off."),
    "main_steps": Detail(
        "This setting defines the main-mode run the prediction places before each sub-mode step. The controller picks a random run "
        "between Min_Main_Mode_Steps and Max_Main_Mode_Steps instead.",
        f"No parameter carries it. Sub_Mode insertion: Vol 6, Part H, §4.4.3; bounds: {CREATE_CONFIG}.",
        "Moves the sub-mode steps within the subevents, so the mix of step durations, steps per subevent and the channels reused by "
        "mode-1 sub-mode steps change. Must lie within Minimum/Maximum main run. Read-only without a sub-mode."),
    "configuration.t_ip1_time_us": Detail(
        "This example value represents T_IP1, the interlude between the initiator and reflector transmissions of a mode-0 or mode-1 step. The planner uses it to model timing until the controller reports the value actually selected.",
        negotiated_timing("T_IP1_Time", "§4.3.1–4.3.2 (T_IP1 values and step structures)", "T_IP1_Times_Supported", TIMING_IP_VALUES, "145 µs"),
        "Lengthens or shortens every mode-0 and mode-1 step (mode-1 sub-mode steps too), so steps per subevent and the number of "
        "subevents change. Mode-2 and mode-3 steps do not change.",
        timing_selection("145 µs"),
        "What this example represents"),
    "configuration.t_ip2_time_us": Detail(
        "This example value represents T_IP2, the interlude between the initiator and reflector tone transmissions of a mode-2 or mode-3 step. The planner uses it to model timing until the controller reports the value actually selected.",
        negotiated_timing("T_IP2_Time", "§4.3.3–4.3.4", "T_IP2_Times_Supported, or T_IP2_IPT_Times_Supported with IPT,", TIMING_IP_VALUES, "145 µs"),
        "Lengthens or shortens every mode-2 and mode-3 step. With IPT it also sets the reflector's T_RD + T_IP2 phase budget "
        "reported in the Step view. Read-only without Mode 2 or 3.",
        timing_selection("145 µs", ipt=True),
        "What this example represents"),
    "configuration.t_fcs_time_us": Detail(
        "This example value represents T_FCS, the frequency change and settling period between consecutive steps. The planner uses it to model timing until the controller reports the value actually selected.",
        negotiated_timing("T_FCS_Time", "§4.3 (Table 4.3, permitted T_FCS values)", "T_FCS_Times_Supported", TIMING_FCS_VALUES, "150 µs"),
        "Adds one gap per step boundary inside a subevent (none after the last step), so every step costs more or less subevent "
        "time. The Events view draws the gaps; the individual step duration excludes them.",
        timing_selection("150 µs"),
        "What this example represents"),
    "configuration.t_pm_time_us": Detail(
        "This example value represents T_PM, the phase measurement period of each tone slot in a mode-2 or mode-3 step. The planner uses it to model timing until the controller reports the value actually selected.",
        negotiated_timing("T_PM_Time", "§4.3.3–4.3.4 and §4.6 (phase measurements during T_PM)", "T_PM_Times_Supported", TIMING_PM_VALUES, "40 µs"),
        "Applies to every antenna-path slot and the extension slot in both directions, so a change counts 2 × (N_AP + 1) times per "
        "mode-2 or mode-3 step. Read-only without Mode 2 or 3.",
        timing_selection("40 µs"),
        "What this example represents"),
    "t_sw_us": Detail(
        "This setting defines T_SW, the antenna switch period before each tone slot of a mode-2 or mode-3 step.",
        f"T_SW_Time_Supported (0, 1, 2, 4 or 10 µs) in {CAPABILITIES}, exchanged in the CS Capabilities Exchange procedure "
        "(Vol 6, Part B, §5.1.24). Antenna switching: Vol 6, Part H, §4.7.",
        "Counts 2 × (N_AP + 1) times per mode-2 or mode-3 step, like T_PM. Read-only without Mode 2 or 3, or when IPT is requested "
        "(T_SW_IPT applies then)."),
    "t_sw_ipt_us": Detail(
        "This setting defines T_SW_IPT, the antenna switch period used instead of T_SW when IPT is enabled.",
        f"T_SW_IPT_Times_Supported (0, 1, 2, 4 or 10 µs) in {CAPABILITIES}. IPT steps: Vol 6, Part H, §4.3.3–4.3.4.",
        "With IPT, every tone slot of a mode-2 or mode-3 step uses this switch period, so step durations follow it. Editable only "
        "when IPT is requested with Mode 2 or 3."),
    # Schedule
    "procedure.subevent_len": Detail(
        "This setting defines Min_Subevent_Len and Max_Subevent_Len (sent equal) in HCI_LE_CS_Set_Procedure_Parameters.",
        f"{PROCEDURE_PARAMETERS}: Min_Subevent_Len, Max_Subevent_Len, 1250 µs–4 s; the selected Subevent_Len is reported in "
        f"{ENABLE_COMPLETE}. T_SUBEVENT_LEN: {CS_PROCEDURES}.",
        "The planner shows the minimum budget needed for one fresh step after its Mode-0 prefix. Arrow buttons step by 1,000 µs, while typed values retain 1 µs resolution. Sets how many steps fit per subevent (at most 160), so the number of subevents and CS events and the procedure duration "
        "change. With several subevents per event, Subevent spacing must exceed it by 150 µs; CS event spacing must cover the event."),
    "procedure.max_procedure_len": Detail(
        "This setting defines Max_Procedure_Len, the longest duration of a CS procedure, in HCI_LE_CS_Set_Procedure_Parameters.",
        f"{PROCEDURE_PARAMETERS}: Max_Procedure_Len, 0x0001–0xFFFF × 0.625 ms; reported in {ENABLE_COMPLETE}. "
        "Procedure closing conditions: Vol 6, Part H, §4.2.",
        "A procedure closes when its next step would run past it, which can leave the workload incomplete. The Procedures view "
        "draws it as the Budget block. Step and subevent durations do not change."),
    "procedure.procedure_interval": Detail(
        "This setting defines Min_Procedure_Interval and Max_Procedure_Interval (sent equal), the connection intervals between "
        "procedure starts, in HCI_LE_CS_Set_Procedure_Parameters.",
        f"{PROCEDURE_PARAMETERS}: Min_Procedure_Interval, Max_Procedure_Interval; Procedure_Interval in {ENABLE_COMPLETE}. "
        f"T_PROCEDURE_INTERVAL: {CS_PROCEDURES}.",
        "Spaces the procedure instances in the Procedures view by this many Selected intervals. A repeating procedure must end "
        "before the next one starts. Ignored when Procedure count is 1."),
    "procedure.procedure_count": Detail(
        "This setting defines Max_Procedure_Count, the number of consecutive CS procedures (0: until disabled), in "
        "HCI_LE_CS_Set_Procedure_Parameters.",
        f"{PROCEDURE_PARAMETERS}: Max_Procedure_Count; Procedure_Count in {ENABLE_COMPLETE}. N_PROCEDURE_COUNT: {CS_PROCEDURES}.",
        "The Procedures view draws up to Preview instances of it; each instance repeats the same schedule. With 1, Procedure "
        "spacing has no effect."),
    "target_steps": Detail(
        "This setting defines the number of fresh steps (main- and sub-mode steps, not mode-0 or repeated steps) the prediction "
        "places in one procedure.",
        "No parameter carries it. A procedure closes at Max_Procedure_Len, 256 steps, 32 subevents or when its channel arrays are "
        f"used up (Vol 6, Part H, §4.2); 160 steps per subevent ({CS_PROCEDURES}).",
        "More steps need more subevents and CS events, so the procedure lasts longer and may stop at Procedure budget, the step or "
        "subevent limits or the channel arrays set by Map repetition. The status line names the limit that stopped it."),
    "procedure.subevents_per_event": Detail(
        "This setting defines Subevents_Per_Event, the number of CS subevents in each CS event, which the controllers select.",
        f"N_SUBEVENTS_PER_EVENT: {CS_PROCEDURES}; selected in {START_PROCEDURE}; reported in {ENABLE_COMPLETE} (1–32).",
        "More subevents per event put more steps in each CS event, so fewer CS events are needed. With 1, Subevent spacing is held "
        "at 0 and read-only; with more, it must exceed Subevent budget + 150 µs and CS event spacing must cover the longer event."),
    "procedure.subevent_interval": Detail(
        "This setting defines Subevent_Interval, the start-to-start spacing of subevents in a CS event, in 625 µs units.",
        f"T_SUBEVENT_INTERVAL: {CS_PROCEDURES}; selected in {START_PROCEDURE}; reported in {ENABLE_COMPLETE}.",
        "Moves the later subevents of each event in the Events view and lengthens the event, which CS event spacing must cover "
        "plus 150 µs. Must be 0 with one subevent per event (read-only then), otherwise longer than Subevent budget + 150 µs."),
    "procedure.event_interval": Detail(
        "This setting defines Event_Interval, the connection intervals between the starts of consecutive CS events in a procedure.",
        f"T_EVENT_INTERVAL: {CS_PROCEDURES}; selected in {START_PROCEDURE}; reported in {ENABLE_COMPLETE}.",
        "Spaces CS events by this many Selected intervals, so the elapsed procedure time grows with it while steps per subevent "
        "stay the same. It must leave at least 150 µs after the event's last subevent."),
    "preview_count": Detail(
        "This setting defines how many procedure instances the Procedures view draws and the Procedure selector offers.",
        "No Core Specification parameter.",
        "Changes only the Procedures view and the Procedure selector, up to Procedure count when that is not 0."),
    # Channels
    "configuration.channel_map": Detail(
        "This setting defines Channel_Map, the CS channels the configuration may use, in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Channel_Map, 10 octets, bits 0, 1, 23–25, 77 and 78 reserved; reported in {CONFIG_COMPLETE}. "
        "Channel use: Vol 6, Part H, §4.2. Later updates: HCI_LE_CS_Set_Channel_Classification (Vol 4, Part E, §7.8.139) and the "
        "CS Channel Map Update procedure (Vol 6, Part B, §5.1.28).",
        "Each non-mode-0 channel array holds the enabled channels, so a smaller map closes the procedure after fewer steps "
        "(Map repetition arrays), which can leave the workload incomplete. At least 15 allowed channels are required. The "
        "Channels view and its Wi-Fi overlap counts follow the map; step timing does not change."),
    "configuration.channel_map_repetition": Detail(
        "This setting defines Channel_Map_Repetition (CSNumRepetitions), the number of non-mode-0 channel arrays a procedure uses, "
        "in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Channel_Map_Repetition, 0x01–0xFF. Non-mode-0 channel selection: Vol 6, Part H, §4.1.4. "
        "Procedure closing: §4.2. #3c limits: Table 4.2 (§4.1.4.2.1).",
        "More arrays let a procedure run more non-mode-0 steps before it closes; fewer can stop the workload early (channel map "
        "cycles exhausted). With CSA #3c the jump limits it to 1–3."),
    "configuration.channel_selection_type": Detail(
        "This setting defines Channel_Selection_Type, the algorithm that orders non-mode-0 channels, in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Channel_Selection_Type (0x00 #3b, 0x01 #3c). CSA #3b: Vol 6, Part H, §4.1.4.1. CSA #3c: §4.1.4.2. "
        "Mode-0 steps: CSA #3a, §4.1.3.",
        "Changes the example hop order in the Channels view and, with #3c, the array contents and the Map repetition limit. #3c "
        "enables #3c shape and #3c jump; #3b holds them read-only at their defaults. Step timing does not change."),
    "configuration.ch3c_shape": Detail(
        "This setting defines Ch3c_Shape, the ramp shape of CSA #3c (Hat or X), in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Ch3c_Shape. Shape generation: Vol 6, Part H, §4.1.4.2.2.",
        "Changes only the example hop order in the Channels view. Read-only with CSA #3b."),
    "configuration.ch3c_jump": Detail(
        "This setting defines Ch3c_Jump, the channel spacing within each CSA #3c ramp, in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Ch3c_Jump, 2–8. Parameter blocks: Vol 6, Part H, §4.1.4.2.1 (Table 4.2).",
        "Selects the ramp start channels, salt rate and largest Map repetition, so the example hop order and the number of "
        "arrays change; a Map repetition above the jump's limit is an error. Read-only with CSA #3b."),
    "channel_seed": Detail(
        "This setting defines the seed of the stand-in random generator the Channels view uses for its shuffles.",
        "No parameter carries it. Real shuffles use the CS DRBG (Vol 6, Part H, §4.8), set up by the CS Security Start procedure "
        "(Vol 6, Part B, §5.1.23).",
        "Changes only the example channel of each step (Channels, Events and Step views). Timing and validation do not change."),
    # Host and toolbar
    "configuration.role": Detail(
        "This setting defines Role, whether this device is the CS initiator or the CS reflector of the configuration.",
        f"{CREATE_CONFIG}: Role; Role_Enable in {DEFAULT_SETTINGS}. Role selection: {CONFIG_PROCEDURE}.",
        "Selects the initiator or reflector configuration packet. A reflector configuration holds Creation context read-only at "
        "its default, because the initiator creates the configuration. " + NO_TIMING),
    "gap_role": Detail(
        "This setting defines the GAP role of this device: Central (scans and connects) or Peripheral (advertises).",
        "Vol 3, Part C, §2.2.2.3 (Peripheral role) and §2.2.2.4 (Central role).",
        "A central creates the connection with the Connection tab's requested parameters and filters peers by Peripheral "
        "prefixes; a peripheral ignores the prefixes. Independent of the CS role. " + NO_TIMING),
    "cs_sync_antenna_selection": Detail(
        "This setting defines CS_SYNC_Antenna_Selection, the local antenna for CS_SYNC packets, in HCI_LE_CS_Set_Default_Settings.",
        f"{DEFAULT_SETTINGS}: CS_SYNC_Antenna_Selection (0x01–0x04, 0xFE repetitive, 0xFF no recommendation). "
        f"Antenna count: Num_Antennae_Supported in {CAPABILITIES}.",
        "Chooses the antenna for CS_SYNC packets; a fixed antenna must exist on the controller. " + NO_TIMING),
    "max_tx_power": Detail(
        "This setting defines Max_TX_Power, the maximum power of all CS transmissions, in HCI_LE_CS_Set_Default_Settings.",
        f"{DEFAULT_SETTINGS}: Max_TX_Power, −127 to +20 dBm. The power used is reported as Selected_TX_Power in {ENABLE_COMPLETE}.",
        "Caps the CS transmit power. " + NO_TIMING),
    "phy": Detail(
        "This setting defines PHY, the PHY that Tx_Power_Delta refers to, in HCI_LE_CS_Set_Procedure_Parameters.",
        f"{PROCEDURE_PARAMETERS}: PHY (0x01 LE 1M, 0x02 LE 2M, 0x03 LE Coded S=8, 0x04 LE Coded S=2).",
        "Changes the reference of TX power delta only; the ACL PHY and CS_SYNC PHY stay as they are. The value is "
        "reused as the assumed ACL PHY, so it scales the RAS real-time air time drawn in the Connection and "
        "Procedures views; it changes no CS step, subevent or procedure timing."),
    "tx_power_delta": Detail(
        "This setting defines Tx_Power_Delta, the recommended difference between the peer's CS power and its power on PHY, in "
        "HCI_LE_CS_Set_Procedure_Parameters.",
        f"{PROCEDURE_PARAMETERS}: Tx_Power_Delta, signed dB (0x80: no recommendation).",
        "Changes the peer's recommended CS power. " + NO_TIMING),
    "preferred_peer_antenna": Detail(
        "This setting defines Preferred_Peer_Antenna, the bitmask of peer antennas preferred for tone exchanges, in "
        "HCI_LE_CS_Set_Procedure_Parameters.",
        f"{PROCEDURE_PARAMETERS}: Preferred_Peer_Antenna. Antenna paths: Vol 6, Part H, §4.7.",
        "Must set at least as many bits as the peer's antenna count in Antenna configuration. Read-only without Mode 2 or 3. "
        + NO_TIMING),
    "snr_control_initiator": Detail(
        "This setting defines SNR_Control_Initiator, the SNR control adjustment of the initiator's CS_SYNC transmissions, in "
        "HCI_LE_CS_Set_Procedure_Parameters.",
        f"{PROCEDURE_PARAMETERS}: SNR_Control_Initiator (0x00–0x04: 18–30 dB, 0xFF: not applied). SNR control: Vol 6, Part A, "
        f"§3.1.3. Support: TX_SNR_Capability in {CAPABILITIES}.",
        "Read-only at Not used without Mode 1 or 3. " + NO_TIMING),
    "snr_control_reflector": Detail(
        "This setting defines SNR_Control_Reflector, the SNR control adjustment of the reflector's CS_SYNC transmissions, in "
        "HCI_LE_CS_Set_Procedure_Parameters.",
        f"{PROCEDURE_PARAMETERS}: SNR_Control_Reflector (0x00–0x04: 18–30 dB, 0xFF: not applied). SNR control: Vol 6, Part A, "
        f"§3.1.3. Support: TX_SNR_Capability in {CAPABILITIES}.",
        "Read-only at Not used without Mode 1 or 3. " + NO_TIMING),
    "creation_context": Detail(
        "This setting defines Create_Context, whether the configuration is written to the local controller only or also to the "
        "peer, in HCI_LE_CS_Create_Config.",
        f"{CREATE_CONFIG}: Create_Context (0x00 local, 0x01 local and remote). {CONFIG_PROCEDURE}.",
        "Local and remote runs the CS Configuration procedure with the peer. Read-only at the default for a reflector "
        "configuration. " + NO_TIMING),
    "peer_data": Detail(
        "This setting defines whether a CS initiator receives reflector RAS subevents or relies on IPT and initiator subevents only.",
        f"The reflector-data choice is carried by the host protocol configuration; IPT is requested in {CREATE_CONFIG}.",
        "RAS real-time provides reflector amplitude and timing reports. None (initiator only) removes the RAS dependency and is "
        "available only for an initiator configuration with IPT enabled. It changes no CS timing, but RAS real-time adds the "
        "reflector's ranging data to the ACL events after each procedure: the views size it from the negotiated ATT MTU the "
        "client reports, or the 23-byte ATT default before an exchange, and draw its air time on the assumed ACL PHY. That is "
        "occupancy, not a predicted drain rate."),
    "t_pm": Detail(
        "This setting defines the phase measurement period T_PM the CS initiator prefers for each tone slot in a mode-2 or "
        "mode-3 step, in microseconds.",
        "No Core Specification host parameter: the controllers select T_PM (Vol 6, Part H, §4.3.3–4.3.4) from "
        "T_PM_Times_Supported (Vol 4, Part E, §7.8.130). The preference reaches the local controller through the "
        "SoftDevice Controller's vendor command CS Params Set, before each " + CREATE_CONFIG + "; the peer must also "
        "support the value, and " + CONFIG_COMPLETE + " reports the one in use.",
        "Longer tone slots lengthen every mode-2 and mode-3 step. 40 µs is the UI default and the mandatory Core "
        "Specification option; 20 µs is conditional and 10 µs is optional. 20 and 40 µs are sent as SET_T_PM and "
        "are part of the configuration CRC, while 10 µs leaves the controller's own preference in place. Read-only "
        "at the default for a reflector configuration or without Mode 2 or 3."),
    "peripheral_patterns": Detail(
        "This setting defines the name prefixes a central accepts while scanning for a peer. It is a firmware scan filter, not an "
        "HCI parameter.",
        "No Core Specification parameter. It matches the Complete or Shortened Local Name AD type (Core Specification Supplement, "
        "Part A, §1.2) in advertising reports.",
        "Changes which advertisers a central connects to; ignored as a peripheral. " + NO_TIMING),
}

GENERAL_CONTROL_DETAILS = {
    "operation_mode": Detail(
        "This setting defines the client operation mode: CS or CS Hostless. Radio Test is temporarily disabled. The CS initiator or reflector role is selected in CS setup.",
        "The host protocol's SET_OPERATION_MODE command and the client operation-mode values; it is an application setting, not a Bluetooth Core parameter.",
        "Selects the configuration controls, outgoing configuration packet type, run controls and results view. It is applied with the rest of the client configuration."),
    "gap_role": CONTROL_DETAILS["gap_role"],
    "peripheral_patterns": CONTROL_DETAILS["peripheral_patterns"],
    "device_name": Detail(
        "This setting defines the local Bluetooth name used when the client advertises.",
        "The host protocol's SET_DEVICE_NAME command and the Complete or Shortened Local Name AD structure (Core Specification Supplement, Part A, §1.2).",
        "Changes the name peers see during discovery and becomes part of the applied configuration. Empty leaves the firmware default in use; it is not sent in that case."),
    "log_console": Detail(
        "This setting defines the severity threshold for the client's local console consumer.",
        "The host protocol's SET_LOG_CONFIG console_level and the firmware app_log console consumer; levels are Off, Error, Warning, Info and Debug.",
        "The console receives the selected level and more severe messages. The value is staged with the configuration and takes effect at APPLY_CONFIG; it is not changed on the fly."),
    "log_host": Detail(
        "This setting defines the severity threshold for diagnostic LOG_MESSAGE frames sent to the host.",
        "The host protocol's SET_LOG_CONFIG protocol_level and the firmware app_log protocol consumer; levels are Off, Error, Warning, Info and Debug.",
        "The host receives the selected level and more severe messages. The value is staged with the configuration and takes effect at APPLY_CONFIG; it is not changed on the fly."),
}
RADIO_CONTROL_DETAILS = {
    "test_type": Detail(
        "This setting defines the radio operation to run.",
        "The radio-test configuration packet's test_type field and the firmware radio-test driver.",
        "Selects which channel, traffic, sweep and sleep controls are meaningful. Unused values remain stored but are disabled."),
    "phy": Detail(
        "This setting defines the physical layer used by the radio test.",
        "The radio-test configuration packet's phy field and the connected controller's supported PHYs.",
        "Changes the modulation and airtime used by the test. The client validates whether the selected PHY is supported."),
    "pattern": Detail(
        "This setting defines the payload pattern for modulated tests.",
        "The radio-test configuration packet's pattern field.",
        "Changes the repeated payload bits transmitted or matched by a modulated test; it is not used by an unmodulated carrier."),
    "channel": Detail(
        "This setting defines the single channel used by a fixed-channel test.",
        "The radio-test configuration packet's channel field and the selected radio band's channel numbering.",
        "Changes the frequency on which the client transmits or listens. Sweep tests use their start/end range instead."),
    "txpower": Detail(
        "This setting defines the requested transmit power in dBm.",
        "The radio-test configuration packet's txpower field and the controller's supported output-power table.",
        "Changes the requested RF output. The hardware may clamp or reject values outside its supported range."),
    "packet_count": Detail(
        "This setting defines the number of packets in a finite packet test.",
        "The radio-test configuration packet's packet_count field.",
        "Zero keeps the test running until stopped; a non-zero value ends the test after that many packets."),
    "sweep_start_channel": Detail(
        "This setting defines the first channel in an inclusive sweep.",
        "The radio-test configuration packet's sweep_start_channel field.",
        "Sets the low edge of the channel sequence. The end channel must not be below it."),
    "sweep_end_channel": Detail(
        "This setting defines the last channel in an inclusive sweep.",
        "The radio-test configuration packet's sweep_end_channel field.",
        "Sets the high edge of the channel sequence. The client visits every channel in the configured range."),
    "sweep_delay_ms": Detail(
        "This setting defines the dwell time on each sweep channel.",
        "The radio-test configuration packet's sweep_delay_ms field.",
        "Longer dwell produces more observations or transmitted traffic per channel before retuning."),
    "duty_cycle": Detail(
        "This setting defines the percentage of each duty-cycle period spent transmitting.",
        "The radio-test configuration packet's duty_cycle field.",
        "Higher values increase transmit time and reduce idle time in the explanatory timeline."),
    "tx_time_us": Detail(
        "This setting defines the transmit burst duration in a sleep sweep.",
        "The radio-test configuration packet's tx_time_us field.",
        "Sets the active portion of each TX/sleep cycle on every sweep channel."),
    "sleep_time_us": Detail(
        "This setting defines the sleep duration between transmit bursts.",
        "The radio-test configuration packet's sleep_time_us field.",
        "Sets the inactive portion of each TX/sleep cycle and therefore the repetition rate."),
    "fem_ramp_up_time_us": Detail(
        "This setting defines the front-end module ramp-up allowance.",
        "The radio-test configuration packet's fem_ramp_up_time_us field and the connected FEM driver.",
        "Gives an attached FEM time to reach the requested RF state before transmission; clients without a FEM may ignore it."),
    "fem_tx_power_control": Detail(
        "This setting defines the FEM transmit-power control value.",
        "The radio-test configuration packet's fem_tx_power_control field and the connected FEM driver.",
        "Selects the FEM power-control behavior; the default value leaves the client's FEM setting unchanged."),
}

TAB_HELP = {
    "General": (
        "Settings that select the client operation and define how it is discovered and reported.",
        "Operation mode selects CS or Hostless CS. Radio Test is temporarily disabled. The GAP role independently selects Central scanning or Peripheral advertising.",
        "Bluetooth name and scan prefixes affect discovery; prefixes are used only by a Central.",
        "Client log thresholds route firmware messages to the local console and host protocol. They are part of the applied configuration and its recorded settings.",
    ),
    "Connection": (
        "The ACL connection that Channel Sounding runs on. Every CS event starts at an offset from a connection event anchor, "
        "and CS event and procedure spacing are counted in connection intervals.",
        "Connection interval: the time between consecutive anchor points. The central picks it within Requested minimum–maximum "
        "when it creates the connection; Selected interval in the example panel is the value the views use.",
        "Peripheral latency: connection events the peripheral may skip. Anchors stay periodic, so CS timing does not move.",
        "Supervision timeout: the longest time without a valid packet before the link is lost. It must exceed "
        "2 × (latency + 1) × interval.",
        "How they bound CS timing: a CS procedure starts every Procedure spacing × interval and a CS event every CS event "
        "spacing × interval, so the selected interval sets both periods. A CS event may run past the next anchor, but it must end "
        "150 µs before the next CS event. Latency and supervision timeout govern the ACL link only.",
    ),
    "CS modes": (
        "How a CS step is built and how steps follow each other in a subevent.",
        "Modes: Mode 0 calibrates frequency and timing and starts every subevent; Mode 1 measures round-trip time with CS_SYNC "
        "packets; Mode 2 measures phase with tones; Mode 3 does both. A sub-mode step follows each run of main-mode steps.",
        "Step duration: CS_SYNC packets (CS_SYNC PHY, RTT sequence), the interludes T_IP1 or T_IP2, tone slots of T_SW + T_PM "
        "for each antenna path plus an extension slot, and a T_FCS gap before the next step. Longer steps mean fewer steps per "
        "subevent, more subevents and a longer procedure.",
        "Antenna configuration sets the number of antenna paths; IPT replaces T_SW with T_SW_IPT.",
        "Preferred T_PM is the timing a CS initiator can ask for. The UI selects the mandatory 40 µs option by default; "
        "20 µs is conditional and 10 µs is optional. 20 or 40 µs is sent as SET_T_PM and applied with CS Params Set "
        "before the configuration is created, while 10 µs leaves the controller's own preference.",
        "Controls the selected modes do not use are held at their defaults, read-only. "
        + CONTROLLER_SELECTED_NOTE + " The controller reports them at CS configuration complete.",
    ),
    "Schedule": (
        "How steps fill subevents, subevents form CS events and CS events form procedures.",
        "Subevent: steps packed into Subevent budget (at most 160 steps). CS event: Subevents / event subevents, Subevent spacing "
        "apart, starting at an offset from an ACL anchor. Procedure: CS events CS event spacing apart until the workload is "
        "placed or a limit closes it (Procedure budget, 256 steps, 32 subevents or the channel arrays). Procedures repeat every "
        "Procedure spacing, Procedure count times.",
        "Spacing rules: Subevent spacing > Subevent budget + 150 µs; CS event spacing × interval ≥ event span + 150 µs.",
        "The host sends the budgets, procedure spacing and count. The controllers select subevent length, subevents per event "
        "and the subevent and event spacing, and report them at procedure enable complete.",
    ),
    "Channels": (
        "Which RF channels CS steps use and in what order.",
        "CS channel k is centered at 2402 + k MHz; channels 0–1, 23–25 and 77–78 are never used. Mode-0 steps take channels from "
        "CSA #3a; other steps take them from arrays built by CSA #3b (a shuffle of the map) or CSA #3c (shaped ramps with salt "
        "channels).",
        "Map repetition sets how many arrays a procedure uses. When they are used up the procedure closes, even with workload left, "
        "so a smaller map or fewer repetitions can end it early.",
        "The real order depends on the CS DRBG set up during CS security start, so the views show an example from Example seed.",
    ),
    "CS setup": (
        "Identity and host settings that are used only by CS modes.",
        "Bluetooth name controls the local advertised name; GAP role selects central scanning or peripheral advertising; CS role selects the initiator or reflector configuration packet.",
        "Scan prefixes filter advertised peer names for a central and are ignored for a peripheral. Radio Test does not use this tab.",
        "The remaining settings configure CS_SYNC, transmit power, procedure PHY, antenna and creation behavior. Controls that do not apply to the selected CS role or mode remain at their defaults and read-only.",
    ),
    "Test": (
        "Select the radio test operation and its common PHY, payload, power and packet settings.",
        "Test type determines which remaining controls are active. Disabled fields retain their values for preset round trips.",
        "Modulated tests use the selected pattern; RX tests listen instead of transmitting; packet count zero means continuous operation.",
    ),
    "Channel": (
        "Select a fixed channel or the inclusive channel range used by a sweep.",
        "Fixed-channel operations use Channel. Sweep operations use Start channel, End channel and Channel dwell.",
        "The client visits sweep channels in order and reports live RX measurements in Radio RX results.",
    ),
    "Timing": (
        "Set the traffic timing for duty-cycle and sleep-based radio tests.",
        "Duty cycle controls the transmit/idle proportion. TX and sleep time control the explicit burst cycle.",
        "Controls that do not apply to the selected test are disabled but remain serialized.",
    ),
    "FEM": (
        "Configure the optional front-end module timing and transmit-power control.",
        "These values are passed to the client with the radio test configuration.",
        "The connected hardware decides whether a FEM is present and whether the requested values are supported.",
    ),
    "Host": (
        "Settings sent to the client. None changes the CS timing prediction; the reference PHY is also read as the "
        "assumed ACL PHY, which sizes the RAS real-time air time in the Connection and Procedures views.",
        "CS default settings: the CS_SYNC antenna and the maximum CS transmit power. Procedure parameters: the reference PHY and "
        "TX power delta for the peer's power, the preferred peer antennas and SNR control.",
        "Creation context: whether the initiator writes the configuration to the peer too. The GAP role (central or peripheral) "
        "is independent of the CS role (initiator or reflector); in cs-app the CS setup tab sets it and the peripheral prefixes.",
        "Unused controls are held read-only: SNR control without Mode 1 or 3, Preferred peer antenna without Mode 2 or 3, "
        "Creation context for a reflector configuration.",
    ),
}


def tab_html(title, settings):
    """Overview of a settings tab, with links to the detailed entries of settings [(key, label)]."""
    paragraphs = "".join(f"<p>{escape(text)}</p>" for text in TAB_HELP.get(title, ()))
    links = "".join(f'<li><a href="#{escape(key)}">{escape(label)}</a></li>' for key, label in settings)
    return f"<h3>{escape(title)}</h3>{paragraphs}" + (f"<p><b>Settings on this tab</b></p><ul>{links}</ul>" if links else "")


def detail_html(key, label, tooltip, read_only=False, detail=None):
    """Detailed entry of a setting, including controller-selection context when relevant."""
    detail = CONTROL_DETAILS[key] if detail is None else detail
    parts = ((detail.defines_heading, detail.defines),)
    if detail.selection:
        parts += (("How the value is selected", detail.selection),)
    parts += (("Effect of a change", detail.effect),
              ("Where the standard defines it (Core v6.3)", detail.standard))
    return (f"<h3>{escape(label)}</h3><p>{escape(tooltip)}</p>" +
            ("<p><i>Currently read-only.</i></p>" if read_only else "") +
            "".join(f"<p><b>{title}</b><br>{escape(text)}</p>" for title, text in parts))
