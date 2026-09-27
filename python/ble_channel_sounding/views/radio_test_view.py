"""Radio test configuration pane; inactive fields retain exact serialized values."""
from dataclasses import asdict
from functools import lru_cache
import json
from pathlib import Path
import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg
from ..log_config import DEFAULT_LOG, normalize_log
from ..protocol.packets import RadioTestPattern, RadioTestPhy, RadioTestType, RadioTxTestConfigPacket
from ..validation import CHANNEL_TESTS, SLEEP_TESTS, SWEEP_TESTS, validate_radio_test
from .control_help import RADIO_CONTROL_DETAILS, detail_html, tab_html
from .cs_view import HelpEvents
from .layout import compact_form

DEFAULT = RadioTxTestConfigPacket(RadioTestType.UNMODULATED_TX, RadioTestPhy.BLE_1M, 3, 0, RadioTestPattern.RANDOM,
                                  0, 0, 80, 10, 50, 100, 100, 0, 255)

def preset_json(packet, log=None):
    """Radio preset file content, as written by Save preset and read by Open preset."""
    values = {k: int(v) for k, v in asdict(packet).items()}
    values["log"] = normalize_log(log)
    return json.dumps(values, indent=2) + "\n"


T = RadioTestType
CHOICES = {
    "test_type": {T.UNMODULATED_TX: "Unmodulated TX", T.MODULATED_TX: "Modulated TX", T.RX: "RX",
                  T.TX_SWEEP: "TX sweep", T.RX_SWEEP: "RX sweep", T.MODULATED_TX_DUTY_CYCLE: "Modulated TX duty cycle",
                  T.TX_SWEEP_WITH_SLEEP: "TX sweep with sleep",
                  T.TX_SWEEP_WITH_SLEEP_MODULATED: "Modulated TX sweep with sleep"},
    "phy": {RadioTestPhy.BLE_1M: "BLE 1M", RadioTestPhy.BLE_2M: "BLE 2M", RadioTestPhy.BLE_LR125K: "BLE LR 125k",
            RadioTestPhy.BLE_LR500K: "BLE LR 500k", RadioTestPhy.NRF_1M: "Nordic 1M", RadioTestPhy.NRF_2M: "Nordic 2M",
            RadioTestPhy.IEEE802154_250K: "IEEE 802.15.4 250k"},
    "pattern": {RadioTestPattern.RANDOM: "Random", RadioTestPattern.PATTERN_11110000: "11110000",
                RadioTestPattern.PATTERN_11001100: "11001100", RadioTestPattern.PATTERN_00000000: "00000000",
                RadioTestPattern.PATTERN_11111111: "11111111"},
}

# These are the finite radio output-power values accepted by the nRF54L radio
# test build.  Imported values outside the current set are retained by
# set_value() so old presets remain lossless.
TX_POWER_VALUES = (-46, -40, -28, -22, -20, -18, -16, -14, -12, -10, -9, -8, -7, -6,
                   -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8)
FEM_RAMP_UP_VALUES = (0, 40, 41, 42, 129, 130, 132)

LABELS = {
    "test_type": "Test type",
    "phy": "PHY",
    "pattern": "Pattern",
    "channel": "Channel",
    "txpower": "TX power (dBm)",
    "packet_count": "Packet count",
    "sweep_start_channel": "Start channel",
    "sweep_end_channel": "End channel",
    "sweep_delay_ms": "Channel dwell (ms)",
    "duty_cycle": "Duty cycle (%)",
    "tx_time_us": "Transmit time (µs)",
    "sleep_time_us": "Sleep time (µs)",
    "fem_ramp_up_time_us": "FEM ramp-up (µs)",
    "fem_tx_power_control": "FEM TX power control",
}

TOOLTIPS = {
    "test_type": "Radio operation to run. Fields that do not apply to the selected operation are retained but disabled.",
    "phy": "PHY selected by the radio driver. The connected SoC may support only a subset of these PHYs.",
    "pattern": "Payload pattern used by modulated transmit tests.",
    "channel": "Single radio channel. BLE and Nordic channels use 0–80; IEEE 802.15.4 uses 11–26.",
    "txpower": "Requested transmit power in dBm. Hardware support is checked by the client.",
    "packet_count": "Number of packets for a finite test. Zero means run until stopped.",
    "sweep_start_channel": "First channel in an inclusive channel sweep.",
    "sweep_end_channel": "Last channel in an inclusive channel sweep.",
    "sweep_delay_ms": "Time spent on each sweep channel before retuning.",
    "duty_cycle": "Transmit duty cycle for the modulated duty-cycle test, from 1 to 99 percent.",
    "tx_time_us": "Transmit duration on each channel for a sleep sweep.",
    "sleep_time_us": "Sleep duration between transmit bursts for a sleep sweep.",
    "fem_ramp_up_time_us": "Front-end module radio ramp-up time. Ignored when the client has no FEM.",
    "fem_tx_power_control": "Front-end module TX power control value; 255 keeps the client default.",
}

