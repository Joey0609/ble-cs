"""Pure-Python timing model. Times are integer microseconds, never plot pixels.

This is an offline planning model, not a controller or a CS DRBG implementation.
The supplied workload and deterministic mode cadence are explicit assumptions.
Core 6.1 Vol 6 Part H 4.3 supplies the step structures. IPT (Inline PCT
Transfer, cs_enhancements_1 bit 0) keeps the formulas but substitutes the
reflector's T_SW_IPT for T_SW, and T_IP2 must come from the reflector's IPT list
(Core 6.3 Vol 6 Part H 4.3.3/4.3.4), so step durations follow T_SW_IPT.
"""

from dataclasses import asdict, dataclass, field, fields, replace
import json

from ..protocol.packets import CsConfigurationPacket, CsProcedureEnableCompletePacket

from .channels import (ALLOWED_CHANNELS, ALLOWED_MASK, CSA3C_PARAMS, ChannelSequencer,  # noqa: F401 (re-exported)
                       channel_map_bytes, enabled_channels)


MODES = {1: "Mode 1 · RTT", 2: "Mode 2 · PBR", 3: "Mode 3 · RTT + PBR",
         0x12: "Mode 2 + sub-mode 1", 0x32: "Mode 2 + sub-mode 3",
         0x23: "Mode 3 + sub-mode 2"}
ROLES = {0: "CS initiator", 1: "CS reflector"}  # configuration.role; same values as OperationMode
ENHANCEMENTS_1_IPT = 0x01  # CS_CONFIG_ENHANCEMENTS_1_IPT
ANTENNA_PATHS = (1, 2, 3, 4, 2, 3, 4, 4)


def uses_pbr(mode: int) -> bool:
    """True when the main mode or sub-mode has CS tones (Mode 2 or 3)."""
    return bool({mode & 0xF, mode >> 4} & {2, 3})


def uses_rtt(mode: int) -> bool:
    """True when the main mode or sub-mode has RTT CS_SYNC packets (Mode 1 or 3)."""
    return bool({mode & 0xF, mode >> 4} & {1, 3})


def has_sub_mode(mode: int) -> bool:
    """True when the mode combination has a sub-mode; the main-mode bounds mean nothing without one."""
    return bool(mode >> 4)


#: Exported main-mode step bounds without a sub-mode. There is no main-mode run to
#: bound, the controller reports 0 back whatever is requested, and the CS view
#: disables the controls, so the request must not carry whatever they last held.
NEUTRAL_MAIN_MODE_STEPS = 1


# Fields a mode combination does not use, as "group.field" (or Scenario field) keys.
# They are held at the Scenario() defaults: the Zephyr connected_cs_initiator sample
# values for creation fields, and the mandatory controller-selected timing values for a
# prediction before CS configuration complete reports the negotiated values.
SUB_MODE_FIELDS = ("configuration.min_main_mode_steps", "configuration.max_main_mode_steps", "main_steps")
RTT_FIELDS = ("configuration.rtt_type",)
PBR_FIELDS = ("configuration.t_ip2_time_us", "configuration.t_pm_time_us", "configuration.cs_enhancements_1",
              "procedure.tone_antenna_config_selection", "t_sw_us", "t_sw_ipt_us")
# Host settings outside the scenario: SNR control applies to Mode-1/3 CS_SYNC packets,
# preferred peer antennas and the preferred T_PM to tone exchanges. T_PM is sent as
# SET_T_PM by a CS initiator only; a reflector configuration does not use the value.
RTT_HOST_FIELDS = ("snr_control_initiator", "snr_control_reflector")
PBR_HOST_FIELDS = ("preferred_peer_antenna", "t_pm")
CSA3C_FIELDS = ("configuration.ch3c_shape", "configuration.ch3c_jump")
# Every key an active-mode rule can make read-only (inactive_fields, unused_host_fields).
CONDITIONAL_FIELDS = SUB_MODE_FIELDS + RTT_FIELDS + PBR_FIELDS + CSA3C_FIELDS + ("procedure.subevent_interval",)
CONDITIONAL_HOST_FIELDS = RTT_HOST_FIELDS + PBR_HOST_FIELDS + ("creation_context", "peer_data")
# Example values the controllers select (negotiated, declared in capabilities, or random) and
# drawing assumptions. Never sent to the client or exported to C; each tab shows its own in the
# "Example config values selected by the controller" panel.
EXAMPLE_FIELDS = ("connection.interval", "connection.activity_us", "connection.mtu", "event_offset_us", "main_steps",
                  "configuration.t_ip1_time_us", "configuration.t_ip2_time_us", "configuration.t_fcs_time_us",
                  "configuration.t_pm_time_us", "t_sw_us", "t_sw_ipt_us", "target_steps",
                  "procedure.subevents_per_event", "procedure.subevent_interval", "procedure.event_interval",
                  "preview_count", "channel_seed")


def unused_fields(mode) -> tuple[str, ...]:
    """Scenario keys the mode combination does not use; none for a non-integer mode."""
    if not isinstance(mode, int) or isinstance(mode, bool):
        return ()
    return ((() if mode >> 4 else SUB_MODE_FIELDS) + (() if uses_rtt(mode) else RTT_FIELDS) +
            (() if uses_pbr(mode) else PBR_FIELDS))


