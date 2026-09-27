"""Convert between planner scenarios and CS protocol configuration packets.

Uses only the standard library and protocol dataclasses, so transports and
tests can use it without Qt. Incoming configurations update a ``Scenario``;
outgoing host configuration packets are built from one.

Host configuration fields the planner does not model (GAP role, TX power,
procedure PHY, SNR control, creation context, ...) are kept in a separate
``host`` mapping so they survive an apply/collect round trip. Timing choices
(T_IP1, T_IP2, T_FCS, T_PM) are selected by the controller and have no field in
the host packets; they arrive only in a negotiated ``CsConfigurationPacket``.
``configuration.t_pm_time_us`` therefore stays the negotiated value, while the
preferred T_PM a CS initiator requests is the separate ``t_pm`` host setting,
sent as its own ``SET_T_PM`` packet (§8.4 step 2). ACL interval, latency and
timeout are requested by the host; ``ConnectionParametersPacket`` reports what
the link uses and narrows the requested range to it. The ATT MTU of that report
is never requested: it replaces ``connection.mtu``, which is the pre-negotiation
ATT default until a link reports its own.
"""

from dataclasses import fields, replace

from ..protocol.frame import Frame
from ..protocol.packets import (ConnectionParametersPacket, CsConfigurationPacket, CsInitiatorConfigPacket,
                                 CsProcedureEnableCompletePacket, CsReflectorConfigPacket,
                                 OperationMode, T_PM_DEFAULT_US, T_PM_MANDATORY_US, T_PM_VALUES_US, decode_packet)

from .model import (ATT_DEFAULT_MTU, NEUTRAL_MAIN_MODE_STEPS, Scenario, channel_map_bytes,
                    has_sub_mode)

HOST_PACKETS = (CsInitiatorConfigPacket, CsReflectorConfigPacket)
NEGOTIATED_PACKETS = (CsConfigurationPacket, CsProcedureEnableCompletePacket)
CONFIG_TYPES = (Scenario, *HOST_PACKETS, *NEGOTIATED_PACKETS, ConnectionParametersPacket)
# Firmware defaults (common/libs/cs_utils/cs_config.c) for host fields outside the planner.
HOST_DEFAULTS = {
    "gap_role": 0,  # central
    "cs_sync_antenna_selection": 0xFE,  # repetitive
    "max_tx_power": 20,
    "phy": 1,  # LE 1M
    "tx_power_delta": -128,  # no recommendation
    "preferred_peer_antenna": 1,
    "snr_control_initiator": 0xFF,  # not used
    "snr_control_reflector": 0xFF,
    "creation_context": 1,  # local and remote
    "peer_data": 0,  # RAS real-time; 1 selects initiator-only data with IPT
    "t_pm": T_PM_MANDATORY_US,  # preferred T_PM; select the standard-mandatory 40 us by default
    "log": {"console": 3, "host": 2},  # firmware defaults: info console, warning host
}
# creation_<name> fields carry CsConfigurationPacket.<name>; creation_context is host-only.
CREATION_FIELDS = tuple(item.name for item in fields(CsInitiatorConfigPacket)
                        if item.name.startswith("creation_") and item.name not in HOST_DEFAULTS)
NEGOTIATED_SOURCE = "Controller fields supplied; ACL/offset/workload remain assumptions"
CONNECTION_SOURCE = "ACL parameters reported by the client; offset/workload remain assumptions"
HOST_SOURCE = "Host configuration applied; controller-selected timing fields remain assumptions until reported"


def decode_config(data):
    """Return a Scenario or configuration packet from a packet, Frame or complete wire frame."""
    if isinstance(data, (bytes, bytearray, memoryview)):
        data = Frame.from_bytes(data)
    if isinstance(data, Frame):
        data = decode_packet(data)
    if not isinstance(data, CONFIG_TYPES):
        name = f"Frame 0x{data.packet_type:04x}" if isinstance(data, Frame) else type(data).__name__
        raise TypeError(f"{name} is not a planner configuration; expected a Scenario, a CS initiator/reflector "
                        "config packet, a CS configuration packet or a procedure enable complete packet")
    return data


def _clamp(value, low, high):
    """Keep a planner-selected value inside a requested range; leave inverted ranges to validation."""
    return min(max(value, low), high) if low <= high else value


