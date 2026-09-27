"""Collect received CS protocol packets and derive per-channel PBR data.

Every decoded packet is kept, so each frame type can be displayed. Initiator
and reflector subevent results are grouped into procedures by
(config_id, start_acl_conn_event, procedure_counter). Their mode-2/3 steps are
paired by ordinal position in the procedure; both controllers report the same
step sequence, and a channel check discards pairs that do not line up.

Mode-0 correction. The two PCT measurements of one tone pair are taken
``tone_pair_delay_us`` apart. A residual carrier offset of ``Δf`` between the
devices rotates their product by ``2π·Δf·Δt``. The initiator's mode-0 steps
report the offset (``measured_freq_offset``, 0.01 ppm, 15-bit signed) and its
subevent header the compensation it applied (``frequency_compensation``). The
correction removes ``exp(j·sign·2π·ppm·1e-6·f_channel·Δt)`` from the product.
The term is proportional to ``f_channel``, so besides a large common phase it
tilts the phase slope: the distance bias is ``c·ppm·1e-6·Δt / 2`` (about 13 cm
for 12 ppm and Δt = 69 µs). The sign convention of the reported offset is not
pinned down here; ``sign`` flips it.

RTT. Mode-1/3 steps carry the HCI ``time_difference`` in 0.5 ns: ToA−ToD at
the initiator and ToD−ToA at the reflector (Zephyr ``cs_reports.h``). The
initiator's round trip includes the reflector's turnaround, so
``RTT = (ToA_I − ToD_I) − (ToD_R − ToA_R)`` and ``ToF = (t_i − t_r) / 2``
(the Zephyr distance_estimation sample does the same). RTT steps are paired by
ordinal position like PBR steps.

Uses the standard library only; plotting lives in ``ble_channel_sounding.views.results_view``.
"""

from __future__ import annotations

import cmath
from collections import deque
from dataclasses import dataclass, field, fields, is_dataclass
import json
import math
import statistics
from typing import Any, Iterable

from .protocol.frame import Frame
from .protocol.packets import (
    CsCapabilitiesPacket,
    CsConfigurationPacket,
    CsInitiatorSubeventResultPacket,
    CsProcedureEnableCompletePacket,
    CsPeerDataPacket,
    CsStep,
    CsSubeventResultPacket,
    LogMessagePacket,
    PacketType,
    decode_packet,
    packet_from_dict,
)
from .protocol.receiver import PacketReceiver

SPEED_OF_LIGHT_M_S = 299_792_458.0
CS_BASE_FREQUENCY_MHZ = 2402
OFFSET_NOT_AVAILABLE = 0xC000
T_RD_US = 5
DEFAULT_T_SW_US = 2

STEP_FLAG_RSSI_VALID = 0x01
STEP_FLAG_FREQ_OFFSET_VALID = 0x02
STEP_FLAG_TIME_DIFFERENCE_VALID = 0x04
STEP_FLAG_PCT_VALID = 0x08
QUALITY_HIGH = 0
QUALITY_UNAVAILABLE = 3  # BT_HCI_LE_CS_TONE_QUALITY_UNAVAILABLE
TIME_DIFFERENCE_UNIT_NS = 0.5
AA_QUALITY_SUCCESS = 0  # HCI packet quality: AA check successful, all bits matched
MAX_BIT_ERRORS = 15  # the bit error count is a nibble; this limit disables the filter

# The store keeps only the newest entries; live views redraw from it and slow down as it grows.
MAX_PACKETS = 200
MAX_PROCEDURES = 200
MAX_LOGS = 200

# Which offset the mode-0 correction removes.
CORRECTION_NONE = "none"
CORRECTION_MEASURED = "measured"  # mean initiator mode-0 measured_freq_offset
CORRECTION_COMPENSATION = "compensation"  # initiator frequency_compensation
CORRECTION_RESIDUAL = "residual"  # measured - compensation
CORRECTIONS = (CORRECTION_MEASURED, CORRECTION_RESIDUAL, CORRECTION_COMPENSATION, CORRECTION_NONE)


def centi_ppm(raw: int) -> float | None:
    """Decode an HCI 15-bit signed 0.01 ppm field; None when not available."""
    if raw == OFFSET_NOT_AVAILABLE:
        return None
    value = raw & 0x7FFF
    if value & 0x4000:
        value -= 0x8000
    return value / 100.0


