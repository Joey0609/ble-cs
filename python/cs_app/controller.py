"""Decode controller reports and check them against the host configuration.

Three client -> host reports describe what the controllers actually agreed on:

* ``CsCapabilitiesPacket``: what the local and the remote controller support.
* ``CsConfigurationPacket``: the CS configuration as completed by the controller,
  including the T_IP1/T_IP2/T_FCS/T_PM timings it selected.
* ``CsProcedureEnableCompletePacket``: the procedure parameters it selected.
* ``ConnectionParametersPacket``: the ACL parameters the link ended up with.

``ControllerReports`` keeps the latest of each. ``compare_configuration``,
``compare_procedure`` and ``compare_connection`` line the negotiated values up
with the requested host configuration; ``check_compatibility`` lists settings a
controller does not support. Standard library only;
``cs_app.views.controller_view`` displays it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .planner.model import ANTENNA_PATHS, ENHANCEMENTS_1_IPT, MODES, ROLES
from .protocol.packets import (CAPABILITIES_CONN_NONE, CapabilitiesSource, ConnectionParametersPacket,
                               CsCapabilitiesPacket, CsConfigurationPacket, CsInitiatorConfigPacket,
                               CsProcedureEnableCompletePacket, CsReflectorConfigPacket, T_PM_DEFAULT_US)

# Optional durations by capability bit (Core Vol 4 Part E 7.8.130); the last value is mandatory.
T_IP_TIMES_US = (10, 20, 30, 40, 50, 60, 80)
T_IP_MANDATORY_US = 145
T_FCS_TIMES_US = (15, 20, 30, 40, 50, 60, 80, 100, 120)
T_FCS_MANDATORY_US = 150
T_PM_TIMES_US = (10, 20)
T_PM_MANDATORY_US = 40
SNR_LEVELS_DB = (18, 21, 24, 27, 30)
RTT_PRECISION = {0: "not supported", 1: "10 ns", 2: "150 ns"}
RTT_TYPES = ("AA only", "32-bit sounding", "96-bit sounding", "32-bit random", "64-bit random", "96-bit random",
             "128-bit random")
SYNC_PHYS = {1: "LE 1M", 2: "LE 2M", 3: "LE 2M 2BT"}
CHANNEL_SELECTION = {0: "CSA #3b", 1: "CSA #3c"}
CH3C_SHAPES = {0: "Hat", 1: "X"}
TONE_ANTENNAS = ("A1:B1", "A2:B1", "A3:B1", "A4:B1", "A1:B2", "A1:B3", "A1:B4", "A2:B2")
# (initiator antennas, reflector antennas) per tone_antenna_config_selection.
TONE_ANTENNA_COUNTS = ((1, 1), (2, 1), (3, 1), (4, 1), (1, 2), (1, 3), (1, 4), (2, 2))
SNR_CONTROL_NONE = 0xFF
TX_POWER_NA = 0x7F

OK = "ok"
DIFFERS = "differs"
OUTSIDE = "outside"
INFO = ""

HOST_PACKETS = (CsInitiatorConfigPacket, CsReflectorConfigPacket)
# Prefix of check_compatibility() entries that end the run instead of only degrading it.
RUN_FAILS = "Run fails: "


def bit_values(mask: int, values: tuple[int, ...]) -> list[int]:
    return [value for bit, value in enumerate(values) if mask & (1 << bit)]


def _label(table, value) -> str:
    if isinstance(table, dict):
        return table.get(value, f"invalid ({value})")
    return table[value] if 0 <= value < len(table) else f"invalid ({value})"


def _times(mask: int, values: tuple[int, ...], mandatory: int | None) -> str:
    listed = bit_values(mask, values) + ([mandatory] if mandatory is not None else [])
    return ", ".join(str(value) for value in listed) + " µs" if listed else "none"


def channel_count(channel_map: bytes) -> int:
    return sum(bin(byte).count("1") for byte in channel_map)


def _uses(mode: int, main_modes: set[int]) -> bool:
    return bool({mode & 0xF, mode >> 4} & main_modes)


@dataclass(frozen=True)
class CapabilityRow:
    """One capability: display text and whether it is supported (None when not a yes/no)."""

    label: str
    text: str
    supported: bool | None = None


def capability_rows(caps: CsCapabilitiesPacket) -> list[CapabilityRow]:
    """Human-readable capabilities in display order."""
    def flag(label, value):
        return CapabilityRow(label, "yes" if value else "no", bool(value))

    def rtt(label, precision, steps):
        text = _label(RTT_PRECISION, precision) + (f", N = {steps}" if steps else ", N = 0")
        return CapabilityRow(label, text, bool(steps))

    consecutive = caps.max_consecutive_procedures_supported
    return [
        CapabilityRow("Configurations", str(caps.num_config_supported)),
        CapabilityRow("Consecutive procedures", "fixed and indefinite" if consecutive == 0 else f"up to {consecutive}"),
        CapabilityRow("Antennas", str(caps.num_antennas_supported)),
        CapabilityRow("Antenna paths", str(caps.max_antenna_paths_supported)),
        flag("Initiator role", caps.initiator_supported),
        flag("Reflector role", caps.reflector_supported),
        flag("Mode 3", caps.mode_3_supported),
        rtt("RTT AA only", caps.rtt_aa_only_precision, caps.rtt_aa_only_n),
        rtt("RTT sounding", caps.rtt_sounding_precision, caps.rtt_sounding_n),
        rtt("RTT random payload", caps.rtt_random_payload_precision, caps.rtt_random_payload_n),
        flag("NADM sounding", caps.phase_based_nadm_sounding_supported),
        flag("NADM random", caps.phase_based_nadm_random_supported),
        flag("CS_SYNC LE 2M", caps.cs_sync_2m_phy_supported),
        flag("CS_SYNC LE 2M 2BT", caps.cs_sync_2m_2bt_phy_supported),
        flag("CS without FAE", caps.cs_without_fae_supported),
        flag("CSA #3c", caps.chsel_alg_3c_supported),
        flag("PBR from RTT sounding", caps.pbr_from_rtt_sounding_seq_supported),
        CapabilityRow("T_IP1", _times(caps.t_ip1_times_supported, T_IP_TIMES_US, T_IP_MANDATORY_US)),
        CapabilityRow("T_IP2", _times(caps.t_ip2_times_supported, T_IP_TIMES_US, T_IP_MANDATORY_US)),
        CapabilityRow("T_FCS", _times(caps.t_fcs_times_supported, T_FCS_TIMES_US, T_FCS_MANDATORY_US)),
        CapabilityRow("T_PM", _times(caps.t_pm_times_supported, T_PM_TIMES_US, T_PM_MANDATORY_US)),
        CapabilityRow("T_SW", f"{caps.t_sw_time} µs"),
        CapabilityRow("TX SNR levels", ", ".join(f"{db} dB" for db in bit_values(caps.tx_snr_capability, SNR_LEVELS_DB))
                      or "none"),
        flag("IPT reflector", caps.cs_ipt_reflector_supported),
        CapabilityRow("IPT T_IP2", _times(caps.t_ip2_ipt_times_supported, T_IP_TIMES_US, None)),
        CapabilityRow("IPT T_SW", f"{caps.t_sw_ipt_time_supported} µs"),
    ]


@dataclass(frozen=True)
class Row:
    """One requested/negotiated comparison line."""

    field: str
    requested: str
    negotiated: str
    status: str = INFO


def _compare(name, requested, negotiated, fmt=str) -> Row:
    if requested is None:
        return Row(name, "—", fmt(negotiated))
    return Row(name, fmt(requested), fmt(negotiated), OK if requested == negotiated else DIFFERS)


def _within(name, low, high, negotiated, fmt=str) -> Row:
    if low is None:
        return Row(name, "—", fmt(negotiated))
    requested = fmt(low) if low == high else f"{fmt(low)} … {fmt(high)}"
    return Row(name, requested, fmt(negotiated), OK if low <= negotiated <= high else OUTSIDE)


def _ms(units_0625: int) -> str:
    return f"{units_0625 * 0.625:g} ms"


def _interval_ms(units_125: int) -> str:
    return f"{units_125 * 1.25:g} ms"


def _timeout_ms(units_10: int) -> str:
    return f"{units_10 * 10:g} ms"


def compare_connection(requested: Any, negotiated: ConnectionParametersPacket) -> list[Row]:
    """Rows for the ACL parameters of the current link; requested is a host config packet or None.

    Only a GAP central asks for connection parameters, so for a peripheral the
    request is inert (§3.1) and the reported values stand alone.
    """
    central = isinstance(requested, HOST_PACKETS) and requested.gap_role == 0
    r = requested if central else None
    rows = [
        _within("Connection interval", r and r.connection_interval_min, r and r.connection_interval_max,
                negotiated.interval, _interval_ms),
        _compare("Peripheral latency", r and r.connection_latency, negotiated.latency, lambda v: f"{v} events"),
        _compare("Supervision timeout", r and r.connection_timeout, negotiated.timeout, _timeout_ms),
        Row("ATT MTU", "not requested", f"{negotiated.mtu} bytes", INFO),
    ]
    if isinstance(requested, HOST_PACKETS) and not central:
        return [Row(row.field, "not requested", row.negotiated) for row in rows]
    return rows


def compare_configuration(requested: Any, negotiated: CsConfigurationPacket, peer_data: int | None = None,
                          t_pm: int = T_PM_DEFAULT_US) -> list[Row]:
    """Rows for a completed CS configuration; requested is a host config packet or None.

    Only the initiator's host packet carries the creation parameters, so for a
    reflector (or no request) they show the negotiated value alone.
    """
    creation = requested if isinstance(requested, CsInitiatorConfigPacket) else None

    def created(name):
        return getattr(creation, "creation_" + name) if creation else None

    host_role = None if requested is None else (0 if isinstance(requested, CsInitiatorConfigPacket) else 1)
    requested_map = created("channel_map")
    rows = [
        _compare("Configuration ID", getattr(requested, "config_id", None), negotiated.id),
        _compare("Local role", host_role, negotiated.role, lambda v: _label(ROLES, v)),
        _compare("Mode", created("mode"), negotiated.mode, lambda v: _label(MODES, v)),
        _compare("Min main-mode steps", created("min_main_mode_steps"), negotiated.min_main_mode_steps),
        _compare("Max main-mode steps", created("max_main_mode_steps"), negotiated.max_main_mode_steps),
        _compare("Main-mode repetition", created("main_mode_repetition"), negotiated.main_mode_repetition),
        _compare("Mode-0 steps", created("mode_0_steps"), negotiated.mode_0_steps),
        _compare("RTT type", created("rtt_type"), negotiated.rtt_type, lambda v: _label(RTT_TYPES, v)),
        _compare("CS_SYNC PHY", created("cs_sync_phy"), negotiated.cs_sync_phy, lambda v: _label(SYNC_PHYS, v)),
        _compare("Channel map repetition", created("channel_map_repetition"), negotiated.channel_map_repetition),
        _compare("Channel selection", created("channel_selection_type"), negotiated.channel_selection_type,
                 lambda v: _label(CHANNEL_SELECTION, v)),
        _compare("#3c shape", created("ch3c_shape"), negotiated.ch3c_shape, lambda v: _label(CH3C_SHAPES, v)),
        _compare("#3c jump", created("ch3c_jump"), negotiated.ch3c_jump),
        _compare("IPT (enhancements 1)", created("cs_enhancements_1"), negotiated.cs_enhancements_1,
                 lambda v: "on" if v & ENHANCEMENTS_1_IPT else "off"),
        Row("Channels", "—" if requested_map is None else f"{channel_count(requested_map)} enabled",
            f"{channel_count(negotiated.channel_map)} enabled",
            INFO if requested_map is None else OK if requested_map == negotiated.channel_map else DIFFERS),
    ]
    if isinstance(requested, CsInitiatorConfigPacket):
        label = {0: "RAS real-time", 1: "None (initiator only)"}.get(peer_data, "unknown")
        rows.append(Row("Reflector data", label, "initiator-only" if peer_data == 1 else "RAS reports",
                        OK if peer_data in (0, 1) else DIFFERS))
    # Timings are chosen by the controllers; the host packet has no field for them.
    rows += [Row(name, "controller", f"{value} µs") for name, value in
             (("T_IP1", negotiated.t_ip1_time_us), ("T_IP2", negotiated.t_ip2_time_us),
              ("T_FCS", negotiated.t_fcs_time_us))]
    # T_PM alone can be asked for, with SET_T_PM; 10 µs leaves the controller its own preference.
    if isinstance(requested, CsInitiatorConfigPacket) and t_pm != T_PM_DEFAULT_US:
        rows.append(_compare("T_PM", t_pm, negotiated.t_pm_time_us, lambda v: f"{v} µs"))
    else:
        rows.append(Row("T_PM", "controller", f"{negotiated.t_pm_time_us} µs"))
    return rows


def compare_procedure(requested: Any, negotiated: CsProcedureEnableCompletePacket,
                      connection: ConnectionParametersPacket | None = None) -> list[Row]:
    """Rows for procedure enable complete; requested is a host config packet or None.

    The event and procedure intervals are counted in ACL events. They are also
    shown in milliseconds once the actual ACL interval has been reported.
    """
    r = requested if isinstance(requested, HOST_PACKETS) else None
    interval_ms = None
    if connection is not None:
        interval_ms = connection.interval * 1.25

    def events(value):
        return f"{value} ACL events" + (f" ({value * interval_ms:g} ms)" if interval_ms else "")

    tx_power = ("n/a" if negotiated.selected_tx_power == TX_POWER_NA else f"{negotiated.selected_tx_power} dBm")
    count = "until disabled" if negotiated.procedure_count == 0 else str(negotiated.procedure_count)
    requested_count = None if r is None else ("no limit" if r.max_procedure_count == 0 else f"≤ {r.max_procedure_count}")
    count_ok = r is None or r.max_procedure_count == 0 or 0 < negotiated.procedure_count <= r.max_procedure_count
    rows = [
        _compare("Configuration ID", r and r.config_id, negotiated.config_id),
        Row("State", "—", "enabled" if negotiated.state else "disabled"),
        _compare("Antenna configuration", r and r.tone_antenna_config_selection,
                 negotiated.tone_antenna_config_selection, lambda v: _label(TONE_ANTENNAS, v)),
        Row("Selected TX power", "—" if r is None else f"≤ {r.max_tx_power} dBm", tx_power,
            INFO if r is None or negotiated.selected_tx_power == TX_POWER_NA
            else OK if negotiated.selected_tx_power <= r.max_tx_power else OUTSIDE),
        _within("Subevent length", r and r.min_subevent_len, r and r.max_subevent_len, negotiated.subevent_len,
                lambda v: f"{v / 1000:g} ms"),
        Row("Subevents per event", "—", str(negotiated.subevents_per_event)),
        Row("Subevent interval", "—", _ms(negotiated.subevent_interval)),
        Row("Event interval", "—", events(negotiated.event_interval)),
        _within("Procedure interval", r and r.min_procedure_interval, r and r.max_procedure_interval,
                negotiated.procedure_interval, events),
        Row("Procedure count", requested_count or "—", count, INFO if r is None else OK if count_ok else OUTSIDE),
        Row("Max procedure length", "—" if r is None else f"≤ {_ms(r.max_procedure_len)}",
            _ms(negotiated.max_procedure_len),
            INFO if r is None else OK if negotiated.max_procedure_len <= r.max_procedure_len else OUTSIDE),
    ]
    return rows


def check_compatibility(capabilities: dict[int, CsCapabilitiesPacket], *, requested: Any = None,
                        configuration: CsConfigurationPacket | None = None,
                        procedure: CsProcedureEnableCompletePacket | None = None,
                        peer_data: int = 0, t_pm: int = T_PM_DEFAULT_US) -> list[str]:
    """List settings the local or remote controller reports as unsupported.

    capabilities maps CapabilitiesSource to the latest report. The negotiated
    configuration and procedure are checked when present, otherwise the
    requested host packet. Checks against a missing report are skipped.
    """
    if not capabilities:
        return []
    initiator_request = isinstance(requested, CsInitiatorConfigPacket)
    if configuration is not None:
        role = configuration.role
        c = {name: getattr(configuration, name) for name in
             ("mode", "rtt_type", "cs_sync_phy", "channel_selection_type", "cs_enhancements_1",
              "t_ip1_time_us", "t_ip2_time_us", "t_fcs_time_us", "t_pm_time_us")}
    elif isinstance(requested, HOST_PACKETS):
        role = 0 if initiator_request else 1
        c = {name: getattr(requested, "creation_" + name) for name in
             ("mode", "rtt_type", "cs_sync_phy", "channel_selection_type", "cs_enhancements_1")} \
            if initiator_request else {}
        # Before configuration complete, a requested T_PM is the only timing to check.
        if c and t_pm != T_PM_DEFAULT_US:
            c["t_pm_time_us"] = t_pm
    else:
        return []
    local, remote = capabilities.get(CapabilitiesSource.LOCAL), capabilities.get(CapabilitiesSource.REMOTE)
    sides = {"initiator": local if role == 0 else remote, "reflector": remote if role == 0 else local}
    names = {id(local): "local", id(remote): "remote"}
    issues: list[str] = []
    failures: list[str] = []

    def each(check):
        for side, caps in sides.items():
            if caps is not None:
                message = check(side, caps)
                if message:
                    issues.append(f"{side.capitalize()} ({names[id(caps)]}): {message}")

    each(lambda side, caps: None if getattr(caps, f"{side}_supported") else f"{side} role not supported")
    mode = c.get("mode")
    if mode is not None:
        if _uses(mode, {3}):
            each(lambda side, caps: None if caps.mode_3_supported else "mode 3 not supported")
        if _uses(mode, {1, 3}):
            rtt_type = c["rtt_type"]
            attribute = ("rtt_aa_only_n" if rtt_type == 0 else "rtt_sounding_n" if rtt_type in (1, 2)
                         else "rtt_random_payload_n")
            each(lambda side, caps: None if getattr(caps, attribute)
                 else f"RTT {_label(RTT_TYPES, rtt_type)} not supported")
        phy = c["cs_sync_phy"]
        if phy in (2, 3):
            attribute = "cs_sync_2m_phy_supported" if phy == 2 else "cs_sync_2m_2bt_phy_supported"
            each(lambda side, caps: None if getattr(caps, attribute) else f"CS_SYNC {SYNC_PHYS[phy]} not supported")
        if c["channel_selection_type"] == 1:
            each(lambda side, caps: None if caps.chsel_alg_3c_supported else "CSA #3c not supported")
        # Reflector data none runs on IPT alone: the firmware ends the run without it
        # (PEER_IPT_UNSUPPORTED), so these are failures, not warnings.
        initiator_only = peer_data == 1 and role == 0
        if initiator_only and not c["cs_enhancements_1"] & ENHANCEMENTS_1_IPT:
            failures.append(f"{RUN_FAILS}configuration: IPT not enabled, needed for reflector data none")
        if c["cs_enhancements_1"] & ENHANCEMENTS_1_IPT and sides["reflector"] is not None:
            caps = sides["reflector"]
            if not caps.cs_ipt_reflector_supported:
                (failures if initiator_only else issues).append(
                    (RUN_FAILS if initiator_only else "") + f"Reflector ({names[id(caps)]}): IPT not supported" +
                    (", needed for reflector data none" if initiator_only else ""))
            elif "t_ip2_time_us" in c and c["t_ip2_time_us"] not in bit_values(caps.t_ip2_ipt_times_supported,
                                                                               T_IP_TIMES_US):
                issues.append(f"Reflector ({names[id(caps)]}): T_IP2 {c['t_ip2_time_us']} µs not supported with IPT")
    for name, attribute, values, mandatory in (("T_IP1", "t_ip1_times_supported", T_IP_TIMES_US, T_IP_MANDATORY_US),
                                               ("T_IP2", "t_ip2_times_supported", T_IP_TIMES_US, T_IP_MANDATORY_US),
                                               ("T_FCS", "t_fcs_times_supported", T_FCS_TIMES_US, T_FCS_MANDATORY_US),
                                               ("T_PM", "t_pm_times_supported", T_PM_TIMES_US, T_PM_MANDATORY_US)):
        value = c.get(name.lower() + "_time_us")
        if value is not None and value != mandatory:
            each(lambda side, caps, name=name, attribute=attribute, values=values, value=value:
                 None if value in bit_values(getattr(caps, attribute), values) else f"{name} {value} µs not supported")
    mask = getattr(requested, "preferred_peer_antenna", None)
    if initiator_request and mask is not None and sides["reflector"] is not None:
        # cs_roles ends the setup at remote capabilities (CS_CONFIG_FAILED, -ERANGE): a reflector
        # controller may switch to such an antenna unchecked, which faults the nRF54L15 Tag.
        count = sides["reflector"].num_antennas_supported
        if count < 4 and mask >> count:
            failures.append(f"{RUN_FAILS}Reflector ({names[id(sides['reflector'])]}): preferred peer antenna "
                            f"0x{mask:02x} names an antenna beyond its {count}")
    selection = procedure.tone_antenna_config_selection if procedure else getattr(
        requested, "tone_antenna_config_selection", None)
    if selection is not None and 0 <= selection < len(TONE_ANTENNA_COUNTS):
        antennas = dict(zip(("initiator", "reflector"), TONE_ANTENNA_COUNTS[selection]))
        paths = ANTENNA_PATHS[selection]
        each(lambda side, caps: f"{antennas[side]} antennas needed, {caps.num_antennas_supported} supported"
             if antennas[side] > caps.num_antennas_supported else None)
        each(lambda side, caps: f"{paths} antenna paths needed, {caps.max_antenna_paths_supported} supported"
             if paths > caps.max_antenna_paths_supported else None)
    count = procedure.procedure_count if procedure else getattr(requested, "max_procedure_count", None)
    if count is not None:
        each(lambda side, caps: None if caps.max_consecutive_procedures_supported == 0
             else "indefinite procedure count not supported" if count == 0
             else f"{count} consecutive procedures, up to {caps.max_consecutive_procedures_supported} supported"
             if count > caps.max_consecutive_procedures_supported else None)
    if initiator_request or isinstance(requested, CsReflectorConfigPacket):
        for side, attribute in (("initiator", "snr_control_initiator"), ("reflector", "snr_control_reflector")):
            level, caps = getattr(requested, attribute), sides[side]
            if caps is not None and level != SNR_CONTROL_NONE and not caps.tx_snr_capability & (1 << level):
                issues.append(f"{side.capitalize()} ({names[id(caps)]}): SNR control "
                              f"{SNR_LEVELS_DB[level] if level < len(SNR_LEVELS_DB) else level} dB not supported")
    return failures + issues


@dataclass
class ControllerReports:
    """Latest capabilities per source, configuration per ID and procedure enable per configuration ID.

    A disable report only marks the last enabled procedure disabled; its other fields are not meaningful.
    """

    capabilities: dict[int, CsCapabilitiesPacket] = field(default_factory=dict)
    configurations: dict[int, CsConfigurationPacket] = field(default_factory=dict)
    procedures: dict[int, CsProcedureEnableCompletePacket] = field(default_factory=dict)
    connection: ConnectionParametersPacket | None = None

    def add(self, packet: Any) -> bool:
        """Keep a report; False for any other packet."""
        if isinstance(packet, CsCapabilitiesPacket):
            self.capabilities[packet.source] = packet
        elif isinstance(packet, CsConfigurationPacket):
            self.configurations[packet.id] = packet
        elif isinstance(packet, CsProcedureEnableCompletePacket):
            if packet.state:
                self.procedures[packet.config_id] = packet
            elif packet.config_id in self.procedures:
                # A disable report carries no procedure parameters (Core Vol 4, Part E, §7.7.65.43).
                self.procedures[packet.config_id] = replace(self.procedures[packet.config_id], state=0)
        elif isinstance(packet, ConnectionParametersPacket):
            self.connection = packet
        else:
            return False
        return True

    def clear(self) -> None:
        self.capabilities.clear()
        self.configurations.clear()
        self.procedures.clear()
        self.connection = None

    def current(self, config_id: int | None = None):
        """(configuration, procedure) for config_id, else the most recently reported ones."""
        if config_id is None:
            config_id = next(reversed(self.procedures), next(reversed(self.configurations), None))
        return self.configurations.get(config_id), self.procedures.get(config_id)


def source_label(caps: CsCapabilitiesPacket) -> str:
    if caps.source == CapabilitiesSource.LOCAL:
        return "Local"
    return "Remote" if caps.conn_index == CAPABILITIES_CONN_NONE else f"Remote (connection {caps.conn_index})"