def unused_host_fields(mode, role=0) -> tuple[str, ...]:
    """Host setting names the mode combination and operation mode (configuration.role) do not use."""
    # Only the initiator configuration carries the creation context, and only a CS initiator sends SET_T_PM.
    reflector = ("creation_context", "t_pm") if role == 1 else ()
    if not isinstance(mode, int) or isinstance(mode, bool):
        return reflector
    return (() if uses_rtt(mode) else RTT_HOST_FIELDS) + (() if uses_pbr(mode) else PBR_HOST_FIELDS) + reflector


def inactive_fields(s) -> dict:
    """Scenario keys the selected modes do not use, mapped to the value each is held at.

    Adds to unused_fields: the tone switch period IPT does not use (T_SW with IPT, T_SW_IPT
    without), the CSA #3c shape and jump with CSA #3b, and a subevent spacing of 0 with one
    subevent per event, as validation requires.
    """
    c, default = s.configuration, Scenario()
    keys = list(unused_fields(c.mode))
    if isinstance(c.mode, int) and not isinstance(c.mode, bool) and uses_pbr(c.mode):
        keys.append("t_sw_us" if c.cs_enhancements_1 & ENHANCEMENTS_1_IPT else "t_sw_ipt_us")
    if c.channel_selection_type == 0:
        keys += CSA3C_FIELDS
    values = {key: scenario_value(default, key) for key in keys}
    if s.procedure.subevents_per_event == 1:
        values["procedure.subevent_interval"] = 0
    return values


def scenario_value(s, key):
    """Value of a "group.field" or Scenario field key."""
    group, _, name = key.rpartition(".")
    return getattr(getattr(s, group) if group else s, name)


def apply_mode_defaults(s):
    """Return s with the fields its selected modes do not use set to their held values (inactive_fields)."""
    groups, local = {}, {}
    for key, value in inactive_fields(s).items():
        group, _, name = key.rpartition(".")
        (groups.setdefault(group, {}) if group else local)[name] = value
    return replace(s, **{group: replace(getattr(s, group), **values) for group, values in groups.items()}, **local)


def ipt_enabled(s) -> bool:
    return bool(s.configuration.cs_enhancements_1 & ENHANCEMENTS_1_IPT)


T_RD_US = 5
# Before a CS event: the 500 µs minimum offset from the ACL anchor (Offset_Min, LL_CS_REQ)
# and the about 0.5 ms the SoftDevice Controller reserves before each subevent.
CS_EVENT_LEAD_US = 1000


def ipt_margin_us(s) -> int:
    """Reflector measure-compute-apply budget per antenna path: T_RD + T_IP2."""
    return T_RD_US + s.configuration.t_ip2_time_us
IP_TIMES = (10, 20, 30, 40, 50, 60, 80, 145)
FCS_TIMES = (15, 20, 30, 40, 50, 60, 80, 100, 120, 150)


ATT_DEFAULT_MTU = 23  # BT_ATT_DEFAULT_LE_MTU: what a link uses until an MTU exchange raises it
ATT_MAX_MTU = 517


@dataclass(frozen=True)
class Connection:
    interval_min: int = 24
    interval_max: int = 24
    interval: int = 24
    latency: int = 0
    timeout: int = 400
    activity_us: int = 1000  # illustrative ACL airtime, not derived from interval
    # Negotiated ATT MTU: reported with the ACL parameters (CONNECTION_PARAMETERS), and the
    # pre-negotiation default until one is. It sizes the RAS real-time transfer, nothing else.
    mtu: int = ATT_DEFAULT_MTU

    @property
    def interval_us(self):
        return self.interval * 1250


def default_configuration():
    return CsConfigurationPacket(
        id=0, mode=2, min_main_mode_steps=2, max_main_mode_steps=10,
        main_mode_repetition=0, mode_0_steps=2, role=0, rtt_type=0,
        cs_sync_phy=2, channel_map_repetition=1, channel_selection_type=0,
        ch3c_shape=0, ch3c_jump=2, cs_enhancements_1=0,
        t_ip1_time_us=145, t_ip2_time_us=145, t_fcs_time_us=150,
        t_pm_time_us=40,
        channel_map=channel_map_bytes(ALLOWED_CHANNELS))


def default_procedure():
    return CsProcedureEnableCompletePacket(
        config_id=0, state=1, tone_antenna_config_selection=0,
        selected_tx_power=0, subevent_len=5000, subevents_per_event=2,
        subevent_interval=12, event_interval=1, procedure_interval=4,
        procedure_count=0, max_procedure_len=160)


@dataclass(frozen=True)
class Scenario:
    connection: Connection = field(default_factory=Connection)
    configuration: CsConfigurationPacket = field(default_factory=default_configuration)
    procedure: CsProcedureEnableCompletePacket = field(default_factory=default_procedure)
    target_steps: int = 72  # fresh non-mode-0 workload, not distinct-channel guarantee
    main_steps: int = 2  # deterministic illustrative cadence within min/max
    t_sw_us: int = 2  # planner assumption; the device-specific value is negotiated from 0/1/2/4/10
    t_sw_ipt_us: int = 2  # same planner assumption, substituted for T_SW when IPT is enabled
    event_offset_us: int = 1500
    preview_count: int = 3
    provenance: str = "Hypothetical configuration and schedule"
    channel_seed: int = 1  # stands in for CS DRBG state; real hop sequences are unpredictable offline


@dataclass(frozen=True)
class Segment:
    label: str
    start: int
    duration: int
    lane: str


