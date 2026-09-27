"""Python packet definitions matching ``cs_protocol_packets.h`` exactly."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import IntEnum, IntFlag
import struct
from typing import Any, ClassVar, TypeVar

from .frame import Frame, ProtocolError

PROTOCOL_VERSION = 0x000B
"""``CS_PROTOCOL_VERSION``: sent in CONNECT and returned in CONNECT_RESPONSE."""

FAE_TABLE_ENTRIES = 72
"""``CS_PROTOCOL_FAE_TABLE_ENTRIES``."""


class PacketType(IntEnum):
    """Values of ``enum cs_protocol_packet_type_t`` in the C header."""

    INVALID = 0x0000
    CS_CAPABILITIES = 0x0001
    CS_CONFIGURATION = 0x0002
    CS_PROCEDURE_ENABLE_COMPLETE = 0x0003
    CS_INITIATOR_SUBEVENT_RESULT = 0x0004
    CS_REFLECTOR_SUBEVENT_RESULT = 0x0005
    LOG_MESSAGE = 0x0006
    CONNECT_RESPONSE = 0x0007
    COMMAND_RESPONSE = 0x0008
    CS_FAE_TABLE = 0x0009
    CLIENT_STATE = 0x000A
    RAS_DATA_LOST = 0x000B
    RADIO_TEST_STATS = 0x000C
    SET_OPERATION_MODE = 0x0100
    SET_CS_INITIATOR_CONFIG = 0x0101
    SET_CS_REFLECTOR_CONFIG = 0x0102
    SET_RADIO_TX_TEST_CONFIG = 0x0103
    SET_PERIPHERAL_PATTERNS = 0x0104
    APPLY_CONFIG = 0x0105
    CONNECT = 0x0106
    START = 0x0107
    STOP = 0x0108
    CLOSE_SESSION = 0x0109
    GET_CONFIG = 0x010A
    LINK_DISCONNECT = 0x010B
    SET_DEVICE_NAME = 0x010C
    SCAN_START = 0x010D
    PEER_CONNECT = 0x010E
    ADVERTISE_START = 0x010F
    SCAN_RESULT = 0x000D
    CS_PROCEDURES_COMPLETE = 0x000E
    CS_PEER_DATA = 0x000F
    CONNECTION_PARAMETERS = 0x0010
    SET_PEER_DATA = 0x0110
    SET_LOG_CONFIG = 0x0111
    SET_T_PM = 0x0112


class CapabilitiesSource(IntEnum):
    """``CsCapabilitiesPacket.source``; ``enum cs_protocol_cs_capabilities_source_t``."""

    LOCAL = 0
    REMOTE = 1


CAPABILITIES_CONN_NONE = 0xFF
"""``CS_PROTOCOL_CS_CAPABILITIES_CONN_NONE``."""


class OperationMode(IntEnum):
    """Values accepted by ``cs_protocol_operation_mode_frame_t.mode``."""

    CS_INITIATOR = 0
    CS_REFLECTOR = 1
    RADIO_TX_TEST = 2
    HOSTLESS_CS = 3


class RadioTestType(IntEnum):
    """``RadioTxTestConfigPacket.test_type``; mirrors ``enum radio_test_mode_type``."""

    UNMODULATED_TX = 0
    MODULATED_TX = 1
    RX = 2
    TX_SWEEP = 3
    RX_SWEEP = 4
    MODULATED_TX_DUTY_CYCLE = 5
    TX_SWEEP_WITH_SLEEP = 6
    TX_SWEEP_WITH_SLEEP_MODULATED = 7


class RadioTestPhy(IntEnum):
    """``RadioTxTestConfigPacket.phy``; mirrors ``enum radio_test_mode_phy``."""

    BLE_1M = 0
    BLE_2M = 1
    BLE_LR125K = 2
    BLE_LR500K = 3
    NRF_1M = 4
    NRF_2M = 5
    IEEE802154_250K = 6


class RadioTestPattern(IntEnum):
    """``RadioTxTestConfigPacket.pattern``; mirrors ``enum radio_test_mode_pattern``."""

    RANDOM = 0
    PATTERN_11110000 = 1
    PATTERN_11001100 = 2
    PATTERN_00000000 = 3
    PATTERN_11111111 = 4


OPERATION_MODE_NONE = 0xFF
"""``CS_PROTOCOL_MODE_NONE``: ``operation_mode`` when no configuration is applied."""


class OperationModeMask(IntFlag):
    """``supported_modes`` bits: bit n is :class:`OperationMode` n."""

    CS_INITIATOR = 1 << OperationMode.CS_INITIATOR
    CS_REFLECTOR = 1 << OperationMode.CS_REFLECTOR
    RADIO_TX_TEST = 1 << OperationMode.RADIO_TX_TEST

    @classmethod
    def of(cls, mode: int) -> "OperationModeMask":
        """Return the bit for one operation mode."""
        return cls(1 << OperationMode(mode))

    def modes(self) -> list[OperationMode]:
        """Operation modes whose bits are set."""
        return [mode for mode in OperationMode if self & (1 << mode)]


class ProtocolStatus(IntEnum):
    """``enum cs_protocol_status``: CONNECT_RESPONSE and COMMAND_RESPONSE status."""

    OK = 0x00
    REJECTED = 0x01
    UNSUPPORTED = 0x02
    BAD_STATE = 0x03
    INVALID_FRAME = 0x04
    VERSION = 0x05
    FAILED = 0x06
    CONFIG_MISMATCH = 0x07


class RejectReason(IntEnum):
    """``enum cs_protocol_reject_reason``: COMMAND_RESPONSE and CLIENT_STATE reason."""

    NONE = 0x00
    NOT_CONNECTED = 0x01
    MODE_MISMATCH = 0x02
    VALUE_OUT_OF_RANGE = 0x03
    NONZERO_PADDING = 0x04
    MISSING_CONFIG = 0x05
    MISSING_PATTERNS = 0x06
    BUSY = 0x07
    LINK_ACTIVE = 0x08
    STOP_TIMEOUT = 0x09
    RAS_NO_REALTIME = 0x0A
    TEST_COMPLETE = 0x0B
    SCAN_FAILED = 0x0D
    ADVERTISE_FAILED = 0x0E
    CONNECT_FAILED = 0x0F
    SECURITY_FAILED = 0x10
    RAS_DISCOVERY_FAILED = 0x11
    CS_CONFIG_FAILED = 0x12
    CS_SECURITY_FAILED = 0x13
    PEER_IPT_UNSUPPORTED = 0x14
    INTERRUPTED = 0x0C


class ClientState(IntEnum):
    """``enum cs_protocol_client_state``."""

    IDLE = 0x00
    CONFIGURED = 0x01
    SCANNING = 0x02
    ADVERTISING = 0x03
    LINK_CONNECTED = 0x04
    RAS_READY = 0x05
    RUNNING = 0x06
    STOPPED = 0x07
    LINK_LOST = 0x08
    LINK_DISCONNECTED = 0x09
    ERROR = 0x0A
    LINK_CONNECTING = 0x0B


class GapRole(IntEnum):
    """GAP roles used by both CS configuration command packets."""

    CENTRAL = 0
    PERIPHERAL = 1


PacketT = TypeVar("PacketT", bound="FixedPacket")


class FixedPacket:
    """Shared codec for packets whose C frame has a fixed size.

    Subclasses declare their message fields as dataclass attributes, in C
    declaration order. ``STRUCT`` describes only those fields; the generic
    :class:`~cs_app.protocol.frame.Frame` supplies the common header and footer.
    Values returned by Python's ``struct`` module are native Python integers
    and bytes, while every multi-byte wire field is encoded little endian.
    """

    PACKET_TYPE: ClassVar[PacketType]
    STRUCT: ClassVar[struct.Struct]

    def _values(self) -> tuple[Any, ...]:
        return tuple(getattr(self, field.name) for field in fields(self))

    def to_frame(self) -> Frame:
        """Pack message fields and return a generic, unserialized frame."""
        try:
            payload = self.STRUCT.pack(*self._values())
        except struct.error as error:
            raise ProtocolError(str(error)) from error
        return Frame(self.PACKET_TYPE, payload)

    def to_bytes(self) -> bytes:
        """Return the complete serialized frame ready for transmission."""
        return self.to_frame().to_bytes()

    @classmethod
    def from_frame(cls: type[PacketT], frame: Frame) -> PacketT:
        """Check packet type and payload size, then unpack message fields."""
        if frame.packet_type != cls.PACKET_TYPE:
            raise ProtocolError(
                f"expected {cls.PACKET_TYPE.name}, got type "
                f"0x{frame.packet_type:04x}"
            )
        if len(frame.payload) != cls.STRUCT.size:
            raise ProtocolError(
                f"{cls.PACKET_TYPE.name} payload is {len(frame.payload)} "
                f"bytes; expected {cls.STRUCT.size}"
            )
        return cls(*cls.STRUCT.unpack(frame.payload))


@dataclass(frozen=True, slots=True)
class OperationModePacket(FixedPacket):
    """Select client operation mode.

    Matches ``struct cs_protocol_operation_mode_frame_t``. ``mode`` is an
    :class:`OperationMode` value. Payload size is 1 byte; frame size is 13.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.SET_OPERATION_MODE
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<B")
    mode: int