def _repair_controller_timing_assumptions(scenario):
    """Raise provisional controller-selected spacings to the planner's valid minima.

    Host configuration packets do not contain subevents/event or their spacing;
    until Procedure Enable Complete arrives, those fields are only assumptions.
    Keep an already-valid value, but move an invalid assumption to the same
    minimum the validation message recommends.
    """
    p, connection = scenario.procedure, scenario.connection
    if not 1 <= p.subevents_per_event <= 32:
        return scenario
    subevent_interval = p.subevent_interval
    if p.subevents_per_event == 1:
        subevent_interval = 0
    else:
        minimum = (p.subevent_len + 150) // 625 + 1
        if subevent_interval < minimum:
            subevent_interval = minimum
    event_span = (p.subevents_per_event - 1) * subevent_interval * 625 + p.subevent_len
    interval_us = max(1, connection.interval_us)
    minimum_event_interval = (event_span + 150 + interval_us - 1) // interval_us
    event_interval = (max(p.event_interval, minimum_event_interval)
                      if minimum_event_interval <= 65535 else p.event_interval)
    if subevent_interval == p.subevent_interval and event_interval == p.event_interval:
        return scenario
    return replace(scenario, procedure=replace(p, subevent_interval=subevent_interval,
                                               event_interval=event_interval))


def apply_packet(scenario: Scenario, host: dict, packet) -> tuple[Scenario, dict]:
    """Return (scenario, host) updated from one decoded configuration.

    A Scenario replaces everything. Negotiated packets replace the configuration
    or procedure as reported, and reported ACL parameters replace the connection.
    Host packets carry requested ranges; the planner's selected interval, subevent
    length and procedure spacing are clamped into them.
    """
    if isinstance(packet, Scenario):
        return packet, host
    s = scenario
    requested = None
    if isinstance(packet, NEGOTIATED_PACKETS):
        mode = OperationMode.CS_REFLECTOR if s.configuration.role == 1 else OperationMode.CS_INITIATOR
        requested = config_packet(s, host, mode)
    if isinstance(packet, CsConfigurationPacket):
        s = replace(s, configuration=packet, procedure=replace(s.procedure, config_id=packet.id))
    elif isinstance(packet, CsProcedureEnableCompletePacket):
        s = replace(s, procedure=packet)
    elif isinstance(packet, ConnectionParametersPacket):
        host_assumption = scenario.provenance == HOST_SOURCE
        # A live link has one interval, not a range, so the request narrows to what it uses.
        # A report without an MTU (no link, or a client older than protocol 0x000B) leaves the
        # pre-negotiation default, which is what such a link uses.
        s = replace(s, connection=replace(s.connection, interval_min=packet.interval, interval_max=packet.interval,
                                          interval=packet.interval, latency=packet.latency, timeout=packet.timeout,
                                          mtu=max(ATT_DEFAULT_MTU, packet.mtu)))
        if host_assumption:
            s = _repair_controller_timing_assumptions(s)
    elif isinstance(packet, HOST_PACKETS):
        a, p = s.connection, s.procedure
        connection = replace(a, interval_min=packet.connection_interval_min,
                             interval_max=packet.connection_interval_max,
                             interval=_clamp(a.interval, packet.connection_interval_min, packet.connection_interval_max),
                             latency=packet.connection_latency, timeout=packet.connection_timeout)
        procedure = replace(p, config_id=packet.config_id, max_procedure_len=packet.max_procedure_len,
                            procedure_interval=_clamp(p.procedure_interval, packet.min_procedure_interval,
                                                      packet.max_procedure_interval),
                            procedure_count=packet.max_procedure_count,
                            subevent_len=_clamp(p.subevent_len, packet.min_subevent_len, packet.max_subevent_len),
                            tone_antenna_config_selection=packet.tone_antenna_config_selection)
        initiator = isinstance(packet, CsInitiatorConfigPacket)
        creation = {name.removeprefix("creation_"): getattr(packet, name) for name in CREATION_FIELDS} if initiator else {}
        configuration = replace(s.configuration, id=packet.config_id, role=0 if initiator else 1, **creation)
        s = replace(s, connection=connection, procedure=procedure, configuration=configuration)
        host = {name: getattr(packet, name, value) for name, value in {**HOST_DEFAULTS, **host}.items()}
        for name in ("min_procedure_interval", "max_procedure_interval", "min_subevent_len", "max_subevent_len"):
            host[name] = getattr(packet, name)
        host["_selected_procedure_interval"] = procedure.procedure_interval
        host["_selected_subevent_len"] = procedure.subevent_len
        host.pop("_requested_wire", None)
        host.pop("_negotiated_wire", None)
        s = _repair_controller_timing_assumptions(s)
    else:
        raise TypeError(f"{type(packet).__name__} is not a planner configuration")
    c = s.configuration
    s = replace(s, main_steps=_clamp(s.main_steps, c.min_main_mode_steps, c.max_main_mode_steps))
    if requested is not None:
        host = {key: value for key, value in host.items() if key not in ("_requested_wire", "_negotiated_wire")}
        reference = config_packet(s, host, mode)
        host["_requested_wire"] = requested.to_bytes().hex()
        host["_negotiated_wire"] = reference.to_bytes().hex()
    return s, host


def source_label(packets, default: str) -> str:
    """Describe where the applied fields came from, for the view's provenance line."""
    if any(isinstance(packet, ConnectionParametersPacket) for packet in packets):
        return CONNECTION_SOURCE
    if any(isinstance(packet, NEGOTIATED_PACKETS) for packet in packets):
        return NEGOTIATED_SOURCE
    if any(isinstance(packet, HOST_PACKETS) for packet in packets):
        return HOST_SOURCE
    return default