@dataclass(frozen=True)
class Step:
    index: int
    mode: int
    start: int  # relative to procedure start
    duration: int
    repeated: bool = False
    channel: int | None = None  # example channel index; depends on CS DRBG state


@dataclass(frozen=True)
class Subevent:
    index: int
    event: int
    slot: int
    start: int
    duration: int
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Schedule:
    subevents: tuple[Subevent, ...]
    errors: tuple[str, ...]
    notes: tuple[str, ...]
    completed_steps: int
    target_steps: int
    stop_reason: str
    channel_cycles: int = 0  # non-mode-0 channel arrays generated (#3b shuffles or #3c invocations)
    ras: "RasTransfer | None" = None  # reflector RAS real-time transfer, None without RAS or without a schedule

    @property
    def duration(self):
        return self.subevents[-1].start + self.subevents[-1].duration if self.subevents else 0

    @property
    def event_count(self):
        return self.subevents[-1].event + 1 if self.subevents else 0

    @property
    def complete(self):
        return not self.errors and self.completed_steps == self.target_steps


def step_segments(s: Scenario, mode: int) -> tuple[Segment, ...]:
    """Build chronological pieces; their sum is the full step duration.

    Extension slots consume time even when their transmission is absent.
    RX activity is inferred by the view from the opposite transmitter lane.
    With IPT, both directions switch in T_SW_IPT and the interlude is labeled
    as an IPT T_IP2 value.
    """
    c = s.configuration
    ipt = ipt_enabled(s)
    t_sw, sw_label = (s.t_sw_ipt_us, "T_SW_IPT") if ipt else (s.t_sw_us, "T_SW")
    sy = 44 if c.cs_sync_phy == 1 else 26
    if mode in (1, 3):
        sy += (0, 32, 96, 32, 64, 96, 128)[c.rtt_type] // (1 if c.cs_sync_phy == 1 else 2)
    result = []
    cursor = 0

    def add(label, duration, lane):
        nonlocal cursor
        if duration:
            result.append(Segment(label, cursor, duration, lane))
            cursor += duration

    def tones(lane):
        paths = ANTENNA_PATHS[s.procedure.tone_antenna_config_selection]
        for path in range(paths + 1):
            add(sw_label, t_sw, lane)
            add(f"P{path + 1}" if path < paths else "Extension", c.t_pm_time_us, lane)

    if mode in (0, 1, 3):
        add("CS_SYNC", sy, "Initiator")
    if mode == 3:
        add("T_GD", 10, "Initiator")
    if mode in (2, 3):
        tones("Initiator")
    add("T_RD", T_RD_US, "Initiator")
    add("T_IP1" if mode in (0, 1) else "T_IP2 (IPT)" if ipt else "T_IP2",
        c.t_ip1_time_us if mode in (0, 1) else c.t_ip2_time_us, "Timing")
    if mode in (0, 1):
        add("CS_SYNC", sy, "Reflector")
    if mode == 0:
        add("T_GD", 10, "Reflector")
        add("T_FM", 80, "Reflector")
    if mode in (2, 3):
        tones("Reflector")
    if mode == 3:
        add("T_GD", 10, "Reflector")
        add("CS_SYNC", sy, "Reflector")
    add("T_RD", T_RD_US, "Reflector")
    return tuple(result)


def minimum_subevent_len(s: Scenario) -> int:
    """Budget needed to fit the first fresh main-mode step after the Mode-0 prefix."""
    c = s.configuration
    durations = {mode: sum(segment.duration for segment in step_segments(s, mode)) for mode in range(4)}
    main_mode = c.mode & 0x0F
    return c.mode_0_steps * (durations[0] + c.t_fcs_time_us) + durations[main_mode]