@dataclass(frozen=True, slots=True)
class PeerDataPacket(FixedPacket):
    """Select RAS real-time (0) or initiator-only (1) reflector data."""

    PACKET_TYPE: ClassVar[PacketType] = PacketType.SET_PEER_DATA
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<B")
    peer_data: int


T_PM_DEFAULT_US = 10
"""Preferred T_PM without ``SET_T_PM`` (the controller's own preference)."""
T_PM_MANDATORY_US = 40
"""Mandatory T_PM duration in the Bluetooth Core Specification."""
T_PM_VALUES_US = (10, 20, 40)


@dataclass(frozen=True, slots=True)
class TpmPacket(FixedPacket):
    """Preferred phase measurement period T_PM of the CS initiator, in microseconds.

    The firmware accepts only 20 and 40: 10 us is expressed by omitting the packet.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.SET_T_PM
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<B")
    t_pm_us: int


class LogLevel(IntEnum):
    """Consumer levels used by ``SET_LOG_CONFIG`` and ``app_log``."""

    OFF = 0
    ERROR = 1
    WARNING = 2
    INFO = 3
    DEBUG = 4


LOG_CONSOLE_LEVEL_DEFAULT = LogLevel.INFO
LOG_PROTOCOL_LEVEL_DEFAULT = LogLevel.WARNING


@dataclass(frozen=True, slots=True)
class LogConfigPacket(FixedPacket):
    """Configure the client's console and host-protocol log consumers."""

    PACKET_TYPE: ClassVar[PacketType] = PacketType.SET_LOG_CONFIG
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<BB")
    console_level: int
    protocol_level: int

    def __post_init__(self) -> None:
        if (isinstance(self.console_level, bool) or isinstance(self.protocol_level, bool) or
                not isinstance(self.console_level, int) or not isinstance(self.protocol_level, int) or
                not 0 <= self.console_level <= int(LogLevel.DEBUG) or
                not 0 <= self.protocol_level <= int(LogLevel.DEBUG)):
            raise ProtocolError("log levels must be integers from 0 (off) through 4 (debug)")
        object.__setattr__(self, "console_level", int(self.console_level))
        object.__setattr__(self, "protocol_level", int(self.protocol_level))

    @property
    def is_default(self) -> bool:
        return (self.console_level == int(LOG_CONSOLE_LEVEL_DEFAULT) and
                self.protocol_level == int(LOG_PROTOCOL_LEVEL_DEFAULT))


@dataclass(frozen=True, slots=True)
class CsPeerDataPacket(FixedPacket):
    """Report the reflector-data choice used by a CS initiator."""

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CS_PEER_DATA
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<B")
    peer_data: int