def channel_frequency_hz(channel: int) -> float:
    return (CS_BASE_FREQUENCY_MHZ + channel) * 1e6


def tone_pair_delay_us(t_ip2_us: int, t_pm_us: int, paths: int, t_sw_us: int = DEFAULT_T_SW_US) -> int:
    """Time from an initiator tone slot to the reflector slot of the same path.

    Mode 2 and 3 both place the initiator's (paths + 1) switch/measure slots,
    T_RD and T_IP2 between the two tone trains (Core Vol 6 Part H 4.3), so the
    delay is the same for every path.
    """
    return (paths + 1) * (t_sw_us + t_pm_us) + T_RD_US + t_ip2_us


def unwrap(phases: list[float]) -> list[float]:
    """numpy.unwrap equivalent for a list of radians."""
    result: list[float] = []
    offset = 0.0
    for index, phase in enumerate(phases):
        if index:
            delta = phase - phases[index - 1]
            offset -= 2 * math.pi * round(delta / (2 * math.pi))
        result.append(phase + offset)
    return result


def linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """Least-squares (slope, intercept); None for fewer than two distinct x."""
    if len(xs) < 2:
        return None
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sxx
    return slope, mean_y - slope * mean_x


@dataclass(frozen=True, slots=True)
class PathSample:
    """One antenna path of one PBR step pair: both PCTs and their qualities."""

    path: int
    initiator: complex
    reflector: complex
    initiator_quality: int
    reflector_quality: int

    @property
    def high_quality(self) -> bool:
        return self.initiator_quality == QUALITY_HIGH and self.reflector_quality == QUALITY_HIGH

    @property
    def product(self) -> complex:
        return self.initiator * self.reflector


@dataclass(frozen=True, slots=True)
class PbrStep:
    """A matched initiator/reflector mode-2/3 step."""

    ordinal: int  # step position within the procedure, mode-0 steps included
    subevent: int  # initiator subevent report index within the procedure
    mode: int
    channel: int
    measured_offset_ppm: float | None
    compensation_ppm: float | None
    delay_us: int | None
    paths: tuple[PathSample, ...]
    # Reflector tones that break the IPT reporting rule (Q must be 0, I non-negative;
    # Core Vol 6 Part A 6.5, Part H 4.6).
    ipt_violations: int = 0

    def offset_ppm(self, correction: str) -> float | None:
        if correction == CORRECTION_MEASURED:
            return self.measured_offset_ppm
        if correction == CORRECTION_COMPENSATION:
            return self.compensation_ppm
        if correction == CORRECTION_RESIDUAL:
            if self.measured_offset_ppm is None:
                return None
            return self.measured_offset_ppm - (self.compensation_ppm or 0.0)
        return None

    def correction_phase(self, correction: str, sign: int = 1) -> float:
        """Radians removed from the product; 0 when offset or timing is unknown."""
        ppm = self.offset_ppm(correction)
        if ppm is None or self.delay_us is None:
            return 0.0
        return sign * 2 * math.pi * ppm * 1e-6 * channel_frequency_hz(self.channel) * self.delay_us * 1e-6


@dataclass(frozen=True, slots=True)
class ChannelPoint:
    """Per-channel PBR values for one antenna path, averaged over repeats."""

    channel: int
    count: int
    initiator: complex
    reflector: complex
    product: complex
    corrected: complex
    correction_rad: float
    offset_ppm: float | None

    @property
    def frequency_hz(self) -> float:
        return channel_frequency_hz(self.channel)


@dataclass(frozen=True, slots=True)
class PbrAnalysis:
    points: tuple[ChannelPoint, ...]
    unwrapped_raw: tuple[float, ...]
    unwrapped_corrected: tuple[float, ...]
    distance_raw_m: float | None
    distance_corrected_m: float | None
    fit_corrected: tuple[float, float] | None  # (slope rad/Hz, intercept rad)


def _slope_distance(points: tuple[ChannelPoint, ...], phases: list[float]) -> tuple[float | None, tuple[float, float] | None]:
    fit = linear_fit([p.frequency_hz for p in points], phases)
    if fit is None:
        return None, None
    # Reciprocal product phase is -4π·f·d/c (Zephyr distance_estimation sample).
    return -fit[0] * SPEED_OF_LIGHT_M_S / (4 * math.pi), fit


