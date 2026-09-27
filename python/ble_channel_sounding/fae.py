"""Mode-0 frequency actuation error (FAE) table model.

The controller reports a peer's FAE table as 72 signed octets in HCI table
order. Table indices are not CS channel indices: the entries cover the
allowed CS channels 2..22 and 26..76 in ascending order. The client sends
them in ``CS_FAE_TABLE`` frames; this module converts entries to ppm and Hz
using the standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

FAE_TABLE_ENTRIES = 72
FAE_ROW_WIDTH = 8

# Allowed CS channels in table order: 21 below the 2.4 GHz gap, 51 above it.
FAE_CHANNELS: tuple[int, ...] = tuple(range(2, 23)) + tuple(range(26, 77))

# Core v6.3, Vol 6, Part B, 2.4.2.52: signed FAE resolution is 1/32 ppm.
# Used only as the fallback for tables built without a packet; packets supply their own scale.
DEFAULT_PPM_PER_LSB = 1 / 32

CS_BASE_FREQUENCY_MHZ = 2402.0

def channel_frequency_mhz(channel: int) -> float:
    """Centre frequency of a CS channel index."""
    return CS_BASE_FREQUENCY_MHZ + channel


@dataclass(frozen=True, slots=True)
class FaeStats:
    """Summary of one table in ppm. The fit is FAE against channel frequency."""

    mean_ppm: float
    std_ppm: float
    min_ppm: float
    min_channel: int
    max_ppm: float
    max_channel: int
    slope_ppm_per_mhz: float
    fit_residual_rms_ppm: float
    mean_hz: float


@dataclass(frozen=True, slots=True)
class FaeTable:
    """One FAE table: raw signed entries in HCI table order.

    ``label`` names the report (file and table number); ``line`` is the
    1-based line of the table header in its source text, or 0 when unknown.
    """

    entries: tuple[int, ...]
    label: str = ""
    line: int = 0
    ppm_per_lsb: float = DEFAULT_PPM_PER_LSB

    def __post_init__(self) -> None:
        if len(self.entries) != FAE_TABLE_ENTRIES:
            raise ValueError(
                f"FAE table needs {FAE_TABLE_ENTRIES} entries, got {len(self.entries)}")
        if not math.isfinite(self.ppm_per_lsb) or self.ppm_per_lsb <= 0:
            raise ValueError("FAE scale must be finite and positive")
        for value in self.entries:
            if not isinstance(value, int) or isinstance(value, bool) or not -128 <= value <= 127:
                raise ValueError(f"FAE entry {value} is outside int8")

    @classmethod
    def from_bytes(cls, data: bytes, label: str = "") -> FaeTable:
        """Build a table from the 72 raw octets of the HCI event."""
        if len(data) != FAE_TABLE_ENTRIES:
            raise ValueError(
                f"FAE table needs {FAE_TABLE_ENTRIES} bytes, got {len(data)}")
        return cls(tuple(b - 256 if b > 127 else b for b in data), label)

    @classmethod
    def zeros(cls, label: str = "No FAE report yet") -> FaeTable:
        return cls((0,) * FAE_TABLE_ENTRIES, label)

    @classmethod
    def from_packet(cls, packet, label: str = "") -> FaeTable:
        """Consume an FAE report without defining or changing its wire format.

        Failed reads are not measurements. Callers should retain their last table.
        """
        if packet.hci_status:
            raise ValueError(f"FAE read failed (HCI status 0x{packet.hci_status:02x})")
        denominator = packet.lsb_denominator
        if not isinstance(denominator, int) or isinstance(denominator, bool) or not 1 <= denominator <= 255:
            raise ValueError("FAE LSB denominator must be 1..255")
        return cls(tuple(packet.entries), label, ppm_per_lsb=1 / denominator)

    @property
    def is_zero(self) -> bool:
        return not any(self.entries)

    def ppm(self, ppm_per_lsb: float | None = None) -> tuple[float, ...]:
        """Entries in ppm, in table order (aligned with ``FAE_CHANNELS``)."""
        scale = self.ppm_per_lsb if ppm_per_lsb is None else ppm_per_lsb
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError("FAE scale must be finite and positive")
        return tuple(value * scale for value in self.entries)

    def hz(self, ppm_per_lsb: float | None = None) -> tuple[float, ...]:
        """Entries as frequency error in Hz at each channel's centre."""
        return tuple(
            ppm * channel_frequency_mhz(channel)  # ppm * MHz == Hz
            for ppm, channel in zip(self.ppm(ppm_per_lsb), FAE_CHANNELS))

    def by_channel(self, ppm_per_lsb: float | None = None) -> dict[int, float]:
        """Map CS channel index to FAE in ppm."""
        return dict(zip(FAE_CHANNELS, self.ppm(ppm_per_lsb)))

    def stats(self, ppm_per_lsb: float | None = None) -> FaeStats:
        values = self.ppm(ppm_per_lsb)
        freqs = [channel_frequency_mhz(channel) for channel in FAE_CHANNELS]
        count = len(values)
        mean = sum(values) / count
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / count)
        low = min(range(count), key=values.__getitem__)
        high = max(range(count), key=values.__getitem__)

        freq_mean = sum(freqs) / count
        sxx = sum((f - freq_mean) ** 2 for f in freqs)
        slope = sum((f - freq_mean) * (v - mean) for f, v in zip(freqs, values)) / sxx
        residual = math.sqrt(sum(
            (v - (mean + slope * (f - freq_mean))) ** 2
            for f, v in zip(freqs, values)) / count)

        return FaeStats(
            mean_ppm=mean,
            std_ppm=std,
            min_ppm=values[low],
            min_channel=FAE_CHANNELS[low],
            max_ppm=values[high],
            max_channel=FAE_CHANNELS[high],
            slope_ppm_per_mhz=slope,
            fit_residual_rms_ppm=residual,
            mean_hz=sum(self.hz(ppm_per_lsb)) / count,
        )