@dataclass(frozen=True, slots=True)
class ConnectionParametersPacket(FixedPacket):
    """Unsolicited negotiated ACL connection parameters and ATT MTU of the current link."""

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CONNECTION_PARAMETERS
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<HHHH")
    LEGACY_STRUCT: ClassVar[struct.Struct] = struct.Struct("<HHH")
    interval: int
    latency: int
    timeout: int
    mtu: int

    @classmethod
    def from_frame(cls, frame: Frame) -> "ConnectionParametersPacket":
        """Decode current reports and legacy 18-byte reports from old captures."""
        if frame.packet_type == cls.PACKET_TYPE and len(frame.payload) == cls.LEGACY_STRUCT.size:
            return cls(*cls.LEGACY_STRUCT.unpack(frame.payload), mtu=0)
        return super().from_frame(frame)


@dataclass(frozen=True, slots=True)
class CsReflectorConfigPacket(FixedPacket):
    """Configure the CS reflector mode.

    Matches ``struct cs_protocol_cs_reflector_config_frame_t``. Fields cover
    GAP role, ACL connection parameters, local CS defaults, and procedure
    parameters. Timing units and encoded enum values are documented in the C
    header. Payload size is 34 bytes; frame size is 46.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.SET_CS_REFLECTOR_CONFIG
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBHHHHBbHHHHIIBBbBBB")
    gap_role: int
    config_id: int
    connection_interval_min: int
    connection_interval_max: int
    connection_latency: int
    connection_timeout: int
    cs_sync_antenna_selection: int
    max_tx_power: int
    max_procedure_len: int
    min_procedure_interval: int
    max_procedure_interval: int
    max_procedure_count: int
    min_subevent_len: int
    max_subevent_len: int
    tone_antenna_config_selection: int
    phy: int
    tx_power_delta: int
    preferred_peer_antenna: int
    snr_control_initiator: int
    snr_control_reflector: int


@dataclass(frozen=True, slots=True)
class CsInitiatorConfigPacket(FixedPacket):
    """Configure the CS initiator mode.

    Matches ``struct cs_protocol_cs_initiator_config_frame_t``. Its first 34
    message bytes have the same field order as the reflector configuration.
    The remaining ``creation_*`` fields describe the CS configuration created
    by the initiator. ``creation_channel_map`` must contain exactly 10 bytes.
    Payload size is 57 bytes; frame size is 69.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.SET_CS_INITIATOR_CONFIG
    STRUCT: ClassVar[struct.Struct] = struct.Struct(
        "<BBHHHHBbHHHHIIBBbBBB7B10s6B"
    )
    gap_role: int
    config_id: int
    connection_interval_min: int
    connection_interval_max: int
    connection_latency: int
    connection_timeout: int
    cs_sync_antenna_selection: int
    max_tx_power: int
    max_procedure_len: int
    min_procedure_interval: int
    max_procedure_interval: int
    max_procedure_count: int
    min_subevent_len: int
    max_subevent_len: int
    tone_antenna_config_selection: int
    phy: int
    tx_power_delta: int
    preferred_peer_antenna: int
    snr_control_initiator: int
    snr_control_reflector: int
    creation_mode: int
    creation_min_main_mode_steps: int
    creation_max_main_mode_steps: int
    creation_main_mode_repetition: int
    creation_mode_0_steps: int
    creation_rtt_type: int
    creation_cs_sync_phy: int
    creation_channel_map: bytes
    creation_channel_map_repetition: int
    creation_channel_selection_type: int
    creation_ch3c_shape: int
    creation_ch3c_jump: int
    creation_cs_enhancements_1: int
    creation_context: int


@dataclass(frozen=True, slots=True)
class RadioTxTestConfigPacket(FixedPacket):
    """Configure a Nordic radio test operation.

    Matches ``struct cs_protocol_radio_tx_test_config_frame_t``. ``test_type``
    selects which channel, sweep, duty-cycle, sleep, and FEM fields apply.
    The application may ignore fields unrelated to that test type. Payload
    size is 25 bytes; frame size is 37.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.SET_RADIO_TX_TEST_CONFIG
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBBbBIBBIBHHIB")
    test_type: int
    phy: int
    channel: int
    txpower: int
    pattern: int
    packet_count: int
    sweep_start_channel: int
    sweep_end_channel: int
    sweep_delay_ms: int
    duty_cycle: int
    tx_time_us: int
    sleep_time_us: int
    fem_ramp_up_time_us: int
    fem_tx_power_control: int


@dataclass(frozen=True, slots=True)
class PeripheralPatternsPacket(FixedPacket):
    """Carry GAP peripheral-name prefixes used by a central.

    Matches ``struct cs_protocol_peripheral_patterns_frame_t``. ``count`` is
    the number of active slots, ``lengths`` is the eight-byte length array,
    and ``patterns`` is the flattened 8-by-32-byte C array. Prefer
    :meth:`from_patterns` when constructing this packet. Payload size is 265
    bytes; frame size is 277.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.SET_PERIPHERAL_PATTERNS
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<B8s256s")
    count: int
    lengths: bytes
    patterns: bytes

    @classmethod
    def from_patterns(cls, patterns: list[str | bytes]) -> "PeripheralPatternsPacket":
        """Encode one to eight UTF-8 or byte prefixes into fixed C slots."""
        if not 1 <= len(patterns) <= 8:
            raise ProtocolError("peripheral pattern count must be 1..8")
        lengths = bytearray(8)
        slots = bytearray(8 * 32)
        for index, pattern in enumerate(patterns):
            encoded = pattern.encode("utf-8") if isinstance(pattern, str) else bytes(pattern)
            if not 1 <= len(encoded) <= 32 or b"\0" in encoded:
                raise ProtocolError("each peripheral pattern must be 1..32 bytes without NUL")
            lengths[index] = len(encoded)
            slots[index * 32 : index * 32 + len(encoded)] = encoded
        return cls(len(patterns), bytes(lengths), bytes(slots))

    def names(self) -> list[str]:
        """Decode active prefix slots as UTF-8, replacing invalid sequences."""
        return [
            self.patterns[index * 32 : index * 32 + self.lengths[index]].decode(
                "utf-8", errors="replace"
            )
            for index in range(min(self.count, 8))
        ]

    def has_nonzero_padding(self) -> bool:
        """True when a byte after a pattern's length, or in an unused slot, is set.

        Such frames are rejected with ``RejectReason.NONZERO_PADDING`` so equal
        pattern sets always have equal bytes (and equal configuration CRCs).
        """
        count = min(self.count, 8)
        for index in range(8):
            length = self.lengths[index] if index < count else 0
            if index >= count and self.lengths[index]:
                return True
            if any(self.patterns[index * 32 + min(length, 32) : (index + 1) * 32]):
                return True
        return False


