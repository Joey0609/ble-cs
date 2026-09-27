"""RX statistics independent of Qt; rates use host report arrival times."""
from collections import deque
from dataclasses import dataclass
import math
import time

from .protocol.packets import RadioTestStatsPacket


@dataclass(frozen=True)
class RadioSample:
    t: float
    received: int
    crc_errors: int
    rssi: float
    channel: int
    interval: float
    received_rate: float
    crc_rate: float
    crc_percent: float
    reset: bool

    def estimated_missing_rate(self, expected_rate):
        # Missing means undetected, excluding packets detected with bad CRC.
        if expected_rate <= 0 or not math.isfinite(self.received_rate):
            return math.nan
        return max(0., expected_rate - self.received_rate - self.crc_rate)


class RadioResultStore:
    def __init__(self, max_samples=5000):
        self.samples = deque(maxlen=max_samples)
        self.previous = None
        self.origin = None
        self.resets = 0

    def clear(self):
        self.samples.clear()
        self.previous = self.origin = None
        self.resets = 0

    def add(self, packet, timestamp=None):
        if not isinstance(packet, RadioTestStatsPacket):
            return None
        timestamp = time.monotonic() if timestamp is None else float(timestamp)
        if not math.isfinite(timestamp):
            raise ValueError("Report timestamp must be finite")
        if self.origin is None:
            self.origin = timestamp
        dt = rx_rate = crc_rate = percent = math.nan
        reset = False
        if self.previous is not None:
            previous_time, previous = self.previous
            dt = timestamp - previous_time
            rx = (packet.packets_received - previous.packets_received) & 0xffffffff
            crc = (packet.crc_errors - previous.crc_errors) & 0xffffffff
            # Half-range rule distinguishes ordinary rollover from counter reset.
            reset = rx >= 2**31 or crc >= 2**31 or dt < 0
            if reset:
                self.resets += 1
            elif dt > 0:
                rx_rate, crc_rate = rx / dt, crc / dt
                percent = 100 * crc / (rx + crc) if rx + crc else math.nan
        sample = RadioSample(timestamp - self.origin, packet.packets_received,
                             packet.crc_errors, math.nan if packet.rssi_dbm == 127 else packet.rssi_dbm,
                             packet.channel, dt, rx_rate, crc_rate, percent, reset)
        self.samples.append(sample)
        # Co-timed reports remain visible but share the last usable rate baseline.
        if self.previous is None or dt != 0:
            self.previous = timestamp, packet
        return sample
