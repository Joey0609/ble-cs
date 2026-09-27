"""Generic CS protocol framing and incremental stream decoding."""

from __future__ import annotations

from dataclasses import dataclass
import struct
import zlib

START_SYNC = 0x5AA5
END_SYNC = 0xA55A
HEADER = struct.Struct("<HHH")
FOOTER = struct.Struct("<IH")
MIN_FRAME_SIZE = HEADER.size + FOOTER.size
MAX_FRAME_SIZE = 0xFFFF
MAX_PAYLOAD_SIZE = MAX_FRAME_SIZE - MIN_FRAME_SIZE


class ProtocolError(ValueError):
    """Report malformed framing, invalid field widths, or packet layouts."""


@dataclass(frozen=True, slots=True)
class Frame:
    """Generic CS protocol frame.

    ``packet_type`` is the unsigned 16-bit value stored in the C header.
    ``payload`` contains only bytes between the six-byte C header and six-byte
    footer. :meth:`to_bytes` creates the complete wire frame and
    :meth:`from_bytes` validates one complete frame before returning it.

    The computed :attr:`size` includes header and footer. :attr:`crc32` is
    CRC-32/IEEE over the little-endian size, packet type, and payload, matching
    ``cs_protocol_crc32`` in the C implementation.
    """

    packet_type: int
    payload: bytes = b""

    @property
    def size(self) -> int:
        return MIN_FRAME_SIZE + len(self.payload)

    @property
    def crc32(self) -> int:
        body = struct.pack("<HH", self.size, self.packet_type) + self.payload
        return zlib.crc32(body) & 0xFFFFFFFF

    def to_bytes(self) -> bytes:
        """Serialize the frame with sync markers, total size, and CRC."""
        if not 0 <= self.packet_type <= 0xFFFF:
            raise ProtocolError("packet_type must fit in uint16")
        if len(self.payload) > MAX_PAYLOAD_SIZE:
            raise ProtocolError(
                f"payload is {len(self.payload)} bytes; maximum is "
                f"{MAX_PAYLOAD_SIZE}"
            )
        header = HEADER.pack(START_SYNC, self.size, self.packet_type)
        return header + self.payload + FOOTER.pack(self.crc32, END_SYNC)

    @classmethod
    def from_bytes(cls, data: bytes | bytearray | memoryview) -> "Frame":
        """Validate and decode exactly one complete frame.

        Raises:
            ProtocolError: If size, either sync marker, or CRC is invalid.
        """
        view = memoryview(data)
        if len(view) < MIN_FRAME_SIZE:
            raise ProtocolError(
                f"frame is {len(view)} bytes; minimum is {MIN_FRAME_SIZE}"
            )
        sync, size, packet_type = HEADER.unpack_from(view)
        if sync != START_SYNC:
            raise ProtocolError(
                f"invalid start sync 0x{sync:04x}; expected 0x{START_SYNC:04x}"
            )
        if size != len(view):
            raise ProtocolError(
                f"header size is {size}, received {len(view)} bytes"
            )
        received_crc, end_sync = FOOTER.unpack_from(view, size - FOOTER.size)
        if end_sync != END_SYNC:
            raise ProtocolError(
                f"invalid end sync 0x{end_sync:04x}; expected 0x{END_SYNC:04x}"
            )
        expected_crc = zlib.crc32(view[2 : size - FOOTER.size]) & 0xFFFFFFFF
        if received_crc != expected_crc:
            raise ProtocolError(
                f"invalid CRC 0x{received_crc:08x}; expected "
                f"0x{expected_crc:08x}"
            )
        return cls(packet_type, bytes(view[HEADER.size : size - FOOTER.size]))


class FrameDecoder:
    """Incrementally extract :class:`Frame` objects from arbitrary chunks.

    Data before the start marker and corrupt frame candidates are discarded
    one byte at a time so decoding can resume at the next valid marker.
    ``discarded_bytes`` and ``invalid_frames`` expose recovery statistics.
    A decoder retains incomplete frame bytes between :meth:`feed` calls.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.discarded_bytes = 0
        self.invalid_frames = 0

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def reset(self) -> None:
        """Discard buffered input and reset recovery counters."""
        self._buffer.clear()
        self.discarded_bytes = 0
        self.invalid_frames = 0

    def feed(self, data: bytes | bytearray | memoryview) -> list[Frame]:
        """Consume a stream chunk and return every complete validated frame."""
        self._buffer.extend(data)
        frames: list[Frame] = []
        sync_bytes = struct.pack("<H", START_SYNC)

        while True:
            start = self._buffer.find(sync_bytes)
            if start < 0:
                keep = 1 if self._buffer[-1:] == sync_bytes[:1] else 0
                self.discarded_bytes += len(self._buffer) - keep
                if keep:
                    self._buffer[:] = self._buffer[-1:]
                else:
                    self._buffer.clear()
                break
            if start:
                del self._buffer[:start]
                self.discarded_bytes += start
            if len(self._buffer) < HEADER.size:
                break

            _, size, _ = HEADER.unpack_from(self._buffer)
            if size < MIN_FRAME_SIZE:
                del self._buffer[0]
                self.discarded_bytes += 1
                self.invalid_frames += 1
                continue
            if len(self._buffer) < size:
                break

            candidate = bytes(self._buffer[:size])
            try:
                frame = Frame.from_bytes(candidate)
            except ProtocolError:
                del self._buffer[0]
                self.discarded_bytes += 1
                self.invalid_frames += 1
                continue
            frames.append(frame)
            del self._buffer[:size]

        return frames