@dataclass(frozen=True, slots=True)
class DeviceNamePacket(FixedPacket):
    """Local Bluetooth name: length + 32 padded UTF-8 bytes (45-byte frame)."""
    PACKET_TYPE: ClassVar[PacketType] = PacketType.SET_DEVICE_NAME
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<B32s")
    length: int
    name: bytes

    def __post_init__(self):
        if not 1 <= self.length <= 32 or len(self.name) != 32:
            raise ProtocolError("Bluetooth name must be 1–32 UTF-8 bytes")
        if any(self.name[self.length:]) or b"\0" in self.name[:self.length]:
            raise ProtocolError("Bluetooth name contains NUL or nonzero padding")
        try:
            self.name[:self.length].decode("utf-8")
        except UnicodeDecodeError as error:
            raise ProtocolError("Bluetooth name must be valid UTF-8") from error

    @classmethod
    def from_name(cls, name):
        try:
            data = name.encode("utf-8")
        except (AttributeError, UnicodeEncodeError) as error:
            raise ProtocolError("Bluetooth name must be valid UTF-8 text") from error
        return cls(len(data), data.ljust(32, b"\0"))

    def text(self):
        return self.name[:self.length].decode("utf-8")


@dataclass(frozen=True, slots=True)
class ApplyConfigPacket(FixedPacket):
    """Request application of the staged configuration.

    Matches ``struct cs_protocol_apply_config_frame_t`` and has no message
    fields. Its complete serialized frame is therefore 12 bytes.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.APPLY_CONFIG
    STRUCT: ClassVar[struct.Struct] = struct.Struct("")


@dataclass(frozen=True, slots=True)
class ConnectPacket(FixedPacket):
    """Open a host session.

    Matches ``struct cs_protocol_connect_frame_t``. Payload size is 2 bytes;
    frame size is 14.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CONNECT
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<H")
    protocol_version: int = PROTOCOL_VERSION


@dataclass(frozen=True, slots=True)
class StartPacket(FixedPacket):
    """Start the applied configuration.

    Matches ``struct cs_protocol_start_frame_t``. ``config_crc32`` is the CRC
    of the configuration the host expects to run. Payload size is 4 bytes;
    frame size is 16.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.START
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<I")
    config_crc32: int


@dataclass(frozen=True, slots=True)
class StopPacket(FixedPacket):
    """Disable CS procedures or stop the radio test. Frame size is 12."""

    PACKET_TYPE: ClassVar[PacketType] = PacketType.STOP
    STRUCT: ClassVar[struct.Struct] = struct.Struct("")


@dataclass(frozen=True, slots=True)
class CloseSessionPacket(FixedPacket):
    """End the host session; the link and a running test are unaffected. Frame size is 12."""

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CLOSE_SESSION
    STRUCT: ClassVar[struct.Struct] = struct.Struct("")


@dataclass(frozen=True, slots=True)
class GetConfigPacket(FixedPacket):
    """Request the client's applied configuration. Frame size is 12."""

    PACKET_TYPE: ClassVar[PacketType] = PacketType.GET_CONFIG
    STRUCT: ClassVar[struct.Struct] = struct.Struct("")


@dataclass(frozen=True, slots=True)
class LinkDisconnectPacket(FixedPacket):
    """Disconnect the Bluetooth link and stop scanning/advertising. Frame size is 12."""

    PACKET_TYPE: ClassVar[PacketType] = PacketType.LINK_DISCONNECT
    STRUCT: ClassVar[struct.Struct] = struct.Struct("")


@dataclass(frozen=True, slots=True)
class ScanStartPacket(FixedPacket):
    PACKET_TYPE: ClassVar[PacketType] = PacketType.SCAN_START
    STRUCT: ClassVar[struct.Struct] = struct.Struct("")


@dataclass(frozen=True, slots=True)
class AdvertiseStartPacket(FixedPacket):
    PACKET_TYPE: ClassVar[PacketType] = PacketType.ADVERTISE_START
    STRUCT: ClassVar[struct.Struct] = struct.Struct("")


@dataclass(frozen=True, slots=True)
class PeerConnectPacket(FixedPacket):
    """Select by address/type, never by a potentially duplicate name."""
    PACKET_TYPE: ClassVar[PacketType] = PacketType.PEER_CONNECT
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<B6s")
    address_type: int
    address: bytes

    def __post_init__(self):
        if self.address_type not in (0, 1) or len(self.address) != 6:
            raise ProtocolError("Peer address must have type 0/1 and six bytes")