@dataclass
class Procedure:
    """Subevent reports of both roles that belong to one CS procedure."""

    config_id: int
    start_acl_conn_event: int
    procedure_counter: int
    initiator: list[CsSubeventResultPacket] = field(default_factory=list)
    reflector: list[CsSubeventResultPacket] = field(default_factory=list)
    time: float | None = None  # host arrival time of the first report, seconds; None for untimed captures
    peer_data: int = 0

    @property
    def key(self) -> tuple[int, int, int]:
        return self.config_id, self.start_acl_conn_event, self.procedure_counter

    @property
    def complete(self) -> bool:
        """Both roles have reported."""
        return bool(self.initiator and (self.reflector or self.peer_data == 1))

    @property
    def label(self) -> str:
        return (f"Procedure {self.procedure_counter} · config {self.config_id} · "
                f"ACL {self.start_acl_conn_event}")

    def pbr_steps(self, configuration: CsConfigurationPacket | None,
                  t_sw_us: int = DEFAULT_T_SW_US) -> tuple[list[PbrStep], int]:
        """Pair mode-2/3 steps of both roles. Returns (pairs, mismatched pairs).

        With IPT the reflector has already rotated its tones by the phase it measured, so the
        initiator's PCT carries the two-way phase and the reflector reports amplitude only
        (docs/Bluetooth_CS_Inline_Phase_Transfer.tex). ``t_sw_us`` is then T_SW_IPT.
        """
        pairs: list[PbrStep] = []

        def delay(paths):
            return (tone_pair_delay_us(configuration.t_ip2_time_us, configuration.t_pm_time_us, paths, t_sw_us)
                    if configuration is not None else None)

        if self.peer_data == 1 and self.initiator and not self.reflector:
            # Initiator only: unit reflector amplitude; the initiator's quality still applies.
            for ordinal, (se_index, report, step, measured) in enumerate(_flatten(self.initiator)):
                if step.mode not in (2, 3):
                    continue
                paths = report.num_antenna_paths
                tones = {tone.antenna_path: tone for tone in step.tones[:paths]}
                samples = tuple(PathSample(path, complex(tone.i, tone.q), 1 + 0j, tone.quality, QUALITY_HIGH)
                                for path, tone in sorted(tones.items()))
                pairs.append(PbrStep(ordinal, se_index, step.mode, step.channel, measured,
                                     centi_ppm(report.frequency_compensation), delay(paths), samples))
            return pairs, 0
        ipt = bool(configuration is not None and configuration.cs_enhancements_1 & 0x01)
        matched, mismatched = self._paired((2, 3))
        for ordinal, (se_index, header, step, measured), (_, ref_header, ref_step, _) in matched:
            paths = header.num_antenna_paths
            samples, violations = _path_samples(step, ref_step, paths, ref_header.num_antenna_paths, ipt)
            pairs.append(PbrStep(
                ordinal, se_index, step.mode, step.channel, measured,
                centi_ppm(header.frequency_compensation), delay(paths), samples, violations))
        return pairs, mismatched

    def rtt_steps(self) -> tuple[list[RttStep], int]:
        """Pair mode-1/3 steps of both roles. Returns (pairs, mismatched pairs)."""
        if self.peer_data == 1:
            return [], 0
        matched, mismatched = self._paired((1, 3))
        return [RttStep(ordinal, se_index, step.mode, step.channel, RttSide.of(step), RttSide.of(ref_step))
                for ordinal, (se_index, _, step, _), (_, _, ref_step, _) in matched], mismatched

    def _paired(self, modes: tuple[int, ...]):
        """Steps of both roles at the same ordinal whose mode is in ``modes``.

        A pair where either side has one of ``modes`` but mode or channel
        differ counts as mismatched, as does every step without a counterpart.
        """
        initiator = list(_flatten(self.initiator))
        reflector = list(_flatten(self.reflector))
        matched = []
        mismatched = abs(len(initiator) - len(reflector))
        for ordinal, (ini, ref) in enumerate(zip(initiator, reflector)):
            step, ref_step = ini[2], ref[2]
            if step.mode not in modes and ref_step.mode not in modes:
                continue
            if step.mode != ref_step.mode or step.channel != ref_step.channel:
                mismatched += 1
                continue
            matched.append((ordinal, ini, ref))
        return matched, mismatched


