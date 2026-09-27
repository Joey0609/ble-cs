"""Live and recorded radio RX diagnostics."""
import math
from pathlib import Path

import h5py
from PyQt6 import QtCore, QtWidgets as W
import pyqtgraph as pg

from ..protocol.packets import RadioTestStatsPacket
from ..radio_results import RadioResultStore


class RadioResultsWidget(W.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = RadioResultStore()
        self.dirty = True
        self.running = False
        layout = W.QVBoxLayout(self)
        bar = W.QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(5)
        # Open capture and Clear are session toolbar actions; what is left here
        # is the analysis setting of this view.
        radio_controls = W.QWidget()
        radio_bar = W.QHBoxLayout(radio_controls)
        radio_bar.setContentsMargins(0, 0, 0, 0)
        radio_bar.setSpacing(5)
        self.expected_rate = W.QDoubleSpinBox(minimum=0, maximum=1e9, decimals=2, suffix=" packets/s")
        self.expected_rate.setSpecialValueText("Unknown (drop estimate unavailable)")
        self.expected_rate.setToolTip("Known TX rate during this RX observation window. For sweeps, use the rate actually expected while listening, not total transmitter traffic.")
        self.expected_rate.valueChanged.connect(self.mark_dirty)
        radio_bar.addWidget(W.QLabel("Expected TX rate:"))
        radio_bar.addWidget(self.expected_rate)
        bar.addWidget(radio_controls)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.summary = W.QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("background: #e4edf8; padding: 6px 10px; font-size: 13px;")
        note = W.QLabel("Drops are estimates: max(0, expected TX − valid RX − CRC failures). "
                        "CRC failures are measured; undetected loss requires a known TX rate. "
                        "Rates use host arrival times. Sweep intervals may span several channels.")
        note.setWordWrap(True)
        layout.addWidget(note)
        grid = W.QGridLayout()
        layout.addLayout(grid, 1)
        self.curves = {}
        self.plots = {}
        specs = (("rssi", "RSSI", "dBm"), ("received_rate", "Valid RX rate", "packets/s"),
                 ("crc_percent", "CRC failure rate", "%"), ("missing", "Estimated undetected drops", "packets/s"),
                 ("received", "Cumulative valid RX / CRC errors", "packets"), ("channel", "Reported channel", "channel"))
        for i, (key, title, unit) in enumerate(specs):
            plot = pg.PlotWidget(background="white", title=title)
            plot.setLabel("bottom", "Host elapsed time", units="s")
            axis_label = {"rssi": "RSSI", "received_rate": "Valid RX", "crc_percent": "CRC failures",
                          "missing": "Estimated drops", "received": "Count", "channel": "Channel"}[key]
            plot.setLabel("left", axis_label, units=unit)
            self.plots[key] = plot
            plot.showGrid(x=True, y=True, alpha=.15)
            plot.addLegend()
            self.curves[key] = plot.plot(name="Valid RX" if key == "received" else title, pen=pg.mkPen("#2274a5", width=2), connect="finite")
            if key == "received":
                self.curves["crc_errors"] = plot.plot(name="CRC errors", pen="#d1495b")
            grid.addWidget(plot, i // 2, i % 2)
        interval_plot = pg.PlotWidget(background="white", title="Report interval")
        interval_plot.setLabel("bottom", "Host elapsed time", units="s")
        interval_plot.setLabel("left", "Interval", units="s")
        self.plots["interval"] = interval_plot
        self.curves["interval"] = interval_plot.plot(pen="#8055aa", connect="finite")
        grid.addWidget(interval_plot, 3, 0, 1, 2)
        layout.addWidget(self.summary)
        self.timer = QtCore.QTimer(self, interval=200)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def set_running(self, running):
        """A live run owns the view; the toolbar locks capture replacement and clearing."""
        self.running = bool(running)

    def mark_dirty(self, *_):
        self.dirty = True

    def clear(self):
        self.store.clear()
        self.mark_dirty()
        self.refresh()

    def add_packet(self, packet, timestamp=None):
        if self.store.add(packet, timestamp) is not None:
            self.mark_dirty()

    def refresh(self):
        if not self.dirty:
            return
        self.dirty = False
        samples = list(self.store.samples)
        times = [s.t for s in samples]
        expected = self.expected_rate.value()
        for key, curve in self.curves.items():
            values = [s.estimated_missing_rate(expected) if key == "missing" else getattr(s, key) for s in samples]
            curve.setData(times, values)
            if key in self.plots and key not in ("rssi", "channel"):
                # Include zero so floating-point noise never looks like a rate spike.
                finite = [v for v in values if math.isfinite(v)]
                if key == "received":
                    finite.extend(s.crc_errors for s in samples)
                self.plots[key].setYRange(0, max(finite, default=0) * 1.1 or 1, padding=0)
        if not samples:
            self.summary.setText("Waiting for RADIO_TEST_STATS. Current firmware needs the RX reporting extension; TX tests produce no RX statistics.")
            return
        last = samples[-1]
        missing = last.estimated_missing_rate(expected)
        drops = f"{missing:.1f}/s estimated" if math.isfinite(missing) else "unavailable"
        rssi = f"{last.rssi:g} dBm" if math.isfinite(last.rssi) else "unavailable"
        self.summary.setText(f"Valid RX: {last.received:,} · CRC failures: {last.crc_errors:,} · RSSI: {rssi} · "
                             f"Channel: {last.channel} · Undetected drops: {drops} · Counter resets: {self.store.resets} · "
                             f"Last interval: {last.interval:.3g} s · Showing last {len(samples):,} reports")

    def load_recording(self, path):
        # Build before replacing the current view so a bad file keeps live data.
        store = RadioResultStore()
        with h5py.File(path, "r") as file:
            if "radio_test/stats" not in file:
                raise ValueError("Recording contains no radio RX statistics")
            for row in file["radio_test/stats"]:
                store.add(RadioTestStatsPacket(*(int(row[k]) for k in
                          ("packets_received", "crc_errors", "rssi_dbm", "channel"))), float(row["t_host"]))
        self.store = store
        self.mark_dirty()
        self.refresh()

    def open_capture(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Open capture", "", "HDF5 (*.h5 *.hdf5)")
        if path:
            try:
                self.load_recording(Path(path))
            except (OSError, ValueError, KeyError, TypeError) as error:
                W.QMessageBox.warning(self, "Cannot open capture", str(error))