@dataclass(frozen=True, slots=True)
class ScanResultPacket(FixedPacket):
    """Raw on-air address order; name is up to 254 advertised bytes, zero padded.

    flags: bit 0 connectable, bit 1 complete name (otherwise shortened/absent).
    Reports may update a peer when its scan response supplies the name.
    """
    PACKET_TYPE: ClassVar[PacketType] = PacketType.SCAN_RESULT
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<B6sbBB254s")
    address_type: int
    address: bytes
    rssi_dbm: int
    flags: int
    name_length: int
    name: bytes

    def __post_init__(self):
        if self.address_type not in (0, 1) or len(self.address) != 6:
            raise ProtocolError("Invalid scan address")
        if not 0 <= self.name_length <= 254 or len(self.name) != 254 or any(self.name[self.name_length:]):
            raise ProtocolError("Invalid scan name length or padding")
        if self.flags & ~3:
            raise ProtocolError("Invalid scan flags")

    @property
    def peer_name(self):
        return self.name[:self.name_length].decode("utf-8", errors="replace")

    @property
    def address_text(self):
        return ":".join(f"{b:02X}" for b in reversed(self.address))


@dataclass(frozen=True, slots=True)
class ConnectResponsePacket(FixedPacket):
    """Answer to CONNECT.

    Matches ``struct cs_protocol_connect_response_frame_t``. ``status`` is a
    :class:`ProtocolStatus`, ``supported_modes`` an :class:`OperationModeMask`,
    ``operation_mode`` an :class:`OperationMode` or :data:`OPERATION_MODE_NONE`
    and ``client_state`` a :class:`ClientState`. ``num_antennas_supported``
    is the local board antenna count from its build configuration.
    Payload size is 18 bytes; frame size is 30.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CONNECT_RESPONSE
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<BHBIHBBIBB")
    status: int
    protocol_version: int
    supported_modes: int
    firmware_version: int
    max_frame_size: int
    config_valid: int
    operation_mode: int
    config_crc32: int
    client_state: int
    num_antennas_supported: int


@dataclass(frozen=True, slots=True)
class CommandResponsePacket(FixedPacket):
    """Answer to every host command except CONNECT.

    Matches ``struct cs_protocol_command_response_frame_t``. ``request_type``
    is the answered :class:`PacketType`, ``error`` a negative errno or 0, and
    ``config_crc32`` the applied configuration CRC after the command (0 when
    none). Payload size is 12 bytes; frame size is 24.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.COMMAND_RESPONSE
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<HBBiI")
    request_type: int
    status: int
    reason: int
    error: int
    config_crc32: int


@dataclass(frozen=True, slots=True)
class CsFaeTablePacket(FixedPacket):
    """One remote FAE table read completion event.

    Matches ``struct cs_protocol_cs_fae_table_frame_t``. ``entries`` holds the
    72 signed values in HCI table order; ppm = entry / ``lsb_denominator``.
    Entries are all zero when ``hci_status`` is not 0. Payload size is 74
    bytes; frame size is 86.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CS_FAE_TABLE
    STRUCT: ClassVar[struct.Struct] = struct.Struct(f"<BB{FAE_TABLE_ENTRIES}b")
    hci_status: int
    lsb_denominator: int
    entries: tuple[int, ...] = (0,) * FAE_TABLE_ENTRIES

    def _values(self) -> tuple[Any, ...]:
        if len(self.entries) != FAE_TABLE_ENTRIES:
            raise ProtocolError(
                f"FAE table needs {FAE_TABLE_ENTRIES} entries, got {len(self.entries)}"
            )
        return (self.hci_status, self.lsb_denominator, *self.entries)

    @classmethod
    def from_frame(cls, frame: Frame) -> "CsFaeTablePacket":
        """Check packet type and payload size, then unpack status, scale and entries."""
        if frame.packet_type != cls.PACKET_TYPE or len(frame.payload) != cls.STRUCT.size:
            raise ProtocolError(
                f"expected {cls.PACKET_TYPE.name} with a {cls.STRUCT.size}-byte payload, "
                f"got type 0x{frame.packet_type:04x} with {len(frame.payload)} bytes"
            )
        hci_status, lsb_denominator, *entries = cls.STRUCT.unpack(frame.payload)
        return cls(hci_status, lsb_denominator, tuple(entries))


@dataclass(frozen=True, slots=True)
class ClientStatePacket(FixedPacket):
    """Unsolicited client state change.

    Matches ``struct cs_protocol_client_state_frame_t``. Payload size is 8
    bytes; frame size is 20. ``error`` is a negative Zephyr errno when the
    change ended an operation abnormally (``INTERRUPTED`` or ``ERROR``), else 0.
    Protocol version 2 frames (4-byte payload, no ``error``) still decode, so
    older recordings stay readable.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CLIENT_STATE
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBBBi")
    LEGACY_STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBBB")
    state: int
    operation_mode: int
    reason: int = RejectReason.NONE
    hci_status: int = 0
    error: int = 0

    @classmethod
    def from_frame(cls, frame: Frame) -> "ClientStatePacket":
        """Decode the current frame or a protocol version 2 frame without ``error``."""
        if frame.packet_type == cls.PACKET_TYPE and len(frame.payload) == cls.LEGACY_STRUCT.size:
            return cls(*cls.LEGACY_STRUCT.unpack(frame.payload))
        return super(ClientStatePacket, cls).from_frame(frame)


@dataclass(frozen=True, slots=True)
class RasDataLostPacket(FixedPacket):
    """Unsolicited: real-time RAS data of one procedure was not received.

    Matches ``struct cs_protocol_ras_data_lost_frame_t``. ``error`` is the
    negative errno from the RAS data callback. Payload size is 4 bytes; frame
    size is 16.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.RAS_DATA_LOST
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<Hh")
    ranging_counter: int
    error: int


@dataclass(frozen=True, slots=True)
class CsProceduresCompletePacket(FixedPacket):
    """Unsolicited: the run's CS procedures ended on their own (0x000E, protocol 0x0006).

    Matches ``struct cs_protocol_cs_procedures_complete_frame_t``. Sent by the
    CS initiator when its controller completed ``max_procedure_count``, right
    before CLIENT_STATE(STOPPED, TEST_COMPLETE). ``procedures_completed`` counts
    the run's procedures whose done status was complete. Payload size is 2
    bytes; frame size is 14.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CS_PROCEDURES_COMPLETE
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<H")
    procedures_completed: int