def validate(s: Scenario) -> list[str]:
    c, p, a = s.configuration, s.procedure, s.connection
    errors = []
    # Dataclasses deliberately share the protocol's lightweight types. Validate
    # untrusted JSON and caller-supplied values before arithmetic or indexing.
    for group in (a, c, p):
        for item in fields(group):
            value = getattr(group, item.name)
            expected = bytes if item.name == "channel_map" else int
            if type(value) is not expected:
                errors.append(f"{item.name} must be {expected.__name__}.\nCorrect: Supply a {expected.__name__} value for {item.name} in the imported configuration.")
    for name in ("target_steps", "main_steps", "t_sw_us", "t_sw_ipt_us", "event_offset_us", "preview_count", "channel_seed"):
        if type(getattr(s, name)) is not int:
            errors.append(f"{name} must be an integer.\nCorrect: Replace {name} with a whole number, not a fraction or boolean.")
    if not isinstance(s.provenance, str):
        errors.append("Provenance must be text.\nCorrect: Set provenance to a JSON string.")
    if errors:
        return errors
    def check(ok, message, correction):
        if not ok:
            errors.append(f"{message}\nCorrect: {correction}")
    check(6 <= a.interval_min <= a.interval <= a.interval_max <= 3200,
          "Selected ACL interval must be within the requested range (6–3200 × 1.25 ms).",
          "In Connection, set Requested minimum ≤ Selected interval ≤ Requested maximum, each between 6 and 3200.")
    check(0 <= a.latency <= 499 and 10 <= a.timeout <= 3200,
          "Latency must be 0–499; timeout must be 10–3200 × 10 ms.",
          "Set Peripheral latency to 0–499 and Supervision timeout to 10–3200.")
    timeout_min = max(10, 2 * (a.latency + 1) * a.interval_us // 10000 + 1)
    check(a.timeout * 10000 > 2 * (a.latency + 1) * a.interval_us,
          "Supervision timeout must exceed 2 × (latency + 1) × connection interval.",
          (f"Set Supervision timeout to at least {timeout_min} × 10 ms ({timeout_min * 10} ms), or reduce Peripheral latency / Selected interval."
           if timeout_min <= 3200 else "Reduce Peripheral latency or Selected interval; the required timeout exceeds the 3200 × 10 ms limit."))
    check(0 <= a.activity_us < a.interval_us, "Illustrative ACL activity must be shorter than its interval.",
          f"Set ACL activity example below {a.interval_us} µs (0 hides the activity illustration).")
    check(ATT_DEFAULT_MTU <= a.mtu <= ATT_MAX_MTU, f"ATT MTU must be {ATT_DEFAULT_MTU}–{ATT_MAX_MTU} bytes.",
          f"Set ATT MTU to {ATT_DEFAULT_MTU} (the default before an exchange) or up to {ATT_MAX_MTU}.")
    check(c.mode in MODES, "Unsupported main/sub-mode combination.",
          "Choose a supported Mode combination in CS modes: 1, 2, 3, 2+1, 2+3 or 3+2.")
    check(c.cs_sync_phy in (1, 2, 3) and c.rtt_type in range(7), "Unsupported CS PHY or RTT type.",
          "Choose CS_SYNC PHY and RTT sequence from the CS modes dropdowns.")
    check(1 <= c.mode_0_steps <= 3 and 0 <= c.main_mode_repetition <= 3,
          "Mode-0 count must be 1–3 and main-mode repetition 0–3.",
          "Set Mode-0 prefix to 1–3 and Repeat previous main to 0–3 in CS modes.")
    check(1 <= c.min_main_mode_steps <= s.main_steps <= c.max_main_mode_steps <= 255,
          "Illustrative main-mode cadence must be inside the configured min/max range.",
          "Set Minimum main run ≤ Illustrative main run ≤ Maximum main run, each between 1 and 255.")
    check(c.t_ip1_time_us in IP_TIMES and c.t_ip2_time_us in IP_TIMES,
          "T_IP1/T_IP2 must use a supported timing value.",
          f"Choose T_IP1 and T_IP2 from {IP_TIMES} µs in CS modes.")
    check(c.t_fcs_time_us in FCS_TIMES and c.t_pm_time_us in (10, 20, 40),
          "Unsupported T_FCS or T_PM value.",
          "Choose T_FCS from its dropdown and T_PM of 10, 20 or 40 µs in CS modes.")
    check(s.t_sw_us in (0, 1, 2, 4, 10), "Unsupported antenna switch time.",
          "Choose T_SW of 0, 1, 2, 4 or 10 µs in CS modes.")
    check(s.t_sw_ipt_us in (0, 1, 2, 4, 10), "Unsupported IPT antenna switch time.",
          "Choose T_SW_IPT of 0, 1, 2, 4 or 10 µs in CS modes.")
    check(p.tone_antenna_config_selection in range(8), "Unsupported antenna configuration.",
          "Choose an Antenna configuration from the CS modes dropdown.")
    check(c.role in ROLES, "Operation mode must be CS initiator (0) or CS reflector (1).",
          "Choose Initiator config or Reflector config in the toolbar (configuration.role in the file).")
    check(c.cs_enhancements_1 in (0, ENHANCEMENTS_1_IPT), "Only the IPT bit (0x01) of CS enhancements 1 is defined.",
          "Set Inline PCT transfer (IPT) in CS modes; clear other cs_enhancements_1 bits in the imported data.")
    if c.cs_enhancements_1 & ENHANCEMENTS_1_IPT:
        check(uses_pbr(c.mode), "IPT needs phase measurements; Mode 1 has no CS tones.",
              "Choose a Mode combination with Mode 2 or Mode 3, or turn Inline PCT transfer (IPT) off.")
    check(c.channel_selection_type in (0, 1), "Unknown channel selection algorithm.",
          "Set Channel selection to CSA #3b or CSA #3c in Channels.")
    if c.channel_selection_type == 1:
        check(c.ch3c_shape in (0, 1) and 2 <= c.ch3c_jump <= 8, "CSA #3c needs a Hat or X shape and a jump of 2–8 channels.",
              "In Channels, choose a #3c shape and set #3c jump to 2–8.")
        if c.ch3c_jump in CSA3C_PARAMS:
            limit = CSA3C_PARAMS[c.ch3c_jump][2]
            check(c.channel_map_repetition <= limit, f"CSA #3c jump {c.ch3c_jump} allows at most {limit} map repetition(s).",
                  f"Set Map repetition to 1–{limit}, or choose a #3c jump that allows more (jumps 6–8 allow 3; Table 4.2).")
    check(0 <= s.channel_seed <= 0x7FFFFFFF, "Example channel seed must be 0–2147483647.",
          "Set Example seed in Channels to a nonnegative 31-bit integer.")
    check(len(c.channel_map) == 10, "The CS channel map must contain 10 bytes.",
          "Enter exactly 20 hexadecimal characters in Channels → Map (hex).")
    bits = int.from_bytes(c.channel_map, "little")
    check(bits & ~ALLOWED_MASK == 0 and bits.bit_count() >= 15, "Channel map must contain at least 15 allowed CS channels.",
          f"In Channels, enable at least 15 channels from 2–22 and 26–76 (currently {(bits & ALLOWED_MASK).bit_count()}); "
          "clear reserved channels 0, 1, 23–25, 77 and above.")
    check(1 <= c.channel_map_repetition <= 255, "Channel-map repetition must be 1–255.",
          "Set Map repetition to 1–255 in Channels.")
    check(c.id == p.config_id and 0 <= c.id <= 3, "Configuration IDs must match and be 0–3.",
          "Use matching configuration.id and procedure.config_id values between 0 and 3 in the imported data.")
    check(p.state == 1, "Procedure is disabled; no active schedule to preview.",
          "In cs-app, connect to a peer, apply the CS configuration, then press Start. Check Results → Controller → Procedure Enable Complete for an Enabled result.")
    check(1250 <= p.subevent_len <= 4000000, "Subevent length must be 1250–4000000 µs.",
          "Set Subevent budget between 1250 and 4000000 µs in Schedule.")
    check(1 <= p.subevents_per_event <= 32 and 1 <= p.event_interval <= 65535,
          "Need 1–32 subevents per event and a positive event interval.",
          "Set Subevents / event to 1–32 and CS event spacing to 1–65535 ACL intervals.")
    check(1 <= p.procedure_interval <= 65535 and 0 <= p.procedure_count <= 65535,
          "Invalid procedure interval or count.",
          "Set Procedure spacing to 1–65535 ACL intervals and Procedure count to 0–65535; 0 repeats until disabled.")
    check(1 <= p.max_procedure_len <= 65535, "Maximum procedure length must be positive (625 µs units).",
          "Set Procedure budget to 1–65535 × 625 µs in Schedule.")
    check(0 <= s.event_offset_us and 1 <= s.target_steps <= 256 and 1 <= s.preview_count <= 10,
          "Offset must be nonnegative; workload 1–256; preview count 1–10.",
          "Set CS offset from anchor ≥ 0, Fresh-step workload to 1–256 and Preview instances to 1–10.")
    if p.subevents_per_event == 1:
        check(p.subevent_interval == 0, "Subevent interval must be zero when there is one subevent per event.",
              "Set Subevent spacing to 0, or increase Subevents / event above 1.")
    else:
        check(1 <= p.subevent_interval <= 65535 and p.subevent_interval * 625 > p.subevent_len + 150,
              "Subevent spacing must exceed subevent length + 150 µs.",
              f"Set Subevent spacing to at least {(p.subevent_len + 150) // 625 + 1} × 625 µs, or reduce Subevent budget. Recheck CS event spacing afterwards.")
    event_span = (p.subevents_per_event - 1) * p.subevent_interval * 625 + p.subevent_len
    check(p.event_interval * a.interval_us >= event_span + 150,
          "CS event spacing must leave at least 150 µs after the final reserved subevent.",
          f"Set CS event spacing to at least {(event_span + 150 + max(1, a.interval_us) - 1) // max(1, a.interval_us)} ACL intervals, or reduce Subevents / event, Subevent spacing or Subevent budget.")
    # The controller caps the reservation at the procedure budget. A CS event with less than
    # CS_EVENT_LEAD_US of its ACL interval left was refused with HCI 0x20 at procedure enable.
    reserved = min(event_span, p.max_procedure_len * 625)
    check(reserved + CS_EVENT_LEAD_US <= a.interval_us,
          f"A CS event must be at least {CS_EVENT_LEAD_US} µs shorter than the ACL interval; "
          "the controller rejects the procedure start otherwise.",
          f"Reduce Subevent budget so the CS event takes at most {a.interval_us - CS_EVENT_LEAD_US} µs, "
          f"or set the ACL interval to at least {-(-(reserved + CS_EVENT_LEAD_US) // 1250)} × 1.25 ms.")
    return errors


# --- RAS real-time transfer (Ranging Service 1.0, ranging data format) -------
# With peer_data 0 the reflector's RAS responder notifies one procedure's ranging
# data on the ACL events that follow it. The sizes below are the ranging-data
# format; the step data is the reflector's, because the responder sends what the
# reflector measured. The MTU is what a client reported (CONNECTION_PARAMETERS,
# §12.4) or, before an exchange, the ATT default every link starts at.
ATT_NOTIFY_HEADER = 3  # notification opcode and handle
RAS_SEGMENT_HEADER = 1  # RAS segmentation header: rd_segment_send() segments at mtu - 4
RAS_RANGING_HEADER = 4  # ranging counter and configuration id, selected TX power, antenna-paths mask
RAS_SUBEVENT_HEADER = 8  # start ACL event, frequency compensation, done/abort status, reference power, step count
RAS_STEP_HEADER = 1  # step mode with its aborted flag
L2CAP_HEADER = 4
LL_DATA_LENGTH_MAX = 251  # CONFIG_BT_CTLR_DATA_LENGTH_MAX in every image here
T_IFS_US = 150
PHY_NAMES = {1: "LE 1M", 2: "LE 2M", 3: "LE Coded S8", 4: "LE Coded S2"}


def ras_step_bytes(s: Scenario, mode: int) -> int:
    """Reflector step data of one RAS step, without its step header."""
    c = s.configuration
    if mode == 0:
        # Packet quality, RSSI and antenna. An initiator step would add its 2-byte frequency offset.
        return 3
    paths = ANTENNA_PATHS[s.procedure.tone_antenna_config_selection]
    # Quality, NADM, RSSI, ToA/ToD and antenna; a sounding sequence adds PCT1 and PCT2.
    rtt = 6 + (8 if c.rtt_type in (1, 2) else 0)
    # Antenna permutation index, then a PCT and a quality indicator per path and for the extension slot.
    tones = 1 + (paths + 1) * 4
    return (rtt if uses_rtt(mode) else 0) + (tones if uses_pbr(mode) else 0)


def ll_packet_us(payload: int, phy: int = 1) -> int:
    """Air time of one LL data PDU carrying payload octets (phy: 1 LE 1M, 2 LE 2M, 3 Coded S8, 4 Coded S2)."""
    octets = 2 + payload + 3  # LL header, payload, CRC
    if phy == 2:
        return (2 + 4 + octets) * 4
    if phy in (3, 4):
        coding = 8 if phy == 3 else 2
        # Preamble, access address, coding indicator and TERM1 are always S=8; FEC block 2 ends with TERM2.
        return 80 + 256 + 16 + 24 + (octets * 8 + 3) * coding
    return (1 + 4 + octets) * 8


@dataclass(frozen=True)
class RasTransfer:
    """One procedure's ranging data on the ACL: counts and air time, not a predicted drain.

    ``spans`` places the air time in successive ACL events after the procedure,
    filling each up to one connection interval. That is a floor on how long the
    transfer occupies the link, not a schedule: how many PDUs actually leave per
    ACL event depends on the reflector's event length, its TX buffers and how
    fast its host refills them, none of which a link reports (§13.2).
    """
    mtu: int
    phy: int
    data_bytes: int
    notifications: int
    pdus: int
    airtime_us: int
    spans: tuple[int, ...]

    @property
    def events(self) -> int:
        """Lower bound on the ACL events the transfer occupies."""
        return len(self.spans)

    @property
    def phy_name(self) -> str:
        return PHY_NAMES.get(self.phy, f"PHY {self.phy}")

    @property
    def default_mtu(self) -> bool:
        """True while the link is on the MTU it starts at, which no exchange has raised."""
        return self.mtu == ATT_DEFAULT_MTU


def ras_transfer(s: Scenario, subevents, phy: int = 1) -> RasTransfer:
    """Size one procedure's RAS real-time transfer at the connection's ATT MTU."""
    mtu = s.connection.mtu
    data = (RAS_RANGING_HEADER + len(subevents) * RAS_SUBEVENT_HEADER +
            sum(RAS_STEP_HEADER + ras_step_bytes(s, step.mode) for se in subevents for step in se.steps))
    segment = mtu - ATT_NOTIFY_HEADER - RAS_SEGMENT_HEADER
    notifications = -(-data // segment) if data else 0
    exchanges, remaining = [], data
    for _ in range(notifications):
        carried = min(segment, remaining)
        remaining -= carried
        frame = L2CAP_HEADER + ATT_NOTIFY_HEADER + RAS_SEGMENT_HEADER + carried
        while frame > 0:
            payload = min(LL_DATA_LENGTH_MAX, frame)
            frame -= payload
            # The central polls: an empty PDU and two T_IFS gaps surround each fragment the reflector sends.
            exchanges.append(ll_packet_us(0, phy) + T_IFS_US + ll_packet_us(payload, phy) + T_IFS_US)
    spans = []
    for exchange in exchanges:
        if not spans or spans[-1] + exchange > s.connection.interval_us:
            spans.append(exchange)
        else:
            spans[-1] += exchange
    return RasTransfer(mtu, phy, data, notifications, len(exchanges), sum(exchanges), tuple(spans))


def build_schedule(s: Scenario, peer_data: int = 0, phy: int = 1) -> Schedule:
    """Predict one procedure's schedule, and with RAS real-time its ranging-data transfer.

    peer_data 0 is RAS real-time, 1 initiator-only data. The transfer is sized at
    the connection's ATT MTU, which a client report sets and which is the
    pre-negotiation default until then, and its air time is measured on phy, the
    host reference PHY read as the assumed ACL PHY.
    """
    errors = validate(s)
    notes = ["Predicted timing; mode cadence is deterministic, not the controller's randomized sequence.",
             "Channels are an example: CSA #3a/#3b/#3c structure follows the specification, but the actual hop sequence depends on the CS DRBG state and differs per procedure.",
             "ACL activity width and event offset are assumptions; peripheral latency does not move ACL anchors."]
    if ipt_enabled(s):
        notes.append(f"IPT requested: tone switch periods use T_SW_IPT = {s.t_sw_ipt_us} µs instead of T_SW = {s.t_sw_us} µs, "
                     f"and T_IP2 = {s.configuration.t_ip2_time_us} µs must be in the reflector's IPT T_IP2 list. "
                     f"Reflector real-time margin T_RD + T_IP2 = {ipt_margin_us(s)} µs. The reflector must declare IPT "
                     "support in its capabilities (cs_ipt_reflector_supported).")
    if peer_data == 1:
        if s.configuration.role != 0:
            errors.append("Initiator-only reflector data is valid only for a CS initiator configuration.\nCorrect: Choose CS initiator or select RAS real-time.")
        elif not ipt_enabled(s):
            errors.append("Initiator-only reflector data requires Inline PCT transfer (IPT).\nCorrect: Request IPT or select RAS real-time.")
        else:
            notes.append("Reflector data: initiator only. PBR uses the initiator PCT; reflector amplitude and RTT timing are unavailable.")
            if 3 in (s.configuration.mode & 0xF, s.configuration.mode >> 4):
                notes.append("Mode 3 with initiator-only data: RTT has no reflector timing, and there is no independent "
                             "check of the IPT phase (no reflector PCT to compare against).")
            notes.append("Initiator-only data: no RAS notifications between procedures, so the procedure interval "
                         "can be 1 ACL event.")
    elif peer_data == 0 and ipt_enabled(s):
        notes.append("Reflector data: RAS real-time. Reflector subevents remain available for amplitude weighting and RTT timing.")
    elif peer_data not in (0, 1):
        errors.append("Unknown reflector data setting.\nCorrect: Select RAS real-time or None (initiator only).")
    if (peer_data == 0 and s.configuration.role == 0 and s.procedure.procedure_interval == 1
            and s.procedure.procedure_count != 1):
        notes.append("RAS real-time with a minimum procedure interval of 1 ACL event: the reflector's RAS data "
                     "needs ACL events between procedures, or it arrives late and aborts the next procedure "
                     "(see cs_hostless_initiator/README.md).")
    if errors:
        return Schedule((), tuple(errors), tuple(notes), 0, s.target_steps, "Invalid configuration")
    c, p = s.configuration, s.procedure
    durations = {m: sum(x.duration for x in step_segments(s, m)) for m in range(4)}
    main, sub = c.mode & 0xF, c.mode >> 4
    sequence = [sub if sub and i % (s.main_steps + 1) == s.main_steps else main
                for i in range(s.target_steps)]
    channels = ChannelSequencer(c, s.channel_seed)
    # §4.2: a mode-1 Sub_Mode step reuses the preceding Main_Mode step's channel.
    reuses_channel = [mode == sub == 1 for mode in sequence]
    completed = total = 0
    subevents = []
    prior_main = []  # (mode, channel) of fresh main steps in the previous subevent
    last_main_channel = None
    reason = "Workload completed"
    exhausted_reason = ("Non-mode-0 channel map cycles exhausted\nCorrect: " +
                        (f"Increase Map repetition in Channels (at most {CSA3C_PARAMS[c.ch3c_jump][2]} for #3c jump {c.ch3c_jump}; "
                         "#3c salt counts vary with the DRBG), enable more channels, or reduce Fresh-step workload."
                         if c.channel_selection_type == 1 else
                         f"Increase Map repetition to at least {-(-sum(1 for r in reuses_channel if not r) // len(channels.enabled))} "
                         f"in Channels, enable more channels, or reduce Fresh-step workload "
                         f"(each cycle provides {len(channels.enabled)} non-mode-0 channels)."))

    def fresh_channel(i):
        return last_main_channel if reuses_channel[i] else channels.peek_non_mode0()

    for index in range(32):
        event, slot = divmod(index, p.subevents_per_event)
        start = event * p.event_interval * s.connection.interval_us + slot * p.subevent_interval * 625
        capacity = min(p.subevent_len, p.max_procedure_len * 625 - start)
        steps = []
        used = 0

        def append(mode, repeated=False, channel=None):
            nonlocal used, total
            offset = used + (c.t_fcs_time_us if steps else 0)
            if offset + durations[mode] > capacity or len(steps) >= 160 or total >= 256:
                return False
            steps.append(Step(total, mode, start + offset, durations[mode], repeated, channel))
            used = offset + durations[mode]
            total += 1
            return True

        if fresh_channel(completed) is None:
            reason = exhausted_reason
            break
        repeats = prior_main[-c.main_mode_repetition:] if c.main_mode_repetition else []
        prefix = [0] * c.mode_0_steps + [mode for mode, _ in repeats]
        # Do not leave an invalid Mode-0-only subevent in the plan.
        minimum = sum(durations[m] for m in prefix) + durations[sequence[completed]] + len(prefix) * c.t_fcs_time_us
        if minimum > capacity or total + len(prefix) + 1 > 256:
            if minimum > p.subevent_len:
                reason = ("No fresh step fits after Mode-0/repetition overhead\nCorrect: "
                          f"Increase Subevent budget to at least {minimum} µs for the next required step, "
                          "or reduce Mode-0 prefix / Repeat previous main / step duration. Recheck spacing after changing the budget.")
            elif total + len(prefix) + 1 > 256:
                reason = ("256-step procedure limit reached\nCorrect: Reduce Fresh-step workload "
                          f"(this preview completed {completed}), or reduce calibration/repetition overhead. "
                          "Increasing Procedure budget alone cannot raise the 256-step limit.")
            else:
                units = (start + minimum + 624) // 625
                reason = ("Maximum procedure duration reached\nCorrect: "
                          f"Increase Procedure budget to at least {units} × 625 µs to fit the next required step, "
                          "or reduce Fresh-step workload / scheduled gaps. Recheck Procedure spacing afterwards.")
            break
        for _ in range(c.mode_0_steps):
            append(0, channel=channels.mode0_channel())
        for mode, channel in repeats:
            append(mode, True, channel)
        before = completed
        exhausted = False
        while completed < len(sequence):
            channel = fresh_channel(completed)
            if channel is None:
                exhausted = True
                break
            if not append(sequence[completed], channel=channel):
                break
            if not reuses_channel[completed]:
                channels.take_non_mode0()
            if sequence[completed] == main:
                last_main_channel = channel
            completed += 1
        subevents.append(Subevent(index, event, slot, start, used, tuple(steps)))
        # §4.4.4: only steps not themselves repeated are candidates for repetition.
        prior_main = [(step.mode, step.channel) for step in steps if step.mode == main and not step.repeated]
        if completed == len(sequence):
            break
        if exhausted:
            reason = exhausted_reason
            break
        if completed == before:
            reason = "No forward progress\nCorrect: Increase Subevent budget or reduce Mode-0 prefix / Repeat previous main."
            break
    else:
        reason = ("32-subevent limit reached\nCorrect: Increase Subevent budget so more steps fit in each subevent, "
                  "or reduce Fresh-step workload / repetition overhead. Recheck spacing and Procedure budget afterwards.")
    if subevents:
        end = subevents[-1].start + subevents[-1].duration
        if p.procedure_count != 1 and end + 150 > p.procedure_interval * s.connection.interval_us:
            units = (end + 150 + s.connection.interval_us - 1) // s.connection.interval_us
            errors.append("Procedure repetition interval leaves insufficient space before the next procedure.\nCorrect: "
                          f"Set Procedure spacing to at least {units} ACL intervals, reduce the workload duration, or set Procedure count to 1 for a single instance.")
        # Check illustrative ACL coexistence, including events crossed by long subevents.
        collision = False
        for se in subevents:
            begin = s.event_offset_us + se.start
            finish = begin + se.duration
            anchor = (begin // s.connection.interval_us) * s.connection.interval_us
            while anchor < finish:
                collision |= s.connection.activity_us > 0 and a_overlap(begin, finish, anchor, anchor + s.connection.activity_us)
                anchor += s.connection.interval_us
        if collision:
            notes.append("CS overlaps the illustrative ACL activity; a real controller must resolve coexistence.\nCorrect: "
                         "Adjust CS offset from anchor or CS scheduling gaps to avoid the illustrated activity windows. "
                         "Only reduce ACL activity example if that matches your expected traffic; this check is illustrative.")
    transfer = ras_transfer(s, subevents, phy) if peer_data == 0 and subevents else None
    if transfer:
        default_mtu = " (the ATT default, before an MTU exchange)" if transfer.default_mtu else ""
        notes.append(f"RAS real-time transfer: {transfer.data_bytes} bytes of ranging data per procedure, "
                     f"{transfer.notifications} notification(s) at ATT MTU {transfer.mtu}{default_mtu}, "
                     f"{transfer.pdus} LL PDU(s), {transfer.airtime_us / 1000:g} ms of {transfer.phy_name} air time "
                     f"in at least {transfer.events} ACL event(s). Occupancy, not a predicted drain: how many PDUs "
                     "leave per ACL event depends on the reflector's event length, TX buffers and host, which the link "
                     "does not report.")
        # The notifications start at the first anchor after the procedure, so that anchor to the
        # next procedure is the whole window. Air time alone exceeding it is a floor, not a drain rate.
        interval = s.connection.interval_us
        first = -(-(subevents[-1].start + subevents[-1].duration) // interval)
        window = p.procedure_interval * interval - first * interval
        if p.procedure_count != 1 and transfer.airtime_us > window:
            units = first + -(-transfer.airtime_us // interval)
            # Only the unexchanged default is worth raising; a negotiated MTU is what the link settled on.
            mtu_advice = (f", or raise the client's ATT MTU above {transfer.mtu} (CONFIG_BT_GATT_AUTO_UPDATE_MTU) so "
                          "each notification carries more" if transfer.default_mtu else "")
            notes.append(f"RAS real-time needs {transfer.airtime_us / 1000:g} ms of air time from ACL event {first}, "
                         f"more than the {max(0, window) / 1000:g} ms before the next procedure starts, so the "
                         "reflector's data arrives late and can abort that procedure.\nCorrect: Set Procedure spacing "
                         f"to at least {units} ACL intervals, reduce the workload or antenna paths{mtu_advice}.")
    return Schedule(tuple(subevents), tuple(errors), tuple(notes), completed, s.target_steps, reason, channels.cycles,
                    transfer)


def a_overlap(a, b, c, d):
    return a < d and c < b


def dumps(s: Scenario) -> str:
    data = asdict(s)
    data["configuration"]["channel_map"] = s.configuration.channel_map.hex()
    return json.dumps({"schema_version": 1, **data}, indent=2) + "\n"


def loads(raw: str) -> Scenario:
    """Load planner files; imported invalid timings are rejected without GUI clamping."""
    data = json.loads(raw)
    data.pop("host_settings", None)  # UI/export metadata; timing-only callers can ignore it.
    if data.pop("schema_version", None) != 1:
        raise ValueError("Unsupported planner file version")
    data["configuration"]["channel_map"] = bytes.fromhex(data["configuration"]["channel_map"])
    s = Scenario(connection=Connection(**data.pop("connection")),
                 configuration=CsConfigurationPacket(**data.pop("configuration")),
                 procedure=CsProcedureEnableCompletePacket(**data.pop("procedure")), **data)
    errors = validate(s)
    if errors:
        raise ValueError("\n".join(errors))
    # Check protocol field encodings too, without changing the transport classes.
    s.configuration.to_bytes()
    s.procedure.to_bytes()
    return s