TAB_FIELDS = (
    ("Test", ("test_type", "phy", "pattern", "txpower", "packet_count")),
    ("Channel", ("channel", "sweep_start_channel", "sweep_end_channel", "sweep_delay_ms")),
    ("Timing", ("duty_cycle", "tx_time_us", "sleep_time_us")),
    ("FEM", ("fem_ramp_up_time_us", "fem_tx_power_control")),
)

TAB_TOOLTIPS = {
    "Test": "Select the radio operation, PHY, payload pattern, transmit power and packet count.",
    "Channel": "Choose a fixed channel or configure the inclusive channel sweep.",
    "Timing": "Configure finite traffic, duty-cycle timing and transmit/sleep timing.",
    "FEM": "Configure front-end module timing and transmit power control.",
}

CHANNEL_FIELDS = {"channel", "sweep_start_channel", "sweep_end_channel"}
BOUNDED_FIELDS = CHANNEL_FIELDS | {"txpower", "fem_ramp_up_time_us"}
UINT32_MAX = 0xFFFFFFFF
BOUNDED_CHOICES = {
    "txpower": {value: f"{value} dBm" for value in TX_POWER_VALUES},
    "fem_ramp_up_time_us": {
        value: "Default (0 µs)" if value == 0 else f"{value} µs"
        for value in FEM_RAMP_UP_VALUES
    },
}


# Radio-test channel numbering is different from the CS channel map: Nordic
# radio-test channels use 2400 + channel MHz.  IEEE 802.15.4 uses its own
# 5-MHz channel plan.
RADIO_BAND_MIN_MHZ = 2400.0
RADIO_BAND_MAX_MHZ = 2484.0


def radio_channel_frequency_mhz(phy, channel):
    """Return the centre frequency used by the radio-test firmware."""
    if int(phy) == int(RadioTestPhy.IEEE802154_250K):
        # NCS radio_test.c falls back to IEEE channel 11's 2405 MHz when a
        # sweep supplies a value outside the 802.15.4 range.
        if not 11 <= int(channel) <= 26:
            return 2405.0
        return 2405.0 + (int(channel) - 11) * 5.0
    return 2400.0 + int(channel)


def radio_channel_spacing_mhz(phy):
    """Return adjacent channel-centre spacing, not PHY occupied bandwidth."""
    return 5.0 if int(phy) == int(RadioTestPhy.IEEE802154_250K) else 1.0


def radio_test_channels(packet):
    """Return the configured channel sequence for the preview."""
    if packet.test_type in SWEEP_TESTS or packet.test_type in SLEEP_TESTS:
        return tuple(range(packet.sweep_start_channel, packet.sweep_end_channel + 1))
    if packet.test_type in CHANNEL_TESTS:
        return (packet.channel,)
    return ()


