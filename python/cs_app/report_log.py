"""One-line descriptions of protocol packets, worded like the client firmware log."""
from dataclasses import dataclass
from enum import IntEnum

from .protocol.frame import Frame
from .protocol.packets import (CapabilitiesSource, ClientState, ClientStatePacket, CommandResponsePacket,
                               ConnectResponsePacket, CsCapabilitiesPacket, CsConfigurationPacket,
                               CsFaeTablePacket, CsInitiatorSubeventResultPacket, CsPeerDataPacket,
                               ConnectionParametersPacket,
                               CsProcedureEnableCompletePacket,
                               CsProceduresCompletePacket, CsSubeventResultPacket, LogMessagePacket, OperationMode,
                               PacketType, ProtocolStatus, RadioTestStatsPacket, RasDataLostPacket, RejectReason,
                               ScanResultPacket, StartPacket, error_name)

INFO, WARNING, ERROR = "inf", "wrn", "err"

# Categories the log view can hide; subevents alone arrive tens of times a second.
SUBEVENTS, COMMANDS, CLIENT_LOG, EVENTS = "subevents", "commands", "client log", "events"


@dataclass(frozen=True, slots=True)
class LogLine:
    level: str
    category: str
    text: str


def _name(enum: type[IntEnum], value: int) -> str:
    try:
        return enum(value).name
    except ValueError:
        return f"0x{value:02x}"


def _suffix(reason: int = 0, hci_status: int = 0, error: int = 0) -> str:
    parts = []
    if reason:
        parts.append(f"reason {_name(RejectReason, reason)}")
    if hci_status:
        parts.append(f"HCI status 0x{hci_status:02x}")
    if error:
        parts.append(f"error {error_name(error)}")
    return (", " + ", ".join(parts)) if parts else ""


def _subevent(packet: CsSubeventResultPacket) -> LogLine:
    role = "initiator" if isinstance(packet, CsInitiatorSubeventResultPacket) else "reflector"
    text = (f"CS {role} subevent: config {packet.config_id}, event {packet.start_acl_conn_event}, "
            f"procedure {packet.procedure_counter}, steps {len(packet.steps)}, paths {packet.num_antenna_paths}, "
            f"procedure status 0x{packet.procedure_done_status:02x}, subevent status 0x{packet.subevent_done_status:02x}")
    aborted = packet.procedure_abort_reason or packet.subevent_abort_reason
    if aborted:
        text += (f", abort reasons 0x{packet.procedure_abort_reason:02x}/0x{packet.subevent_abort_reason:02x}"
                 f" at step {packet.abort_step}")
    return LogLine(WARNING if aborted else INFO, SUBEVENTS, text)