@dataclass(frozen=True, slots=True)
class RadioTestStatsPacket(FixedPacket):
    """Radio RX test statistics (0x000C): 10-byte payload, 22-byte frame.

    Matches ``struct cs_protocol_radio_test_stats_frame_t``. Counters are
    cumulative across channels since START, modulo 2**32. packets_received
    counts CRC-valid packets; crc_errors counts failed packets. rssi_dbm is the
    latest packet since the previous report, or 127 when none; channel is that
    packet's channel, or the tuned one. The client sends a baseline after the
    START response, periodic reports and a final report before STOPPED.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.RADIO_TEST_STATS
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<IIbB")
    packets_received: int
    crc_errors: int
    rssi_dbm: int
    channel: int


@dataclass(frozen=True, slots=True)
class CsCapabilitiesPacket(FixedPacket):
    """Report local or remote controller CS capabilities.

    Matches ``struct cs_protocol_cs_capabilities_frame_t`` field for field.
    Boolean capabilities remain integer bytes because that is their C wire
    representation. ``source`` is a :class:`CapabilitiesSource`;
    ``conn_index`` is ``CAPABILITIES_CONN_NONE`` for local reports. Payload
    size is 37 bytes; frame size is 49.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CS_CAPABILITIES
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBBH18BHHHHBBHBB")
    source: int
    conn_index: int
    num_config_supported: int
    max_consecutive_procedures_supported: int
    num_antennas_supported: int
    max_antenna_paths_supported: int
    initiator_supported: int
    reflector_supported: int
    mode_3_supported: int
    rtt_aa_only_precision: int
    rtt_sounding_precision: int
    rtt_random_payload_precision: int
    rtt_aa_only_n: int
    rtt_sounding_n: int
    rtt_random_payload_n: int
    phase_based_nadm_sounding_supported: int
    phase_based_nadm_random_supported: int
    cs_sync_2m_phy_supported: int
    cs_sync_2m_2bt_phy_supported: int
    cs_without_fae_supported: int
    chsel_alg_3c_supported: int
    pbr_from_rtt_sounding_seq_supported: int
    t_ip1_times_supported: int
    t_ip2_times_supported: int
    t_fcs_times_supported: int
    t_pm_times_supported: int
    t_sw_time: int
    tx_snr_capability: int
    t_ip2_ipt_times_supported: int
    t_sw_ipt_time_supported: int
    cs_ipt_reflector_supported: int


@dataclass(frozen=True, slots=True)
class CsConfigurationPacket(FixedPacket):
    """Report a controller-completed CS configuration.

    Matches ``struct cs_protocol_cs_configuration_frame_t``. ``channel_map``
    is the raw 10-byte, 80-bit channel map in C field order. Payload size is
    28 bytes; frame size is 40.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CS_CONFIGURATION
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<18B10s")
    id: int
    mode: int
    min_main_mode_steps: int
    max_main_mode_steps: int
    main_mode_repetition: int
    mode_0_steps: int
    role: int
    rtt_type: int
    cs_sync_phy: int
    channel_map_repetition: int
    channel_selection_type: int
    ch3c_shape: int
    ch3c_jump: int
    cs_enhancements_1: int
    t_ip1_time_us: int
    t_ip2_time_us: int
    t_fcs_time_us: int
    t_pm_time_us: int
    channel_map: bytes


@dataclass(frozen=True, slots=True)
class CsProcedureEnableCompletePacket(FixedPacket):
    """Report the controller's selected CS procedure parameters.

    Matches ``struct cs_protocol_cs_procedure_enable_complete_frame_t``.
    Payload size is 19 bytes; frame size is 31.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CS_PROCEDURE_ENABLE_COMPLETE
    STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBBbIBHHHHH")
    config_id: int
    state: int
    tone_antenna_config_selection: int
    selected_tx_power: int
    subevent_len: int
    subevents_per_event: int
    subevent_interval: int
    event_interval: int
    procedure_interval: int
    procedure_count: int
    max_procedure_len: int


@dataclass(frozen=True, slots=True)
class CsTone:
    """One eight-byte ``cs_protocol_cs_tone_decoded_t`` record.

    ``i`` and ``q`` are signed phase-correction components. ``antenna_path``,
    ``quality``, and ``extension`` retain the controller-derived wire values;
    ``reserved`` is normally zero.
    """

    STRUCT: ClassVar[struct.Struct] = struct.Struct("<hhBBBB")
    i: int
    q: int
    antenna_path: int
    quality: int
    extension: int
    reserved: int = 0

    def to_bytes(self) -> bytes:
        """Serialize this tone without any frame header or footer."""
        return self.STRUCT.pack(*self._values())

    def _values(self) -> tuple[int, ...]:
        return tuple(getattr(self, field.name) for field in fields(self))

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> tuple["CsTone", int]:
        """Decode one tone and return it with the first unread offset."""
        if len(data) - offset < cls.STRUCT.size:
            raise ProtocolError("truncated CS tone")
        return cls(*cls.STRUCT.unpack_from(data, offset)), offset + cls.STRUCT.size


@dataclass(frozen=True, slots=True)
class CsStep:
    """One variable-size decoded CS step record.

    Matches ``struct cs_protocol_cs_step_decoded_t``. The fixed portion is 22
    bytes and stores ``num_tones`` on the wire. Python derives that count from
    ``tones`` and appends each eight-byte :class:`CsTone` record.
    """

    STRUCT: ClassVar[struct.Struct] = struct.Struct("<BBBBBbBBHhhhhhBB")
    mode: int
    channel: int
    flags: int
    aa_quality: int
    bit_errors: int
    rssi: int
    antenna: int
    nadm: int
    measured_freq_offset: int
    time_difference: int
    pct1_i: int
    pct1_q: int
    pct2_i: int
    pct2_q: int
    antenna_permutation_index: int
    tones: tuple[CsTone, ...] = ()

    def to_bytes(self) -> bytes:
        """Serialize the fixed step fields, derived tone count, and tones."""
        values = tuple(
            getattr(self, field.name) for field in fields(self) if field.name != "tones"
        )
        header = self.STRUCT.pack(*values, len(self.tones))
        return header + b"".join(tone.to_bytes() for tone in self.tones)

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> tuple["CsStep", int]:
        """Decode one complete step and return the first unread offset."""
        if len(data) - offset < cls.STRUCT.size:
            raise ProtocolError("truncated CS step header")
        values = cls.STRUCT.unpack_from(data, offset)
        offset += cls.STRUCT.size
        tones: list[CsTone] = []
        for _ in range(values[-1]):
            tone, offset = CsTone.from_bytes(data, offset)
            tones.append(tone)
        return cls(*values[:-1], tuple(tones)), offset