class _SpectrumPreview(pg.PlotWidget):
    """A generated example-frame spectrum for the configured radio test.

    The host has no RF samples, so modulated views synthesize a deterministic
    example PHY frame and calculate its idealized GFSK spectrum.  This keeps
    the view useful for comparing patterns while making it clear that the
    result is not a measurement from the connected radio.
    """

    PHY_BANDWIDTH_MHZ = {
        RadioTestPhy.BLE_1M: 1.0,
        RadioTestPhy.BLE_2M: 2.0,
        RadioTestPhy.BLE_LR125K: 0.5,
        RadioTestPhy.BLE_LR500K: 1.0,
        RadioTestPhy.NRF_1M: 1.0,
        RadioTestPhy.NRF_2M: 2.0,
        RadioTestPhy.IEEE802154_250K: 2.0,
    }
    CARRIER_MODES = (T.UNMODULATED_TX, T.TX_SWEEP, T.TX_SWEEP_WITH_SLEEP)
    MODULATED_MODES = (T.MODULATED_TX, T.MODULATED_TX_DUTY_CYCLE,
                       T.TX_SWEEP_WITH_SLEEP_MODULATED)
    GFSK_PHYS = (RadioTestPhy.BLE_1M, RadioTestPhy.BLE_2M,
                 RadioTestPhy.BLE_LR125K, RadioTestPhy.BLE_LR500K,
                 RadioTestPhy.NRF_1M, RadioTestPhy.NRF_2M)

    def __init__(self, parent=None):
        super().__init__(parent=parent, background="white")
        self.packet = None
        self.channels = ()
        self.frequencies = ()
        self.mode_text = ""
        self.center_frequency_mhz = None
        self.channel_spacing_mhz = None
        self.example_frame = b""
        self._dynamic_items = []
        self.setMinimumHeight(250)
        self.setSizePolicy(W.QSizePolicy.Policy.Expanding, W.QSizePolicy.Policy.Expanding)
        self.setMouseEnabled(x=False, y=False)
        self.setMenuEnabled(False)
        self.setTitle("RF spectrum preview", color="#21334b", size="10pt")
        self.setLabel("bottom", "Frequency", units="MHz", **{"color": "#536981"})
        self.setLabel("left", "Relative level", **{"color": "#536981"})
        self.showGrid(x=True, y=True, alpha=0.15)
        self.setXRange(RADIO_BAND_MIN_MHZ, RADIO_BAND_MAX_MHZ, padding=0)
        self.setYRange(0, 1.12, padding=0)
        for axis_name in ("bottom", "left"):
            axis = self.getPlotItem().getAxis(axis_name)
            axis.setPen(pg.mkPen("#cbd5e1"))
            axis.setTextPen(pg.mkPen("#536981"))
        self.getPlotItem().getAxis("bottom").setTicks([
            [(float(frequency), str(frequency)) for frequency in range(2400, 2481, 10)]
        ])

    def _clear_dynamic(self):
        for item in self._dynamic_items:
            self.removeItem(item)
        self._dynamic_items.clear()

    def _add(self, item):
        self.addItem(item)
        self._dynamic_items.append(item)
        return item

    def _plot(self, *args, **kwargs):
        return self._add(pg.PlotDataItem(*args, **kwargs))

    @staticmethod
    def _brush(colour, alpha):
        value = QtGui.QColor(colour)
        value.setAlpha(alpha)
        return pg.mkBrush(value)

    def _label(self, text, frequency, colour, y=1.02):
        item = pg.TextItem(text=text, color=colour, anchor=(0.5, 0.0))
        item.setPos(frequency, y)
        return self._add(item)

    def _band(self, frequency, bandwidth, colour, label):
        left = frequency - bandwidth / 2
        right = frequency + bandwidth / 2
        x = [left, left + (right - left) * .18, frequency,
             left + (right - left) * .82, right]
        y = [0.0, .62, 1.0, .62, 0.0]
        upper = self._plot(x, y, pen=pg.mkPen(colour, width=2))
        lower = self._plot(x, [0.0] * len(x), pen=None)
        self._add(pg.FillBetweenItem(upper, lower, brush=self._brush(colour, 55)))
        self._label(label, frequency, colour)

    @staticmethod
    @lru_cache(maxsize=None)
    def _example_frame(pattern):
        """Return a deterministic payload-sized frame filled with ``pattern``.

        The firmware's modulated test uses these byte values as its payload
        patterns.  The random case is deterministic here so the preview does
        not jump on every refresh.
        """
        payload_length = 32
        pattern = int(pattern)
        values = {
            int(RadioTestPattern.PATTERN_11110000): 0xF0,
            int(RadioTestPattern.PATTERN_11001100): 0xCC,
            int(RadioTestPattern.PATTERN_00000000): 0x00,
            int(RadioTestPattern.PATTERN_11111111): 0xFF,
        }
        if pattern in values:
            return bytes([values[pattern]] * payload_length)

        state = 0x5D
        frame = bytearray()
        for _ in range(payload_length):
            value = 0
            for bit in range(8):
                feedback = ((state >> 6) ^ (state >> 5)) & 1
                state = ((state << 1) | feedback) & 0x7F
                value |= (state & 1) << bit
            frame.append(value)
        return bytes(frame)

    @classmethod
    @lru_cache(maxsize=None)
    def _gfsk_waveform(cls, pattern, bandwidth):
        """Return a smooth GFSK spectrum for a generated example frame.

        This models BLE's h=0.5 modulation index and BT=0.5 Gaussian filter.
        The selected payload pattern is converted to bits before modulation,
        so constant and alternating patterns produce visibly different
        spectra.
        """
        samples_per_symbol = 16
        frame = cls._example_frame(pattern)
        bits = np.unpackbits(np.frombuffer(frame, dtype=np.uint8), bitorder="little")
        symbols = np.repeat((bits.astype(float) * 2.0) - 1.0, samples_per_symbol)

        time = np.arange(-2.0, 2.0 + 1.0 / samples_per_symbol,
                         1.0 / samples_per_symbol)
        sigma = np.sqrt(np.log(2.0)) / (2.0 * np.pi * 0.5)
        gaussian = np.exp(-0.5 * (time / sigma) ** 2)
        gaussian /= gaussian.sum()
        shaped = np.convolve(symbols, gaussian, mode="same")
        shaped = shaped[4 * samples_per_symbol:-4 * samples_per_symbol]

        # Integrating the filtered frequency pulses gives a continuous-phase
        # FSK waveform.  The factor below is 2*pi*(h/2) per symbol.
        phase = np.cumsum(np.pi * 0.5 * shaped / samples_per_symbol)
        signal = np.exp(1j * phase)
        window = np.hanning(signal.size)
        fft_size = 4096
        spectrum = np.fft.fftshift(np.fft.fft(signal * window, n=fft_size))
        power = np.abs(spectrum) ** 2
        smoothing_window = 9
        power = np.convolve(power, np.ones(smoothing_window) / smoothing_window,
                             mode="same")
        frequency = np.fft.fftshift(np.fft.fftfreq(fft_size,
                                                    d=1.0 / samples_per_symbol))
        visible = np.abs(frequency) <= 2.0
        level = np.sqrt(power[visible])
        peak = float(level.max())
        if peak:
            level /= peak
        return frequency[visible] * bandwidth, level

    def _gfsk_band(self, frequency, bandwidth, colour, label=None):
        offsets, level = self._gfsk_waveform(self.packet.pattern, bandwidth)
        x = frequency + offsets
        upper = self._plot(x, level, pen=pg.mkPen(colour, width=2))
        lower = self._plot(x, np.zeros_like(level), pen=None)
        self._add(pg.FillBetweenItem(upper, lower, brush=self._brush(colour, 55)))
        if label:
            self._label(label, frequency, colour)

    def _smooth_modulated_band(self, frequency, bandwidth, colour, label=None):
        """Draw a non-triangular generic digital-modulation envelope."""
        offsets = np.linspace(-bandwidth, bandwidth, 161)
        normalized = offsets / max(bandwidth / 2.0, 1e-9)
        level = np.exp(-0.5 * (normalized / 0.78) ** 2)
        upper = self._plot(frequency + offsets, level,
                           pen=pg.mkPen(colour, width=2))
        lower = self._plot(frequency + offsets, np.zeros_like(level), pen=None)
        self._add(pg.FillBetweenItem(upper, lower, brush=self._brush(colour, 55)))
        if label:
            self._label(label, frequency, colour)

    def _modulated_band(self, frequency, bandwidth, colour, *, show_label=True):
        label = None
        if self.packet.phy in self.GFSK_PHYS:
            if show_label:
                label = f"GFSK · {bandwidth:g} MHz nominal · {frequency:g} MHz centre"
            self._gfsk_band(frequency, bandwidth, colour, label)
        else:
            if show_label:
                label = f"modulated spectrum · {bandwidth:g} MHz nominal · {frequency:g} MHz centre"
            self._smooth_modulated_band(frequency, bandwidth, colour, label)

    def _carrier(self, frequency, label):
        self._plot([frequency, frequency], [0.0, 1.0],
                   pen=pg.mkPen("#f4c95d", width=3))
        self._add(pg.InfiniteLine(pos=frequency, angle=90,
                                  pen=pg.mkPen("#fff4bd", width=1,
                                               style=QtCore.Qt.PenStyle.DashLine)))
        self._label(label, frequency, "#f4c95d")

    def set_packet(self, packet):
        self._clear_dynamic()
        self.packet = packet
        if packet is None:
            self.channels = ()
            self.frequencies = ()
            self.center_frequency_mhz = None
            self.channel_spacing_mhz = None
            self.mode_text = ""
            self.example_frame = b""
            self.setTitle("RF spectrum preview", color="#21334b", size="10pt")
            return
        self.channels = radio_test_channels(packet)
        self.frequencies = tuple(radio_channel_frequency_mhz(packet.phy, channel)
                                 for channel in self.channels)
        self.center_frequency_mhz = self.frequencies[0] if len(self.frequencies) == 1 else None
        self.channel_spacing_mhz = radio_channel_spacing_mhz(packet.phy)
        self.example_frame = self._example_frame(packet.pattern)
        self.mode_text = CHOICES["test_type"].get(packet.test_type, "Radio test")
        title = "Example-frame spectrum" if packet.test_type in self.MODULATED_MODES else "RF spectrum preview"
        self.setTitle(f"{title} · {self.channel_spacing_mhz:g} MHz centre spacing",
                      color="#21334b", size="10pt")
        if not self.frequencies:
            return

        kind = self.packet.test_type
        frequency = self.frequencies[0]
        bandwidth = self.PHY_BANDWIDTH_MHZ.get(self.packet.phy, 1.0)
        colour = "#f4c95d" if kind in self.CARRIER_MODES else \
                 "#55d6be" if kind == T.RX else "#5aa9e6"

        if len(self.frequencies) > 1:
            if kind in self.MODULATED_MODES:
                # Show the modulation shape at each selected centre instead
                # of reducing a modulated sweep to triangular markers.
                for selected in self.frequencies:
                    self._modulated_band(selected, bandwidth, colour, show_label=False)
                self._label(f"{len(self.frequencies)} channels · modulated",
                            sum(self.frequencies) / len(self.frequencies), colour)
            else:
                # A sweep is shown as selected channel centres and a soft
                # region, rather than as a misleading continuous signal.
                region = pg.LinearRegionItem((min(self.frequencies) - .5,
                                              max(self.frequencies) + .5),
                                             movable=False, brush=self._brush(colour, 45),
                                             pen=pg.mkPen(colour, width=1))
                self._add(region)
                self._plot(self.frequencies, [0.72] * len(self.frequencies),
                           pen=None, symbol="t", symbolSize=8,
                           symbolBrush=colour, symbolPen=colour)
                self._label(f"{len(self.frequencies)} channels · {self.frequencies[0]:g}–{self.frequencies[-1]:g} MHz",
                            sum(self.frequencies) / len(self.frequencies), colour)
        elif kind in self.CARRIER_MODES:
            self._carrier(frequency, f"carrier · channel {self.packet.channel if kind == T.UNMODULATED_TX else 'sweep'}")
        elif kind == T.RX:
            region = pg.LinearRegionItem((frequency - bandwidth / 2, frequency + bandwidth / 2),
                                         movable=False, brush=self._brush(colour, 45),
                                         pen=pg.mkPen(colour, width=2,
                                                      style=QtCore.Qt.PenStyle.DashLine))
            self._add(region)
            self._label(f"listening window · {frequency:g} MHz", frequency, colour)
        elif kind in self.MODULATED_MODES:
            self._modulated_band(frequency, bandwidth, colour)
        else:
            self._band(frequency, bandwidth, colour,
                       f"{bandwidth:g} MHz nominal envelope · {frequency:g} MHz centre")

        # Centre markers remain visible for a single channel and a wide sweep.
        for channel, selected in zip(self.channels, self.frequencies):
            line = pg.InfiniteLine(pos=selected, angle=90,
                                   movable=False, pen=pg.mkPen("#d8e5f1", width=1,
                                                                style=QtCore.Qt.PenStyle.DotLine))
            self._add(line)
            if len(self.frequencies) == 1:
                self._label(f"ch {channel}", selected, "#d8e5f1", y=0.02)