def describe_received(packet) -> LogLine:
    """Describe a packet received from the client."""
    if isinstance(packet, CsSubeventResultPacket):
        return _subevent(packet)
    if isinstance(packet, LogMessagePacket):
        text = packet.message.decode("utf-8", errors="replace").rstrip()
        # app_log.c prefixes every record with "<err>", "<wrn>", "<inf>" or "<dbg>".
        tag = text[1:4] if text.startswith("<") and text[4:5] == ">" else ""
        return LogLine({"err": ERROR, "wrn": WARNING}.get(tag, INFO), CLIENT_LOG, text)
    if isinstance(packet, ClientStatePacket):
        failed = packet.state in (ClientState.ERROR, ClientState.LINK_LOST) or packet.error
        return LogLine(WARNING if failed else INFO, EVENTS,
                       f"State {_name(ClientState, packet.state)}, mode {_name(OperationMode, packet.operation_mode)}"
                       + _suffix(packet.reason, packet.hci_status, packet.error))
    if isinstance(packet, CsConfigurationPacket):
        return LogLine(INFO, EVENTS,
                       f"CS configuration {packet.id}: mode 0x{packet.mode:02x}, "
                       f"role {'initiator' if packet.role == 0 else 'reflector'}, "
                       f"RTT type {packet.rtt_type}, main mode steps {packet.min_main_mode_steps}-"
                       f"{packet.max_main_mode_steps}, mode 0 steps {packet.mode_0_steps}, T_IP1 {packet.t_ip1_time_us}, "
                       f"T_IP2 {packet.t_ip2_time_us}, T_FCS {packet.t_fcs_time_us}, T_PM {packet.t_pm_time_us} µs")
    if isinstance(packet, CsProcedureEnableCompletePacket):
        if not packet.state:
            # A disable report carries no procedure parameters.
            return LogLine(INFO, EVENTS, f"Procedures off: config {packet.config_id}")
        return LogLine(INFO, EVENTS,
                       f"Procedures {'on' if packet.state else 'off'}: config {packet.config_id}, "
                       f"interval {packet.procedure_interval}, count {packet.procedure_count}, "
                       f"subevent length {packet.subevent_len} µs, {packet.subevents_per_event} per event, "
                       f"TX power {packet.selected_tx_power} dBm")
    if isinstance(packet, CsCapabilitiesPacket):
        roles = "/".join(role for role, supported in (("initiator", packet.initiator_supported),
                                                      ("reflector", packet.reflector_supported)) if supported)
        return LogLine(INFO, EVENTS,
                       f"CS capabilities ({_name(CapabilitiesSource, packet.source).lower()}): {roles or 'no roles'}, "
                       f"{packet.num_antennas_supported} antennas, {packet.max_antenna_paths_supported} paths, "
                       f"mode 3 {'yes' if packet.mode_3_supported else 'no'}, T_SW {packet.t_sw_time} µs")
    if isinstance(packet, CsFaeTablePacket):
        if packet.hci_status:
            return LogLine(WARNING, EVENTS, f"Remote FAE table read failed: HCI status 0x{packet.hci_status:02x}")
        return LogLine(INFO, EVENTS, "Remote FAE table read")
    if isinstance(packet, RasDataLostPacket):
        return LogLine(WARNING, EVENTS,
                       f"RAS data lost: procedure {packet.ranging_counter}, error {error_name(packet.error)}")
    if isinstance(packet, CsPeerDataPacket):
        return LogLine(INFO, EVENTS, "Reflector data: " + ("none (initiator only)" if packet.peer_data == 1
                                                           else "RAS real-time"))
    if isinstance(packet, ConnectionParametersPacket):
        return LogLine(INFO, EVENTS,
                       f"ACL connection parameters: interval {packet.interval * 1.25:g} ms, "
                       f"latency {packet.latency} events, timeout {packet.timeout * 10:g} ms, "
                       f"ATT MTU {packet.mtu} bytes")
    if isinstance(packet, CsProceduresCompletePacket):
        return LogLine(INFO, EVENTS,
                       f"max_procedure_count reached: {packet.procedures_completed} procedures completed")
    if isinstance(packet, RadioTestStatsPacket):
        return LogLine(INFO, EVENTS,
                       f"Radio RX: channel {packet.channel}, packets {packet.packets_received}, "
                       f"CRC errors {packet.crc_errors}, RSSI {packet.rssi_dbm} dBm")
    if isinstance(packet, ScanResultPacket):
        return LogLine(INFO, EVENTS,
                       f"Scan result: {packet.address_text} ({'random' if packet.address_type else 'public'}), "
                       f"RSSI {packet.rssi_dbm} dBm, {'connectable' if packet.flags & 1 else 'not connectable'}"
                       + (f", \"{packet.peer_name}\"" if packet.name_length else ""))
    if isinstance(packet, ConnectResponsePacket):
        return LogLine(INFO if packet.status == ProtocolStatus.OK else ERROR, COMMANDS,
                       f"Connect response {_name(ProtocolStatus, packet.status)}: protocol {packet.protocol_version}, "
                       f"firmware 0x{packet.firmware_version:08x}, state {_name(ClientState, packet.client_state)}, "
                       f"configuration {'held' if packet.config_valid else 'empty'} "
                       f"(CRC 0x{packet.config_crc32:08x})")
    if isinstance(packet, CommandResponsePacket):
        return LogLine(INFO if packet.status == ProtocolStatus.OK else ERROR, COMMANDS,
                       f"{_name(PacketType, packet.request_type)} response {_name(ProtocolStatus, packet.status)}"
                       + _suffix(packet.reason, 0, packet.error))
    if isinstance(packet, Frame):
        return LogLine(WARNING, EVENTS, f"Unknown frame type 0x{packet.packet_type:04x}, {len(packet.payload)} bytes")
    return LogLine(INFO, EVENTS, type(packet).__name__)


def describe_sent(packet) -> LogLine:
    """Describe a command sent to the client."""
    text = packet.PACKET_TYPE.name
    if isinstance(packet, StartPacket):
        text += f" (configuration CRC 0x{packet.config_crc32:08x})"
    elif hasattr(packet, "config_id"):
        text += f" (config ID {packet.config_id})"
    elif hasattr(packet, "mode"):
        text += f" ({_name(OperationMode, packet.mode)})"
    return LogLine(INFO, COMMANDS, text)