def _flatten(reports: Iterable[CsSubeventResultPacket]):
    """Yield (report index, header, step, mode-0 offset ppm) in reported order.

    The offset is the mean of valid mode-0 measurements in the latest report
    that carried any, so continuation reports inherit their subevent's value.
    """
    offset = None
    for index, report in enumerate(reports):
        measured = [centi_ppm(step.measured_freq_offset) for step in report.steps
                    if step.mode == 0 and step.flags & STEP_FLAG_FREQ_OFFSET_VALID]
        measured = [value for value in measured if value is not None]
        if measured:
            offset = sum(measured) / len(measured)
        for step in report.steps:
            yield index, report, step, offset


def _path_samples(ini: CsStep, ref: CsStep, ini_paths: int, ref_paths: int,
                  ipt: bool = False) -> tuple[tuple[PathSample, ...], int]:
    """Per-path samples and the count of reflector tones that break the IPT reporting rule.

    Under IPT the reflector's PCT is its amplitude in I (non-negative) with Q zero, so the
    sample uses the real, clamped I. A non-zero Q or a negative I is counted and the tone's
    reflector quality set to unavailable, so the high-quality filter drops it.
    """
    # The slot after the antenna paths is the tone extension; it is not a path measurement.
    ini_tones = {tone.antenna_path: tone for tone in ini.tones[:ini_paths]}
    ref_tones = {tone.antenna_path: tone for tone in ref.tones[:ref_paths]}
    samples, violations = [], 0
    for path in sorted(ini_tones.keys() & ref_tones.keys()):
        tone = ref_tones[path]
        quality = tone.quality
        if ipt:
            if tone.q != 0 or tone.i < 0:
                violations += 1
                quality = QUALITY_UNAVAILABLE
            reflector = complex(max(tone.i, 0), 0)
        else:
            reflector = complex(tone.i, tone.q)
        samples.append(PathSample(path, complex(ini_tones[path].i, ini_tones[path].q), reflector,
                                  ini_tones[path].quality, quality))
    return tuple(samples), violations


def analyze_pbr(steps: Iterable[PbrStep], path: int, correction: str = CORRECTION_MEASURED,
                sign: int = 1, high_quality_only: bool = True) -> PbrAnalysis:
    """Average one antenna path per channel and estimate distance from phase slope."""
    grouped: dict[int, list[tuple[PathSample, PbrStep]]] = {}
    for step in steps:
        for sample in step.paths:
            if sample.path == path and (sample.high_quality or not high_quality_only):
                grouped.setdefault(step.channel, []).append((sample, step))
    points = []
    for channel in sorted(grouped):
        items = grouped[channel]
        count = len(items)
        corrections = [step.correction_phase(correction, sign) for _, step in items]
        offsets = [step.offset_ppm(correction) for _, step in items]
        offsets = [value for value in offsets if value is not None]
        points.append(ChannelPoint(
            channel, count,
            sum(sample.initiator for sample, _ in items) / count,
            sum(sample.reflector for sample, _ in items) / count,
            sum(sample.product for sample, _ in items) / count,
            sum(sample.product * cmath.exp(-1j * phase) for (sample, _), phase in zip(items, corrections)) / count,
            sum(corrections) / count,
            sum(offsets) / len(offsets) if offsets else None))
    points_t = tuple(points)
    raw = unwrap([cmath.phase(p.product) for p in points_t])
    corrected = unwrap([cmath.phase(p.corrected) for p in points_t])
    distance_raw, _ = _slope_distance(points_t, raw)
    distance_corrected, fit = _slope_distance(points_t, corrected)
    return PbrAnalysis(points_t, tuple(raw), tuple(corrected), distance_raw, distance_corrected, fit)