class _TimelineBar(W.QWidget):
    """Small explanatory timeline; it deliberately contains no measured data."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.segments = []
        self.setMinimumHeight(44)
        self.setSizePolicy(W.QSizePolicy.Policy.Expanding, W.QSizePolicy.Policy.Fixed)

    def set_segments(self, segments):
        self.segments = list(segments)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 6, 0, -6)
        total = sum(max(0.0, fraction) for _, fraction, _ in self.segments) or 1.0
        left = float(rect.left())
        for label, fraction, color in self.segments:
            width = rect.width() * max(0.0, fraction) / total
            segment = QtCore.QRectF(left, rect.top(), width, rect.height())
            painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 1))
            painter.setBrush(QtGui.QColor(color))
            painter.drawRoundedRect(segment, 4, 4)
            if width > 52:
                painter.setPen(QtGui.QColor("#ffffff"))
                painter.drawText(segment, QtCore.Qt.AlignmentFlag.AlignCenter, label)
            left += width


class RadioTestPreview(W.QGroupBox):
    """Explain the selected radio operation with a generated, non-live spectrum."""

    DESCRIPTIONS = {
        T.UNMODULATED_TX: "Transmits an unmodulated carrier on one channel until stopped or the finite test completes.",
        T.MODULATED_TX: "Transmits modulated packets on one channel using the selected payload pattern.",
        T.RX: "Listens for modulated packets on one channel and reports cumulative RX statistics.",
        T.TX_SWEEP: "Transmits while stepping through the inclusive channel range at the configured dwell time.",
        T.RX_SWEEP: "Listens while stepping through the inclusive channel range at the configured dwell time.",
        T.MODULATED_TX_DUTY_CYCLE: "Transmits modulated packets with the selected duty cycle on one channel.",
        T.TX_SWEEP_WITH_SLEEP: "Transmits on each sweep channel, then sleeps for the configured interval.",
        T.TX_SWEEP_WITH_SLEEP_MODULATED: "Transmits modulated packets on each sweep channel with sleep between bursts.",
    }

    def __init__(self, view, parent=None):
        super().__init__("Operation preview", parent)
        self.view = view
        layout = W.QVBoxLayout(self)
        self.title_label = W.QLabel()
        self.title_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #21334b;")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        self.description_label = W.QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet("color: #536981; padding: 4px 0 8px;")
        layout.addWidget(self.description_label)
        self.parameters = W.QLabel()
        self.parameters.setWordWrap(True)
        self.parameters.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.parameters)
        self.spectrum = _SpectrumPreview()
        layout.addWidget(self.spectrum, 1)
        self.timeline = _TimelineBar()
        layout.addWidget(self.timeline)
        self.note = W.QLabel("For modulated modes, the generated spectrum uses the selected example frame; it is not a live spectrum measurement. Live RX statistics are shown in Results.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #536981; padding-top: 8px;")
        layout.addWidget(self.note)
        layout.addStretch(1)

    def refresh(self):
        try:
            kind = self.view.controls["test_type"].currentData()
            packet = RadioTxTestConfigPacket(**{name: self.view.value(name) for name in self.view.controls})
            errors = validate_radio_test(packet)
        except (TypeError, ValueError) as error:
            self.title_label.setText("Invalid radio configuration")
            self.description_label.setText(str(error))
            self.parameters.clear()
            self.spectrum.set_packet(None)
            self.timeline.set_segments([])
            return
        if errors:
            self.title_label.setText("Invalid radio configuration")
            self.description_label.setText(" · ".join(errors))
            self.parameters.clear()
            self.spectrum.set_packet(None)
            self.timeline.set_segments([])
            return

        name = CHOICES["test_type"].get(kind, f"Unknown test ({kind})")
        self.title_label.setText(name)
        self.description_label.setText(self.DESCRIPTIONS.get(kind, "The connected client does not describe this test type."))
        if kind in SWEEP_TESTS or kind in SLEEP_TESTS:
            channel = f"Channels {packet.sweep_start_channel}–{packet.sweep_end_channel}"
        elif kind in CHANNEL_TESTS:
            channel = f"Channel {packet.channel}"
        else:
            channel = "Channel range is not used"
        count = "continuous" if not packet.packet_count else f"{packet.packet_count:,} packets"
        details = [channel, f"PHY: {CHOICES['phy'].get(packet.phy, f'Unknown ({packet.phy})')}",
                   f"centre spacing: {radio_channel_spacing_mhz(packet.phy):g} MHz", count]
        if kind in (T.MODULATED_TX, T.RX, T.MODULATED_TX_DUTY_CYCLE, T.TX_SWEEP_WITH_SLEEP_MODULATED):
            details.append(f"pattern: {CHOICES['pattern'].get(packet.pattern, f'Unknown ({packet.pattern})')}")
        if kind in SWEEP_TESTS:
            details.append(f"{packet.sweep_delay_ms} ms dwell")
        if kind == T.MODULATED_TX_DUTY_CYCLE:
            details.append(f"{packet.duty_cycle}% duty cycle")
        if kind in SLEEP_TESTS:
            details.append(f"{packet.tx_time_us} µs TX / {packet.sleep_time_us} µs sleep")
        self.parameters.setText(" · ".join(details))
        self.spectrum.set_packet(packet)
        if kind == T.MODULATED_TX_DUTY_CYCLE:
            self.timeline.set_segments((("TX", packet.duty_cycle, "#2274a5"),
                                        ("idle", 100 - packet.duty_cycle, "#aab8cb")))
        elif kind in SLEEP_TESTS:
            self.timeline.set_segments((("TX", packet.tx_time_us, "#2274a5"),
                                        ("sleep", packet.sleep_time_us, "#aab8cb")))
        elif kind in SWEEP_TESTS:
            self.timeline.set_segments((("channel dwell", 1, "#209f91"),
                                        ("retune", .15, "#aab8cb")))
        elif kind == T.RX:
            self.timeline.set_segments((("RX listening", 1, "#209f91"),))
        else:
            self.timeline.set_segments((("TX", 1, "#2274a5"),))


class RadioTestView(W.QWidget):
    configuration_changed = QtCore.pyqtSignal()
    log_changed = QtCore.pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QWidget { background: #f4f7fb; color: #21334b; font-size: 12px; }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: white; border: 1px solid #cbd5e1;
                border-radius: 4px; padding: 5px; min-height: 20px; }
            QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
                background: #e9eef4; color: #8a9bb0; }
            QPushButton { background: #e6edf7; border: 1px solid #cad6e6; border-radius: 5px; padding: 7px 12px; }
            QPushButton:hover { background: #d7e6f7; }
            QTabWidget::pane { border: 1px solid #d5dfe9; background: white; }
            QTabBar::tab { padding: 10px 13px; }
            QTabBar::tab:selected { background: white; color: #146fba; }
            QGroupBox { font-weight: bold; margin-top: 14px; padding-top: 16px; }
            QTextBrowser { background: white; border: 1px solid #d5dfe9; padding: 8px; }
            QSplitter::handle { background: #cbd8e6; }
            QSplitter::handle:hover { background: #146fba; }
            QSplitter::handle:vertical { height: 8px; }
        """)
        layout = W.QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.controls = {}
        self.forms = {}
        self.labels = {}
        self.help_rows = {}
        self.log = dict(DEFAULT_LOG)

        settings = W.QWidget()
        settings_layout = W.QVBoxLayout(settings)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = W.QTabWidget()
        self.tabs.currentChanged.connect(self.show_tab_help)
        settings_layout.addWidget(self.tabs, 1)
        for tab_title, field_names in TAB_FIELDS:
            page = W.QWidget()
            page_layout = W.QVBoxLayout(page)
            container = W.QWidget()
            form = compact_form(container)
            self.forms[tab_title] = form
            for name in field_names:
                control = self._control(name)
                form.addRow(LABELS[name], control)
                self.controls[name] = control
                self.labels[name] = form.labelForField(control)
                control.setToolTip(TOOLTIPS[name])
                self.labels[name].setToolTip(TOOLTIPS[name])
                self.help_rows[name] = (LABELS[name], TOOLTIPS[name], control)
            page_layout.addWidget(container)
            page_layout.addStretch(1)
            index = self.tabs.addTab(page, tab_title)
            self.tabs.setTabToolTip(index, TAB_TOOLTIPS[tab_title])

        actions = W.QHBoxLayout()
        for title, action in (("Open preset…", self.open_file), ("Save preset…", self.save_file)):
            button = W.QPushButton(title)
            button.clicked.connect(action)
            actions.addWidget(button)
        actions.addStretch(1)
        settings_layout.addLayout(actions)
        self.status = W.QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        settings_layout.addWidget(self.status)
        help_splitter = W.QSplitter(QtCore.Qt.Orientation.Vertical)
        help_splitter.setHandleWidth(8)
        help_splitter.setChildrenCollapsible(False)
        help_splitter.addWidget(settings)
        self.help_pane = W.QTabWidget()
        self.tab_help = W.QTextBrowser()
        self.setting_help = W.QTextBrowser()
        for browser, title in ((self.tab_help, "About this tab"), (self.setting_help, "Setting details")):
            browser.setOpenLinks(False)
            browser.anchorClicked.connect(self.help_link_clicked)
            self.help_pane.addTab(browser, title)
        help_splitter.addWidget(self.help_pane)
        help_splitter.setSizes([560, 240])
        help_splitter.setMinimumWidth(320)
        self.help_events = HelpEvents(self)
        self.help_events.requested.connect(self.show_setting_help)
        for name, (_, _, control) in self.help_rows.items():
            self.help_events.watch(control, name)
            self.help_events.watch(self.labels[name], name)
        self.preview = RadioTestPreview(self)
        self.main_splitter = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("radioConfigurationSplitter")
        self.main_splitter.setHandleWidth(8)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(help_splitter)
        self.main_splitter.addWidget(self.preview)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([520, 760])
        self.preview.setMinimumWidth(400)
        layout.addWidget(self.main_splitter, 1)
        self.apply_config(DEFAULT)
        self.show_tab_help()

    def show_tab_help(self, *_):
        """Show the same lower tab overview used by the CS configuration view."""
        if not hasattr(self, "help_pane"):
            return
        page = self.tabs.currentWidget()
        settings = [(key, label) for key, (label, _, control) in self.help_rows.items()
                    if page is not None and page.isAncestorOf(control) and not control.isHidden()]
        self.tab_help.setHtml(tab_html(self.tabs.tabText(self.tabs.currentIndex()), settings))
        self.help_pane.setCurrentWidget(self.tab_help)

    def help_link_clicked(self, url):
        self.show_setting_help(url.fragment())

    def show_setting_help(self, key):
        if key not in self.help_rows:
            return
        label, tip, control = self.help_rows[key]
        self.setting_help.setHtml(detail_html(key, label, tip, read_only=not control.isEnabled(),
                                              detail=RADIO_CONTROL_DETAILS[key]))
        self.help_pane.setCurrentWidget(self.setting_help)

    def _control(self, name):
        if name in CHANNEL_FIELDS:
            control = W.QSpinBox()
            # Keep inactive uint8 channel values lossless; active limits are
            # narrowed by _update_channel_choices() for the selected mode.
            control.setRange(0, 0xFF)
            control.valueChanged.connect(self.edited)
            return control
        if name == "sweep_delay_ms":
            # QSpinBox is signed 32-bit, while the protocol field is uint32.
            # A zero-decimal QDoubleSpinBox provides the same integer arrows
            # without rejecting the upper half of the wire-format range.
            control = W.QDoubleSpinBox()
            control.setDecimals(0)
            control.setRange(1, UINT32_MAX)
            control.setSingleStep(1)
            control.valueChanged.connect(self.edited)
            return control
        if name in CHOICES or name in BOUNDED_FIELDS:
            control = W.QComboBox()
            if name in CHOICES:
                for value, text in CHOICES[name].items():
                    control.addItem(text, int(value))
            elif name in BOUNDED_CHOICES:
                for value, text in BOUNDED_CHOICES[name].items():
                    control.addItem(text, value)
            else:
                for value in range(81):
                    control.addItem(str(value), value)
            control.currentIndexChanged.connect(self.edited)
            return control
        # Decimal text edits support the full uint32 domain (QSpinBox is int32).
        control = W.QLineEdit()
        control.setPlaceholderText("Decimal value")
        control.textChanged.connect(self.edited)
        return control

    def value(self, name):
        control = self.controls[name]
        if isinstance(control, W.QComboBox):
            return control.currentData()
        if isinstance(control, (W.QSpinBox, W.QDoubleSpinBox)):
            return int(control.value())
        try:
            return int(control.text())
        except ValueError as error:
            raise ValueError(f"{LABELS[name]} must be an integer") from error

    def set_value(self, name, value):
        control = self.controls[name]
        if isinstance(control, (W.QSpinBox, W.QDoubleSpinBox)):
            control.setValue(int(value))
            return
        if not isinstance(control, W.QComboBox):
            control.setText(str(value))
            return
        index = control.findData(int(value))
        if index < 0:
            # Keep a client value outside the known enum so it round-trips unchanged.
            control.addItem(f"Unknown ({value})", int(value))
            index = control.count() - 1
        control.setCurrentIndex(index)

    def edited(self, *_):
        kind = self.controls["test_type"].currentData()
        self._update_channel_choices()
        active = {"test_type", "phy", "pattern", "fem_ramp_up_time_us", "fem_tx_power_control"}
        if kind not in (T.RX, T.RX_SWEEP):
            active.add("txpower")
        if kind in CHANNEL_TESTS:
            active.add("channel")
        if kind in (T.MODULATED_TX, T.RX, T.MODULATED_TX_DUTY_CYCLE):
            active.add("packet_count")
        if kind in SWEEP_TESTS:
            active.update(("sweep_start_channel", "sweep_end_channel", "sweep_delay_ms"))
        if kind == T.MODULATED_TX_DUTY_CYCLE:
            active.add("duty_cycle")
        if kind in SLEEP_TESTS:
            active.update(("tx_time_us", "sleep_time_us"))
        for name, control in self.controls.items():
            enabled = name in active
            control.setEnabled(enabled)
            self.labels[name].setEnabled(enabled)
        self._update_status()
        self.configuration_changed.emit()

    def _update_channel_choices(self):
        """Apply the valid channel range to each active channel spin box."""
        phy = self.controls["phy"].currentData()
        kind = self.controls["test_type"].currentData()
        fixed_range = (11, 26) if int(phy) == int(RadioTestPhy.IEEE802154_250K) else (0, 80)
        ranges = {
            "channel": fixed_range if kind in CHANNEL_TESTS else (0, 0xFF),
            "sweep_start_channel": (0, 80) if kind in SWEEP_TESTS else (0, 0xFF),
            "sweep_end_channel": (0, 80) if kind in SWEEP_TESTS else (0, 0xFF),
        }
        for name, (minimum, maximum) in ranges.items():
            control = self.controls[name]
            current = control.value()
            control.blockSignals(True)
            try:
                control.setRange(minimum, maximum)
                control.setValue(min(max(current, minimum), maximum))
            finally:
                control.blockSignals(False)

    def _update_status(self):
        """Show a compact validation result without making editing disruptive."""
        try:
            packet = RadioTxTestConfigPacket(**{name: self.value(name) for name in self.controls})
            errors = validate_radio_test(packet)
        except (TypeError, ValueError) as error:
            errors = [str(error)]
        if errors:
            self.status.setText("Invalid configuration: " + " · ".join(errors))
            self.status.setStyleSheet("color: #b42318; padding: 4px 0;")
        else:
            kind = self.controls["test_type"].currentData()
            active = [LABELS[name] for name, control in self.controls.items() if control.isEnabled()]
            self.status.setText(f"Ready · {CHOICES['test_type'].get(kind, f'Unknown test ({kind})')} · "
                                f"active fields: {', '.join(active)}")
            self.status.setStyleSheet("color: #3d5f7d; padding: 4px 0;")
        self.preview.refresh()

    def collect_config(self):
        packet = RadioTxTestConfigPacket(**{name: self.value(name) for name in self.controls})
        errors = validate_radio_test(packet)
        if errors:
            raise ValueError("\n".join(errors))
        return packet

    def apply_config(self, packet):
        if not isinstance(packet, RadioTxTestConfigPacket):
            raise TypeError("Expected radio test configuration")
        for control in self.controls.values():
            control.blockSignals(True)
        try:
            for name in self.controls:
                self.set_value(name, getattr(packet, name))
            # The target channel values must be written again after the PHY
            # range changes; the old PHY may have clamped them differently.
            self._update_channel_choices()
            for name in CHANNEL_FIELDS:
                self.set_value(name, getattr(packet, name))
        finally:
            for control in self.controls.values():
                control.blockSignals(False)
        self.edited()

    def open_file(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Open radio preset", "", "JSON (*.json)")
        if path:
            try:
                values = json.loads(Path(path).read_text(encoding="utf-8"))
                if not isinstance(values, dict):
                    raise ValueError("Radio preset must contain a JSON object")
                levels = normalize_log(values.pop("log", DEFAULT_LOG))
                packet = RadioTxTestConfigPacket(**values)
                errors = validate_radio_test(packet)
                if errors:
                    raise ValueError("\n".join(errors))
                self.apply_config(packet)
                self.set_log(levels, emit=True)
            except (OSError, ValueError, TypeError) as error:
                W.QMessageBox.warning(self, "Cannot open preset", str(error))

    def save_file(self):
        try:
            packet = self.collect_config()
            path, _ = W.QFileDialog.getSaveFileName(self, "Save radio preset", "radio.json", "JSON (*.json)")
            if path:
                Path(path).write_text(preset_json(packet, self.log), encoding="utf-8")
        except (OSError, ValueError) as error:
            W.QMessageBox.warning(self, "Cannot save preset", str(error))

    def set_log(self, value, *, emit=False):
        self.log = normalize_log(value)
        if emit:
            self.log_changed.emit(dict(self.log))