@dataclass(frozen=True, slots=True)
class CsSubeventResultPacket:
    """Common codec for initiator and reflector subevent reports.

    The 15-byte fixed payload prefix matches both C subevent frame structs.
    Python derives ``num_steps_reported`` from ``steps`` and serializes each
    variable-size :class:`CsStep` immediately afterward. Concrete subclasses
    provide the initiator or reflector packet type.
    """

    STRUCT: ClassVar[struct.Struct] = struct.Struct("<BHHHbBBBBBBB")
    PACKET_TYPE: ClassVar[PacketType]
    config_id: int
    start_acl_conn_event: int
    procedure_counter: int
    frequency_compensation: int
    reference_power_level: int
    procedure_done_status: int
    subevent_done_status: int
    procedure_abort_reason: int
    subevent_abort_reason: int
    num_antenna_paths: int
    abort_step: int
    steps: tuple[CsStep, ...] = ()

    def to_frame(self) -> Frame:
        """Pack the result prefix, derived step count, and step records."""
        values = tuple(
            getattr(self, field.name) for field in fields(self) if field.name != "steps"
        )
        payload = self.STRUCT.pack(*values[:-1], len(self.steps), values[-1])
        payload += b"".join(step.to_bytes() for step in self.steps)
        return Frame(self.PACKET_TYPE, payload)

    def to_bytes(self) -> bytes:
        """Return the complete serialized subevent frame."""
        return self.to_frame().to_bytes()

    @classmethod
    def from_frame(cls, frame: Frame) -> "CsSubeventResultPacket":
        """Decode exactly the declared number of steps and reject trailing data."""
        if frame.packet_type != cls.PACKET_TYPE:
            raise ProtocolError(
                f"expected {cls.PACKET_TYPE.name}, got 0x{frame.packet_type:04x}"
            )
        if len(frame.payload) < cls.STRUCT.size:
            raise ProtocolError("truncated CS subevent result")
        values = cls.STRUCT.unpack_from(frame.payload)
        num_steps = values[-2]
        offset = cls.STRUCT.size
        steps: list[CsStep] = []
        for _ in range(num_steps):
            step, offset = CsStep.from_bytes(frame.payload, offset)
            steps.append(step)
        if offset != len(frame.payload):
            raise ProtocolError(
                f"CS subevent contains {len(frame.payload) - offset} trailing bytes"
            )
        return cls(*values[:-2], values[-1], tuple(steps))


@dataclass(frozen=True, slots=True)
class CsInitiatorSubeventResultPacket(CsSubeventResultPacket):
    """Initiator result matching ``cs_protocol_cs_initiator_subevent_result_frame_t``."""

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CS_INITIATOR_SUBEVENT_RESULT


@dataclass(frozen=True, slots=True)
class CsReflectorSubeventResultPacket(CsSubeventResultPacket):
    """Reflector result matching ``cs_protocol_cs_reflector_subevent_result_frame_t``."""

    PACKET_TYPE: ClassVar[PacketType] = PacketType.CS_REFLECTOR_SUBEVENT_RESULT


@dataclass(frozen=True, slots=True)
class LogMessagePacket:
    """Variable-length diagnostic text matching ``cs_protocol_log_message_frame_t``.

    ``message`` contains the exact payload bytes and has no terminating NUL.
    Decode it explicitly using the desired error policy, or use
    :func:`packet_to_dict` for replacement-character UTF-8 output.
    """

    PACKET_TYPE: ClassVar[PacketType] = PacketType.LOG_MESSAGE
    message: bytes

    def to_frame(self) -> Frame:
        """Return a generic frame containing the raw message bytes."""
        return Frame(self.PACKET_TYPE, bytes(self.message))

    def to_bytes(self) -> bytes:
        """Return the complete serialized log frame."""
        return self.to_frame().to_bytes()

    @classmethod
    def from_frame(cls, frame: Frame) -> "LogMessagePacket":
        """Decode a log frame without altering or interpreting its bytes."""
        if frame.packet_type != cls.PACKET_TYPE:
            raise ProtocolError(
                f"expected LOG_MESSAGE, got 0x{frame.packet_type:04x}"
            )
        return cls(frame.payload)


PACKET_CLASSES: dict[PacketType, type[Any]] = {
    packet_class.PACKET_TYPE: packet_class
    for packet_class in (
        OperationModePacket,
        PeerDataPacket,
        CsInitiatorConfigPacket,
        CsReflectorConfigPacket,
        RadioTxTestConfigPacket,
        PeripheralPatternsPacket,
        LogConfigPacket,
        TpmPacket,
        DeviceNamePacket, ScanStartPacket, AdvertiseStartPacket, PeerConnectPacket, ScanResultPacket,
        ApplyConfigPacket,
        ConnectPacket,
        StartPacket,
        StopPacket,
        CloseSessionPacket,
        GetConfigPacket,
        LinkDisconnectPacket,
        CsCapabilitiesPacket,
        CsConfigurationPacket,
        CsProcedureEnableCompletePacket,
        CsInitiatorSubeventResultPacket,
        CsReflectorSubeventResultPacket,
        LogMessagePacket,
        ConnectResponsePacket,
        CommandResponsePacket,
        CsFaeTablePacket,
        ClientStatePacket,
        RasDataLostPacket,
        RadioTestStatsPacket,
        CsProceduresCompletePacket,
        CsPeerDataPacket,
        ConnectionParametersPacket,
    )
}


