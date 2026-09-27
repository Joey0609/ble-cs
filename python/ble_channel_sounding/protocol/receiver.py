"""Receive, validate, and decode CS protocol frames."""

from __future__ import annotations

from typing import Any

from .frame import FrameDecoder, ProtocolError
from .packets import decode_packet


class PacketReceiver:
    """Incrementally turn serial bytes into C-matching packet objects.

    One instance retains partial input between :meth:`feed` calls. Valid known
    frame types become packet dataclasses from :mod:`ble_channel_sounding.protocol.packets`;
    unknown types remain generic :class:`ble_channel_sounding.protocol.frame.Frame` instances.
    Framing recovery counters are available through :attr:`frames`.

    A frame that passes framing and CRC checks but whose payload does not
    match its packet type is skipped and recorded in :attr:`packet_errors`;
    one bad packet never stops the stream.
    """

    def __init__(self) -> None:
        self.frames = FrameDecoder()
        self.packet_errors: list[ProtocolError] = []

    def feed(self, data: bytes) -> list[Any]:
        """Consume one byte chunk and return all complete decoded packets."""
        packets = []
        for frame in self.frames.feed(data):
            try:
                packets.append(decode_packet(frame))
            except ProtocolError as error:
                self.packet_errors.append(error)
        return packets