def apply_channel_list(scenario: Scenario, channels) -> Scenario:
    """Set the channel map from channel indices, or from a raw 10-byte map kept as given."""
    if isinstance(channels, (bytes, bytearray, memoryview)):
        channel_map = bytes(channels)
        if len(channel_map) != 10:
            raise ValueError(f"A CS channel map must contain 10 bytes, not {len(channel_map)}")
    else:
        channels = tuple(channels)
        if not all(isinstance(ch, int) and not isinstance(ch, bool) and 0 <= ch < 80 for ch in channels):
            raise ValueError("CS channel indices must be integers 0–79")
        channel_map = channel_map_bytes(channels)
    return replace(scenario, configuration=replace(scenario.configuration, channel_map=channel_map))


def config_packet(scenario: Scenario, host: dict | None = None, mode=OperationMode.CS_INITIATOR):
    """Build the host configuration packet that requests this scenario.

    Loaded requests retain their ranges until the selected value is edited.
    New or edited requests use min = max. Field widths are checked so the packet can be transmitted.
    """
    host = {**HOST_DEFAULTS, **(host or {})}
    a, p, c = scenario.connection, scenario.procedure, scenario.configuration
    if host["peer_data"] not in (0, 1):
        raise ValueError("peer_data must be 0 (RAS real-time) or 1 (initiator only)")
    if mode == OperationMode.CS_INITIATOR and host["peer_data"] == 1 and not (c.cs_enhancements_1 & 0x01):
        raise ValueError("initiator-only reflector data requires Inline PCT transfer (IPT)")
    if mode != OperationMode.CS_INITIATOR and host["peer_data"] != 0:
        raise ValueError("initiator-only reflector data is valid only for CS initiator mode")
    if host["t_pm"] not in T_PM_VALUES_US:
        raise ValueError("t_pm must be 10, 20 or 40 us")
    if mode != OperationMode.CS_INITIATOR and host["t_pm"] not in (T_PM_DEFAULT_US, T_PM_MANDATORY_US):
        raise ValueError("a preferred T_PM is valid only for CS initiator mode")
    values = dict(
        gap_role=host["gap_role"], config_id=c.id,
        connection_interval_min=a.interval_min, connection_interval_max=a.interval_max,
        connection_latency=a.latency, connection_timeout=a.timeout,
        cs_sync_antenna_selection=host["cs_sync_antenna_selection"], max_tx_power=host["max_tx_power"],
        max_procedure_len=p.max_procedure_len,
        min_procedure_interval=p.procedure_interval, max_procedure_interval=p.procedure_interval,
        max_procedure_count=p.procedure_count,
        min_subevent_len=p.subevent_len, max_subevent_len=p.subevent_len,
        tone_antenna_config_selection=p.tone_antenna_config_selection, phy=host["phy"],
        tx_power_delta=host["tx_power_delta"], preferred_peer_antenna=host["preferred_peer_antenna"],
        snr_control_initiator=host["snr_control_initiator"], snr_control_reflector=host["snr_control_reflector"])
    for name, selected in (("procedure_interval", p.procedure_interval), ("subevent_len", p.subevent_len)):
        low, high = host.get("min_" + name, selected), host.get("max_" + name, selected)
        if host.get("_selected_" + name) == selected and low <= selected <= high:
            values["min_" + name], values["max_" + name] = low, high
    if mode == OperationMode.CS_INITIATOR:
        creation = {name: getattr(c, name.removeprefix("creation_")) for name in CREATION_FIELDS}
        if not has_sub_mode(c.mode):
            # The bounds only order main-mode steps against sub-mode steps (§14). The CS view
            # disables them without a sub-mode, so the request must not carry a stale value.
            creation["creation_min_main_mode_steps"] = NEUTRAL_MAIN_MODE_STEPS
            creation["creation_max_main_mode_steps"] = NEUTRAL_MAIN_MODE_STEPS
        packet = CsInitiatorConfigPacket(**values, **creation, creation_context=host["creation_context"])
    elif mode == OperationMode.CS_REFLECTOR:
        packet = CsReflectorConfigPacket(**values)
    else:
        raise ValueError(f"No CS configuration packet for operation mode {mode!r}")
    if host.get("_requested_wire") and host.get("_negotiated_wire"):
        requested = decode_config(bytes.fromhex(host["_requested_wire"]))
        reference = decode_config(bytes.fromhex(host["_negotiated_wire"]))
        if type(packet) is type(requested):
            packet = replace(packet, **{f.name: getattr(requested, f.name) for f in fields(packet)
                                       if getattr(packet, f.name) == getattr(reference, f.name)})
    packet.to_frame()  # raises ProtocolError on out-of-range field values
    return packet