@dataclass(frozen=True, slots=True)
class RttSide:
    """One role's mode-1/3 packet measurement; None where the controller reported none."""

    time_difference: int | None  # 0.5 ns; ToA−ToD for the initiator, ToD−ToA for the reflector
    aa_quality: int
    bit_errors: int
    nadm: int | None
    rssi: int | None
    antenna: int

    @classmethod
    def of(cls, step: CsStep) -> RttSide:
        return cls(step.time_difference if step.flags & STEP_FLAG_TIME_DIFFERENCE_VALID else None,
                   step.aa_quality, step.bit_errors, None if step.nadm == 0xFF else step.nadm,
                   step.rssi if step.flags & STEP_FLAG_RSSI_VALID else None, step.antenna)

    def accepted(self, aa_success_only: bool, max_bit_errors: int) -> bool:
        return (self.time_difference is not None
                and (self.aa_quality == AA_QUALITY_SUCCESS or not aa_success_only)
                and self.bit_errors <= max_bit_errors)


@dataclass(frozen=True, slots=True)
class RttStep:
    """A matched initiator/reflector mode-1/3 step."""

    ordinal: int
    subevent: int
    mode: int
    channel: int
    initiator: RttSide
    reflector: RttSide

    @property
    def tof_ns(self) -> float | None:
        if self.initiator.time_difference is None or self.reflector.time_difference is None:
            return None
        return (self.initiator.time_difference - self.reflector.time_difference) * TIME_DIFFERENCE_UNIT_NS / 2

    @property
    def distance_m(self) -> float | None:
        tof = self.tof_ns
        return None if tof is None else SPEED_OF_LIGHT_M_S * tof * 1e-9

    def accepted(self, aa_success_only: bool = True, max_bit_errors: int = MAX_BIT_ERRORS) -> bool:
        return (self.initiator.accepted(aa_success_only, max_bit_errors)
                and self.reflector.accepted(aa_success_only, max_bit_errors))


@dataclass(frozen=True, slots=True)
class RttAnalysis:
    accepted: tuple[RttStep, ...]
    rejected: tuple[RttStep, ...]
    mean_m: float | None
    median_m: float | None
    std_m: float | None  # sample standard deviation; None below two accepted steps

    @property
    def distances_m(self) -> list[float]:
        return [step.distance_m for step in self.accepted]


def analyze_rtt(steps: Iterable[RttStep], aa_success_only: bool = True,
                max_bit_errors: int = MAX_BIT_ERRORS) -> RttAnalysis:
    """Filter RTT step pairs and summarize their distances.

    A pair is accepted when both roles report a time difference, a successful
    AA check (unless ``aa_success_only`` is False) and at most
    ``max_bit_errors`` bit errors.
    """
    accepted, rejected = [], []
    for step in steps:
        (accepted if step.accepted(aa_success_only, max_bit_errors) else rejected).append(step)
    distances = [step.distance_m for step in accepted]
    return RttAnalysis(
        tuple(accepted), tuple(rejected),
        statistics.fmean(distances) if distances else None,
        statistics.median(distances) if distances else None,
        statistics.stdev(distances) if len(distances) > 1 else None)


@dataclass
class Received:
    """One packet in arrival order, with a running index for display."""

    index: int
    packet: Any
    timestamp: float | None = None
    direction: str = "received"

    @property
    def name(self) -> str:
        if isinstance(self.packet, Frame):
            return f"unknown_0x{self.packet.packet_type:04x}"
        return self.packet.PACKET_TYPE.name