def _enum_name(enum: type[IntEnum], value: int) -> str:
    """Lower-case name of an enum value, or ``unknown_0x..`` for values not defined."""
    try:
        return enum(value).name.lower()
    except ValueError:
        return f"unknown_0x{value:02x}"


def _mode_name(value: int) -> str:
    return "none" if value == OPERATION_MODE_NONE else _enum_name(OperationMode, value)


# Zephyr / picolibc errno values (not the host's errno module, whose numbers differ).
ZEPHYR_ERRNO_NAMES: dict[int, str] = {
    5: "EIO", 12: "ENOMEM", 13: "EACCES", 16: "EBUSY", 19: "ENODEV", 22: "EINVAL", 34: "ERANGE",
    61: "ENODATA", 88: "ENOSYS", 116: "ETIMEDOUT", 120: "EALREADY", 128: "ENOTCONN",
    134: "ENOTSUP", 140: "ECANCELED",
}


def error_name(error: int) -> str:
    """Name of a negative Zephyr errno, e.g. ``-ECANCELED``; ``0`` for no error."""
    if error == 0:
        return "0"
    name = ZEPHYR_ERRNO_NAMES.get(abs(error))
    return f"{'-' if error < 0 else ''}{name}" if name else str(error)


def decode_packet(frame: Frame) -> Any:
    """Decode a generic frame into its matching packet dataclass."""
    try:
        packet_type = PacketType(frame.packet_type)
    except ValueError:
        return frame
    packet_class = PACKET_CLASSES.get(packet_type)
    if packet_class is None:
        raise ProtocolError(f"unsupported packet type {packet_type.name}")
    return packet_class.from_frame(frame)


def packet_to_dict(packet: Any) -> dict[str, Any]:
    """Convert a packet dataclass into JSON-safe data."""
    if isinstance(packet, Frame):
        return {
            "packet_type": packet.packet_type,
            "packet_name": f"unknown_0x{packet.packet_type:04x}",
            "payload": packet.payload.hex(),
        }
    if not is_dataclass(packet):
        raise TypeError("packet must be a dataclass instance")

    def convert(value: Any) -> Any:
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, IntEnum):
            return int(value)
        if isinstance(value, tuple):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    result = convert(asdict(packet))
    result["packet_type"] = int(packet.PACKET_TYPE)
    result["packet_name"] = packet.PACKET_TYPE.name.lower()
    if isinstance(packet, ScanResultPacket):
        result["peer_name"] = packet.peer_name
        result["address_text"] = packet.address_text
    if isinstance(packet, PeripheralPatternsPacket):
        result["peripheral_names"] = packet.names()
    if isinstance(packet, LogMessagePacket):
        result["text"] = packet.message.decode("utf-8", errors="replace")
    if isinstance(packet, ConnectResponsePacket):
        result["status_name"] = _enum_name(ProtocolStatus, packet.status)
        result["supported_mode_names"] = [
            mode.name.lower() for mode in OperationModeMask(packet.supported_modes & 0x07).modes()
        ]
        result["operation_mode_name"] = _mode_name(packet.operation_mode)
        result["client_state_name"] = _enum_name(ClientState, packet.client_state)
    if isinstance(packet, CommandResponsePacket):
        result["request_name"] = _enum_name(PacketType, packet.request_type)
        result["status_name"] = _enum_name(ProtocolStatus, packet.status)
        result["reason_name"] = _enum_name(RejectReason, packet.reason)
        result["error_name"] = error_name(packet.error)
    if isinstance(packet, ClientStatePacket):
        result["state_name"] = _enum_name(ClientState, packet.state)
        result["operation_mode_name"] = _mode_name(packet.operation_mode)
        result["reason_name"] = _enum_name(RejectReason, packet.reason)
        result["error_name"] = error_name(packet.error)
    return result


PACKET_NAMES: dict[str, type[Any]] = {
    packet_type.name.lower().replace("set_", ""): packet_class
    for packet_type, packet_class in PACKET_CLASSES.items()
}
PACKET_NAMES.update(
    {packet_type.name.lower(): packet_class for packet_type, packet_class in PACKET_CLASSES.items()}
)


def packet_from_dict(name: str, values: dict[str, Any]) -> Any:
    """Build a transmit packet from a JSON-compatible mapping."""
    normalized = name.lower().replace("-", "_")
    try:
        packet_class = PACKET_NAMES[normalized]
    except KeyError as error:
        raise ProtocolError(f"unknown packet name {name!r}") from error

    values = dict(values)
    if packet_class is PeripheralPatternsPacket and "peripheral_names" in values:
        return packet_class.from_patterns(values.pop("peripheral_names"))
    if packet_class is LogMessagePacket and "text" in values:
        return packet_class(values.pop("text").encode("utf-8"))
    if issubclass(packet_class, CsSubeventResultPacket) and "steps" in values:
        decoded_steps = []
        for step_values in values["steps"]:
            step_values = dict(step_values)
            step_values["tones"] = tuple(
                tone if isinstance(tone, CsTone) else CsTone(**tone)
                for tone in step_values.get("tones", ())
            )
            decoded_steps.append(CsStep(**step_values))
        values["steps"] = tuple(decoded_steps)
    if packet_class is CsFaeTablePacket and "entries" in values:
        values["entries"] = tuple(values["entries"])

    byte_fields = {
        "name",
        "address",
        "creation_channel_map",
        "channel_map",
        "lengths",
        "patterns",
        "message",
    }
    for key in byte_fields & values.keys():
        value = values[key]
        if isinstance(value, str):
            values[key] = bytes.fromhex(value)
        elif isinstance(value, list):
            values[key] = bytes(value)
    try:
        return packet_class(**values)
    except (TypeError, ValueError) as error:
        raise ProtocolError(str(error)) from error
