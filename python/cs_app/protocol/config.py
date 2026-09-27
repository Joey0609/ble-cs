"""Client configuration as held by the client, and its configuration CRC.

The client holds one applied configuration: the operation mode, the matching
configuration packet and, for CS modes, optionally the peripheral patterns.
``config_crc32`` is CRC-32/IEEE (the framing CRC) over the concatenated
payloads, without headers or footers, in this order:

1. ``SET_OPERATION_MODE`` payload (1 byte)
2. ``SET_CS_INITIATOR_CONFIG``, ``SET_CS_REFLECTOR_CONFIG`` or
   ``SET_RADIO_TX_TEST_CONFIG`` payload
3. ``SET_PERIPHERAL_PATTERNS`` payload, only if patterns are part of the
   configuration
4. Optional ``SET_DEVICE_NAME`` payload, for CS modes only.
5. Optional ``SET_PEER_DATA`` payload, for CS initiator mode only.
6. Optional ``SET_T_PM`` payload, for CS initiator mode only, when T_PM is not 10 us.
7. Optional ``SET_LOG_CONFIG`` payload, when the levels are not the defaults.

Pattern packets with non-zero bytes after a pattern's length, or in unused
slots, are refused so that equal pattern sets always give equal CRCs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import zlib

from .frame import ProtocolError
from .packets import (
    CsInitiatorConfigPacket,
    CsReflectorConfigPacket,
    OperationMode,
    OperationModePacket,
    PeripheralPatternsPacket,
    DeviceNamePacket,
    PeerDataPacket,
    LogConfigPacket,
    RadioTxTestConfigPacket,
    T_PM_DEFAULT_US,
    T_PM_VALUES_US,
    TpmPacket,
)

ConfigPacket = CsInitiatorConfigPacket | CsReflectorConfigPacket | RadioTxTestConfigPacket

CONFIG_CLASSES: dict[OperationMode, type[Any]] = {
    OperationMode.CS_INITIATOR: CsInitiatorConfigPacket,
    OperationMode.CS_REFLECTOR: CsReflectorConfigPacket,
    OperationMode.RADIO_TX_TEST: RadioTxTestConfigPacket,
}


@dataclass(frozen=True, slots=True, init=False)
class ClientConfig:
    """One complete client configuration.

    Construction checks that ``config`` matches ``mode``, that patterns are
    only given for CS modes and that pattern padding is zero. Field value
    ranges are not checked here.
    """

    mode: OperationMode
    config: ConfigPacket
    patterns: PeripheralPatternsPacket | None = None
    device_name: DeviceNamePacket | None = None
    peer_data: int = 0
    log: LogConfigPacket | None = None
    t_pm: int = T_PM_DEFAULT_US

    def __init__(self, mode, config, patterns=None, device_name=None, peer_data=0,
                 log=None, *, log_config=None, t_pm=T_PM_DEFAULT_US):
        """Create a configuration; ``log_config`` is accepted as a descriptive alias for ``log``."""
        if log is not None and log_config is not None:
            raise ProtocolError("specify either log or log_config, not both")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "patterns", patterns)
        object.__setattr__(self, "device_name", device_name)
        object.__setattr__(self, "peer_data", peer_data)
        object.__setattr__(self, "log", log if log is not None else log_config)
        object.__setattr__(self, "t_pm", t_pm)
        self.__post_init__()

    def __post_init__(self) -> None:
        try:
            mode = OperationMode(self.mode)
        except ValueError as error:
            raise ProtocolError(f"invalid operation mode {self.mode!r}") from error
        object.__setattr__(self, "mode", mode)
        expected = CONFIG_CLASSES[mode]
        if type(self.config) is not expected:
            raise ProtocolError(
                f"{mode.name} needs {expected.__name__}, got {type(self.config).__name__}"
            )
        if self.device_name is not None:
            if mode == OperationMode.RADIO_TX_TEST or not isinstance(self.device_name, DeviceNamePacket):
                raise ProtocolError("Bluetooth device name is only valid in CS modes")
        if self.patterns is not None:
            if mode == OperationMode.RADIO_TX_TEST:
                raise ProtocolError("peripheral patterns are only valid in CS modes")
            if not isinstance(self.patterns, PeripheralPatternsPacket):
                raise ProtocolError("patterns must be a PeripheralPatternsPacket")
            if self.patterns.has_nonzero_padding():
                raise ProtocolError("peripheral patterns have non-zero padding")
        if type(self.peer_data) is not int or self.peer_data not in (0, 1):
            raise ProtocolError("peer_data must be 0 or 1")
        if self.peer_data and (mode != OperationMode.CS_INITIATOR or not
                               (getattr(self.config, "creation_cs_enhancements_1", 0) & 0x01)):
            raise ProtocolError("initiator-only peer data requires IPT in CS initiator mode")
        if type(self.t_pm) is not int or self.t_pm not in T_PM_VALUES_US:
            raise ProtocolError("t_pm must be 10, 20 or 40 us")
        if self.t_pm != T_PM_DEFAULT_US and mode != OperationMode.CS_INITIATOR:
            raise ProtocolError("a preferred T_PM is only valid in CS initiator mode")
        if self.log is not None:
            if not isinstance(self.log, LogConfigPacket):
                raise ProtocolError("log must be a LogConfigPacket")
            # The firmware omits the defaults, giving each configuration one
            # canonical wire representation and preserving older CRCs.
            if self.log.is_default:
                object.__setattr__(self, "log", None)

    def packets(self) -> list[Any]:
        """Configuration packets in send order, without ``APPLY_CONFIG``."""
        packets: list[Any] = [OperationModePacket(int(self.mode)), self.config]
        if self.patterns is not None:
            packets.append(self.patterns)
        if self.device_name is not None:
            packets.append(self.device_name)
        if self.peer_data:
            packets.append(PeerDataPacket(self.peer_data))
        if self.t_pm != T_PM_DEFAULT_US:
            packets.append(TpmPacket(self.t_pm))
        if self.log is not None:
            packets.append(self.log)
        return packets

    def payloads(self) -> bytes:
        """Concatenated packet payloads: the exact CRC input."""
        return b"".join(packet.to_frame().payload for packet in self.packets())

    def crc32(self) -> int:
        """Configuration CRC, as reported in ``config_crc32``."""
        return zlib.crc32(self.payloads()) & 0xFFFFFFFF

    @classmethod
    def from_packets(cls, packets: Iterable[Any]) -> "ClientConfig":
        """Build a configuration from received ``GET_CONFIG`` reply packets.

        Expects ``OperationModePacket``, the matching configuration packet and
        optionally ``PeripheralPatternsPacket``, then optionally ``DeviceNamePacket``,
        ``PeerDataPacket``, ``TpmPacket`` and ``LogConfigPacket``.
        """
        packets = list(packets)
        log = packets.pop() if packets and isinstance(packets[-1], LogConfigPacket) else None
        t_pm = packets.pop().t_pm_us if packets and isinstance(packets[-1], TpmPacket) else T_PM_DEFAULT_US
        peer_data = packets.pop().peer_data if packets and isinstance(packets[-1], PeerDataPacket) else 0
        device_name = packets.pop() if packets and isinstance(packets[-1], DeviceNamePacket) else None
        if len(packets) not in (2, 3):
            raise ProtocolError(
                f"a configuration has 2 or 3 packets after optional fields, got {len(packets)}"
            )
        if not isinstance(packets[0], OperationModePacket):
            raise ProtocolError(
                f"configuration must start with OperationModePacket, got "
                f"{type(packets[0]).__name__}"
            )
        patterns = packets[2] if len(packets) == 3 else None
        if patterns is not None and not isinstance(patterns, PeripheralPatternsPacket):
            raise ProtocolError(
                f"third configuration packet must be PeripheralPatternsPacket, got "
                f"{type(patterns).__name__}"
            )
        return cls(packets[0].mode, packets[1], patterns, device_name, peer_data, log, t_pm=t_pm)

    @property
    def log_config(self) -> LogConfigPacket | None:
        """Compatibility/descriptive alias for the optional log configuration."""
        return self.log