class ResultStore:
    """The newest received packets, the latest reports and the newest grouped procedures.

    ``packet_count`` and ``log_count`` count everything ever added, so a view can
    tell which of the retained entries it has not shown yet.
    """

    def __init__(self, max_packets: int = MAX_PACKETS, max_procedures: int = MAX_PROCEDURES,
                 max_logs: int = MAX_LOGS) -> None:
        self.packets: deque[Received] = deque(maxlen=max_packets)
        self.packet_count = 0
        self.procedures: dict[tuple[int, int, int], Procedure] = {}
        self.max_procedures = max_procedures
        self.configurations: dict[int, CsConfigurationPacket] = {}
        self.capabilities: deque[CsCapabilitiesPacket] = deque(maxlen=16)
        self.enable_complete: dict[int, CsProcedureEnableCompletePacket] = {}
        self.logs: deque[str] = deque(maxlen=max_logs)
        self.log_count = 0
        self.origin: float | None = None  # arrival time of the first timed packet
        self.peer_data = 0

    def add(self, packet: Any, timestamp: float | None = None, direction: str = "received") -> Procedure | None:
        """Store a decoded packet, Frame or complete wire frame; return the procedure it updated.

        ``timestamp`` is the host arrival time in seconds, None when unknown.
        """
        if isinstance(packet, (bytes, bytearray, memoryview)):
            packet = Frame.from_bytes(packet)
        if isinstance(packet, Frame):
            packet = decode_packet(packet)
        if timestamp is not None and self.origin is None:
            self.origin = timestamp
        self.packets.append(Received(self.packet_count, packet, timestamp, direction))
        self.packet_count += 1
        if isinstance(packet, CsConfigurationPacket):
            self.configurations[packet.id] = packet
        elif isinstance(packet, CsCapabilitiesPacket):
            self.capabilities.append(packet)
        elif isinstance(packet, CsProcedureEnableCompletePacket):
            self.enable_complete[packet.config_id] = packet
        elif isinstance(packet, LogMessagePacket):
            self.logs.append(packet.message.decode("utf-8", errors="replace"))
            self.log_count += 1
        elif isinstance(packet, CsPeerDataPacket):
            self.peer_data = packet.peer_data
        elif isinstance(packet, CsSubeventResultPacket):
            key = (packet.config_id, packet.start_acl_conn_event, packet.procedure_counter)
            procedure = self.procedures.get(key)
            if procedure is None:
                procedure = self.procedures[key] = Procedure(*key, time=timestamp, peer_data=self.peer_data)
                if len(self.procedures) > self.max_procedures:
                    del self.procedures[next(iter(self.procedures))]
            side = procedure.initiator if isinstance(packet, CsInitiatorSubeventResultPacket) else procedure.reflector
            side.append(packet)
            return procedure
        return None

    def t_sw_us(self, configuration: CsConfigurationPacket | None = None) -> int:
        """Antenna switch time from the latest capabilities report, else the planner default.

        A configuration with IPT uses the IPT switch period (T_SW_IPT) instead.
        """
        if not self.capabilities:
            return DEFAULT_T_SW_US
        caps = self.capabilities[-1]
        if configuration is not None and configuration.cs_enhancements_1 & 0x01:
            return caps.t_sw_ipt_time_supported
        return caps.t_sw_time


def packet_from_json_line(line: str) -> Any:
    """Rebuild a packet from one line of a JSON-lines capture."""
    data = json.loads(line)
    if not isinstance(data, dict):
        raise TypeError(f"JSON capture line must be an object, got {type(data).__name__}")
    name = data.pop("packet_name")
    data.pop("packet_type", None)
    if name.startswith("unknown_0x"):
        return Frame(int(name[10:], 16), bytes.fromhex(data["payload"]))
    if name == PacketType.LOG_MESSAGE.name.lower():
        data.pop("message", None)
    return packet_from_dict(name, data)


def load_timed_capture(data: bytes) -> tuple[list[tuple[float | None, Any]], list[str]]:
    """Decode a capture into (host arrival time, packet) pairs; only HDF5 recordings carry times."""
    if data.startswith(b"\x89HDF\r\n\x1a\n"):
        from .recorder import load
        return load(data, include_tx=True, times=True, with_direction=True, include_host=True), []
    packets, errors = load_capture(data)
    return [(None, packet) for packet in packets], errors


def load_capture(data: bytes) -> tuple[list[Any], list[str]]:
    """Decode a capture: receiver JSON lines, or raw binary protocol frames."""
    if data.startswith(b"\x89HDF\r\n\x1a\n"):
        from .recorder import load
        return load(data), []
    errors: list[str] = []
    stripped = data.lstrip()
    if stripped.startswith(b"{"):
        packets = []
        for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                packets.append(packet_from_json_line(line))
            except (ValueError, KeyError, TypeError) as error:
                errors.append(f"line {number}: {error}")
        return packets, errors
    receiver = PacketReceiver()
    packets = receiver.feed(data)
    errors.extend(str(error) for error in receiver.packet_errors)
    return packets, errors


def describe(value: Any) -> Any:
    """Plain nested data for key/value display of any packet."""
    if is_dataclass(value):
        return {item.name: describe(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (tuple, list)):
        return [describe(item) for item in value]
    return value
