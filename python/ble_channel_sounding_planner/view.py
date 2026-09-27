"""Planner window contents: controls, timing and channel plots (PyQt6 / PyQtGraph).

Mirrors the planner of the ble-channel-sounding Configuration tab without its device-link parts
(controller packets, FAE reports).
"""

from dataclasses import replace
from html import escape
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg

from .export_c import (HOST_DEFAULTS, TONE_ANTENNA_COUNTS, document, generate, load_document, standalone_host_settings,
                        validate_device_name)
from .channels import ALLOWED_CHANNELS, channel_map_bytes, enabled_channels
from .model import (ANTENNA_PATHS, ENHANCEMENTS_1_IPT, FCS_TIMES, IP_TIMES, MODES, ROLES, Scenario,
                    build_schedule, dumps, ipt_enabled, ipt_margin_us, loads, minimum_subevent_len,
                    step_segments, validate)
from .model import (CONDITIONAL_FIELDS, CONDITIONAL_HOST_FIELDS, apply_mode_defaults, inactive_fields, scenario_value, unused_host_fields)
from .control_help import (CHANNEL_CONTROL_HELP, CONNECTION_CONTROL_HELP, CONTROL_DETAILS, CS_CONTROL_HELP,
                           CONTROLLER_SELECTED_NOTE, EXAMPLE_CONTROL_HELP, HOST_CONTROL_HELP, ROLE_HELP,
                           SCHEDULE_CONTROL_HELP, TIMING_MANDATORY_VALUES, detail_html, tab_html)
from . import icons
from .tooltips import show_tooltip

COLORS = {0: "#8b75cb", 1: "#398bcc", 2: "#209f91", 3: "#db9540"}
IPT_TONE_COLOR = "#b4539a"  # reflector tones pre-rotated by the measured phase
MODE_HELP = {
    0: "Frequency/timing calibration for the measurements in this subevent.",
    1: "Reciprocal CS_SYNC packets for round-trip-time ranging (RTT).",
    2: "Reciprocal tones for phase-based ranging (PBR).",
    3: "Combined CS_SYNC packets and tones for RTT and PBR.",
}
SEGMENT_HELP = {
    "CS_SYNC": "Synchronization packet. Mode-1/3 may include the configured RTT sequence; Mode-0 does not.",
    "T_SW": "Antenna switching/settling period before the next phase measurement slot.",
    "T_GD": "Guard period between the CS_SYNC packet and tone structure.",
    "T_RD": "Ramp-down period for the transmitter to remove RF energy.",
    "T_FM": "Mode-0 frequency measurement tone used to estimate frequency offset.",
    "T_IP1": "Interlude between the initiator and reflector CS_SYNC exchanges.",
    "T_IP2": "Interlude between the initiator and reflector tone-bearing exchanges.",
    "T_SW_IPT": "IPT antenna switching period: replaces T_SW when IPT is enabled; the reflector's applied phase must settle within it.",
    "T_IP2 (IPT)": "Interlude from the reflector's IPT T_IP2 list. With T_RD it is the reflector's budget to measure, compute and apply each path's phase.",
    "Extension": "Reserved tone extension slot. It occupies time even when its randomized transmission is absent.",
}
# Common 20 MHz Wi-Fi channels, as (name, center MHz), for spectrum reference only.
WIFI_CHANNELS = (("Wi-Fi 1", 2412), ("Wi-Fi 6", 2437), ("Wi-Fi 11", 2462))

class TimeAxis(pg.AxisItem):
    """Keep exact selection boundaries visible alongside ordinary major ticks."""
    def __init__(self):
        self.bounds = None
        super().__init__(orientation="bottom")

    def tickValues(self, minimum, maximum, size):
        ticks = super().tickValues(minimum, maximum, size)
        if self.bounds is None or not ticks:
            return ticks
        span = maximum - minimum
        bounds = [x for x in self.bounds if minimum - 1e-8 <= x <= maximum + 1e-8]
        spacing, values = ticks[0]
        values = [x for x in values if all(abs(x - b) > span * .12 for b in bounds)]
        return [(spacing, sorted(set(values + bounds)))]

    def tickStrings(self, values, scale, spacing):
        return [f"{x * scale:.6f}".rstrip("0").rstrip(".") or "0" for x in values]

    def generateDrawSpecs(self, painter):
        specs = super().generateDrawSpecs(painter)
        if specs is None or self.bounds is None:
            return specs
        axis, ticks, labels = specs
        # AxisItem normally suppresses edge labels when their centered text
        # would overhang the plot. Place selection endpoint labels inside it.
        area = self.mapRectFromParent(self.geometry())
        minimum, maximum = self.range
        for value in self.bounds:
            if not minimum - 1e-8 <= value <= maximum + 1e-8:
                continue
            text = self.tickStrings([value], 1, 1)[0]
            labels = [entry for entry in labels if entry[2] != text]
            metrics = QtGui.QFontMetricsF(painter.font())
            width, height = metrics.horizontalAdvance(text) + 4, metrics.height()
            x = area.left() + (value - minimum) / max(1e-12, maximum - minimum) * area.width()
            left = min(max(x - width / 2, area.left() + 3), area.right() - width - 3)
            y = area.top() + max(0, self.style["tickLength"]) + self.style["tickTextOffset"][1]
            rect = QtCore.QRectF(left, y, width, height)
            labels.append((rect, QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop, text))
        return axis, ticks, labels


class Block(pg.GraphicsObject):
    """Time-scaled, clickable block with a label that appears when it fits."""
    def __init__(self, x, width, row, label, color, detail="", action=None):
        super().__init__()
        self.rect = QtCore.QRectF(x, row - .28, width, .56)
        self.label, self.color, self.action = label, color, action
        self.shown_tooltip = None
        self.setToolTip(detail or label)
        self.setAcceptHoverEvents(True)
        if action:
            self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

    def boundingRect(self):
        return self.rect

    def paint(self, painter, option, widget=None):
        painter.setPen(pg.mkPen(self.color, width=1))
        painter.setBrush(pg.mkBrush(self.color))
        painter.drawRect(self.rect)
        # Labels use screen pixels, while the rectangle remains time-scaled.
        screen = painter.worldTransform().mapRect(self.rect).normalized()
        painter.save()
        painter.resetTransform()
        font = QtGui.QFont("Arial", 10)
        painter.setFont(font)
        if screen.width() > QtGui.QFontMetricsF(font).horizontalAdvance(self.label) + 12:
            painter.setPen(QtGui.QColor("#ffffff"))
            painter.drawText(screen, QtCore.Qt.AlignmentFlag.AlignCenter, self.label)
        painter.restore()

    def mouseClickEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if self.action:
                W.QToolTip.hideText()
                self.action()
            else:
                self.shown_tooltip = show_tooltip(event.screenPos().toPoint(), self.toolTip(), self.getViewWidget())
            event.accept()
        else:
            event.ignore()

    def hoverEvent(self, event):
        # PyQtGraph dispatches its own hover events. Explicitly show the Qt
        # tooltip instead of relying on the platform's GraphicsView help event.
        if event.isExit():
            if W.QToolTip.text() == self.shown_tooltip:
                W.QToolTip.hideText()
        elif event.acceptClicks(QtCore.Qt.MouseButton.LeftButton):
            self.shown_tooltip = show_tooltip(event.screenPos().toPoint(), self.toolTip(), self.getViewWidget())


class LanePlot(pg.PlotWidget):
    """Labeled horizontal lanes of Block items along a pannable x-axis."""
    def __init__(self, rows, **kwargs):
        super().__init__(background="white", **kwargs)
        self.rows = rows
        self.getAxis("bottom").enableAutoSIPrefix(False)
        self.getAxis("left").setTicks([list(enumerate(rows))])
        self.getAxis("left").setWidth(120)
        self.setYRange(-.7, len(rows) - .3, padding=0)
        self.setMouseEnabled(x=True, y=False)
        self.showGrid(x=True, y=False, alpha=.12)
        self.hideButtons()
        self.setMinimumHeight(170)


class Timeline(LanePlot):
    def __init__(self, rows, microseconds=False):
        super().__init__(rows, axisItems={"bottom": TimeAxis()})
        self.scale = 1 if microseconds else 1000
        self.time_origin = "first ACL anchor"
        self.setLabel("bottom", "Time since first ACL anchor", units="µs" if microseconds else "ms")

    def block(self, start, duration, row, label, color, detail="", action=None, timing_duration=None):
        described_duration = duration if timing_duration is None else timing_duration
        timing = (f"Start: {start:g} µs ({start / 1000:g} ms)<br>"
                  f"End: {start + described_duration:g} µs ({(start + described_duration) / 1000:g} ms)<br>"
                  f"Duration: {described_duration:g} µs<br>Time origin: {self.time_origin}.")
        tooltip = (f"<b>{escape(label or 'ACL anchor')}</b><br>"
                   f"{escape(detail or label)}<br><br>{timing}" +
                   ("<br><i>Click to inspect.</i>" if action else ""))
        item = Block(start / self.scale, duration / self.scale, row, label, color, tooltip, action)
        self.addItem(item)
        return item

    def anchor(self, time, label=None):
        self.addItem(pg.InfiniteLine(time / self.scale, pen=pg.mkPen("#d4dce6", style=QtCore.Qt.PenStyle.DashLine)))

    def fit(self, start, end, exact=False):
        bounds = (start / self.scale, max(start + 1, end) / self.scale)
        axis = self.getAxis("bottom")
        axis.bounds = bounds if exact else None
        axis.picture = None
        axis.update()
        self.setXRange(*bounds, padding=0 if exact else .025)


class SpectrumPlot(LanePlot):
    def __init__(self, rows):
        super().__init__(rows)
        self.setLabel("bottom", "Frequency", units="MHz")

    def block(self, low_mhz, width_mhz, row, label, color, detail, action=None):
        tooltip = (f"<b>{escape(label)}</b><br>{escape(detail)}<br><br>"
                   f"From {low_mhz:g} MHz to {low_mhz + width_mhz:g} MHz" +
                   ("<br><i>Click to toggle.</i>" if action else ""))
        item = Block(low_mhz, width_mhz, row, label, color, tooltip, action)
        self.addItem(item)
        return item

    def fit(self):
        self.setXRange(2400, 2481, padding=0)


class HopPlot(pg.PlotWidget):
    """Example channel of every step, against the step index within the procedure."""
    def __init__(self):
        super().__init__(background="white")
        self.setLabel("bottom", "Step index in procedure")
        self.setLabel("left", "CS channel")
        self.getAxis("left").setWidth(120)
        self.showGrid(x=False, y=True, alpha=.12)
        self.hideButtons()
        self.setMinimumHeight(220)


class ChannelMapEditor(W.QWidget):
    """Toggle grid and hex entry for the 10-byte CS channel map.

    The raw bytes are kept as given, so imported reserved bits or a wrong length
    stay visible to validation instead of being silently repaired.
    """
    changed = QtCore.pyqtSignal()
    PRESETS = (("All", ALLOWED_CHANNELS), ("Even", tuple(ch for ch in ALLOWED_CHANNELS if ch % 2 == 0)),
               ("Odd", tuple(ch for ch in ALLOWED_CHANNELS if ch % 2)), ("None", ()))

    def __init__(self, tip=""):
        super().__init__()
        self.map = bytes(10)
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        presets = W.QHBoxLayout()
        for title, channels in self.PRESETS:
            button = W.QPushButton(title)
            button.setToolTip(f"Enable {title.lower()} allowed CS channels ({len(channels)}).")
            button.clicked.connect(lambda _=False, chs=channels: self.set_map(channel_map_bytes(chs)))
            presets.addWidget(button)
        layout.addLayout(presets)
        grid = W.QGridLayout()
        grid.setSpacing(2)
        grid.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.buttons = {}
        for ch in range(79):
            button = W.QToolButton()
            button.setObjectName("channel")
            button.setText(str(ch))
            button.setCheckable(True)
            button.setFixedSize(32, 22)
            allowed = ch in ALLOWED_CHANNELS
            button.setEnabled(allowed)
            button.setToolTip(f"Channel {ch} · {2402 + ch} MHz" + ("" if allowed else " · reserved, never used for CS"))
            button.clicked.connect(lambda _=False, c=ch: self.toggle(c))
            grid.addWidget(button, ch // 10, ch % 10)
            self.buttons[ch] = button
        layout.addLayout(grid)
        self.hex = W.QLineEdit()
        self.hex.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont))
        self.hex.setToolTip("10 bytes as 20 hexadecimal characters, least-significant byte (channels 0–7) first, as in planner JSON.")
        # Apply a complete map while typing too: Save/Open buttons do not take focus
        # on macOS, so editingFinished alone would drop a typed map.
        self.hex.textEdited.connect(self.hex_edited)
        self.hex.editingFinished.connect(self.hex_edited)
        layout.addWidget(self.hex)
        self.summary = W.QLabel()
        layout.addWidget(self.summary)
        self.setToolTip(tip)

    def value(self):
        return self.map

    def setValue(self, value):
        self.map = bytes(value)
        bits = int.from_bytes(self.map, "little")
        for ch, button in self.buttons.items():
            button.setChecked(bool(bits >> ch & 1))
        if self.hex.text().strip().lower() != self.map.hex():
            self.hex.setText(self.map.hex())
        self.hex.setStyleSheet("")
        channels = enabled_channels(self.map)
        allowed = sum(1 for ch in channels if ch in ALLOWED_CHANNELS)
        reserved = len(channels) - allowed
        self.summary.setText(f"{allowed} of {len(ALLOWED_CHANNELS)} channels enabled" +
                             (f" · {reserved} reserved bit(s) set" if reserved else ""))

    def set_map(self, value):
        self.setValue(value)
        self.changed.emit()

    def toggle(self, ch):
        if not self.isEnabled():  # also reached from the spectrum plot while the settings are locked
            return
        bits = int.from_bytes(self.map, "little") ^ (1 << ch)
        self.set_map(bits.to_bytes(max(10, len(self.map)), "little"))

    def hex_edited(self, *_):
        text = self.hex.text().strip()
        try:
            value = bytes.fromhex(text)
        except ValueError:
            value = b""
        if len(value) != 10:
            self.hex.setStyleSheet("border: 1px solid #b44136;")
            return
        if value != self.map:
            self.set_map(value)


class PeerAntennaEditor(W.QWidget):
    """Check boxes for the preferred peer antenna mask: peer antennas 1–4 are bits 0–3.

    Takes QSpinBox's place: value(), setValue() and valueChanged, emitted only on a change.
    Bits above 3 in a loaded mask are kept, so validation still reports them.
    """
    valueChanged = QtCore.pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.mask, self.needed = 0, 0
        layout = W.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.boxes = []
        for bit in range(4):
            box = W.QCheckBox(f"ANT{bit + 1}")
            box.toggled.connect(self.box_toggled)
            layout.addWidget(box)
            self.boxes.append(box)
        self.summary = W.QLabel()
        layout.addWidget(self.summary)
        layout.addStretch()
        self.update_summary()

    def value(self):
        return self.mask

    def setValue(self, value):
        value = int(value)
        for bit, box in enumerate(self.boxes):
            with QtCore.QSignalBlocker(box):
                box.setChecked(bool(value >> bit & 1))
        changed, self.mask = value != self.mask, value
        self.update_summary()
        if changed:
            self.valueChanged.emit(value)

    def box_toggled(self, *_):
        low = sum(1 << bit for bit, box in enumerate(self.boxes) if box.isChecked())
        self.setValue(self.mask & ~0x0F | low)

    def set_needed(self, needed):
        """Show a warning while fewer than needed peer antennas are checked."""
        self.needed = needed
        self.update_summary()

    def update_summary(self):
        bits = bin(self.mask & 0x0F).count("1")
        short = self.isEnabled() and bits < self.needed
        self.summary.setText(f"0x{self.mask:02x}" + (f" · set at least {self.needed}" if short else ""))
        self.summary.setStyleSheet("color: #b44136;" if short or self.mask & ~0x0F else "")

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.EnabledChange:
            self.update_summary()


class HelpEvents(QtCore.QObject):
    """Event filter reporting the help key of a widget the user selects or rests the pointer on."""
    requested = QtCore.pyqtSignal(str)
    SELECTING = (QtCore.Qt.FocusReason.MouseFocusReason, QtCore.Qt.FocusReason.TabFocusReason,
                 QtCore.Qt.FocusReason.BacktabFocusReason, QtCore.Qt.FocusReason.ShortcutFocusReason)

    def __init__(self, parent, rest_ms=400):
        super().__init__(parent)
        self.key = None
        # A short rest before hover help, so passing over controls does not switch the pane.
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(rest_ms)
        self.timer.timeout.connect(self.rested)

    def watch(self, widget, key):
        widget.setProperty("help_key", key)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        key = obj.property("help_key")
        kind = event.type()
        # Focus that follows a tab switch or window activation is not a selection.
        if kind == QtCore.QEvent.Type.FocusIn and event.reason() in self.SELECTING:
            self.timer.stop()
            self.requested.emit(key)
        elif kind == QtCore.QEvent.Type.Enter:
            self.key = key
            self.timer.start()
        elif kind == QtCore.QEvent.Type.Leave and key == self.key:
            self.timer.stop()
        return False

    def rested(self):
        self.requested.emit(self.key)


class PlannerWidget(W.QWidget):
    status_message = QtCore.pyqtSignal(str, int)
    configuration_changed = QtCore.pyqtSignal()
    populated = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.scenario = Scenario()
        self.host_settings = {**HOST_DEFAULTS, "peripheral_patterns": []}
        self.schedule = build_schedule(self.scenario)
        self.controls = {}
        self.help_rows = {}  # key: (label, tooltip, control) for the help pane
        self.loading = False
        self.host_controls = {}
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #f4f7fb; color: #21334b; font-size: 12px; }
            QLineEdit, QSpinBox, QComboBox { background: white; border: 1px solid #cbd5e1;
                border-radius: 4px; padding: 5px; min-height: 20px; }
            QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QPlainTextEdit:disabled {
                background: #e9eef4; color: #8a9bb0; }
            QPushButton { background: #e6edf7; border: 1px solid #cad6e6; border-radius: 5px; padding: 7px 12px; }
            QPushButton:hover { background: #d7e6f7; }
            QTabWidget::pane { border: 1px solid #d5dfe9; background: white; }
            QTabBar::tab { padding: 10px 13px; }
            QTabBar::tab:selected { background: white; color: #146fba; }
            QGroupBox { font-weight: bold; margin-top: 14px; padding-top: 16px; }
            QGroupBox#example { background: #eef3f9; border: 1px dashed #aab8cb; border-radius: 5px;
                margin-top: 18px; padding: 18px 6px 6px 6px; }
            QGroupBox#example::title { subcontrol-origin: margin; left: 8px; color: #536981; }
            QGroupBox#example QLabel { font-weight: normal; }
            QTextBrowser { background: white; border: 1px solid #d5dfe9; padding: 8px; }
            QFrame#diagnostics { background: white; border: 1px solid #cbd8e6; border-radius: 4px; }
            QToolButton#diagnosticSummary { text-align: left; border: 0; border-radius: 3px; padding: 8px; }
            QToolButton#diagnosticToggle { border: 0; padding: 5px 9px; }
            QTextBrowser#diagnosticDetails { background: white; border: 0; border-top: 1px solid #d5dfe9; padding: 8px; }
            QToolTip { background: #fffdf1; color: #21334b; border: 1px solid #aab8cb; padding: 8px; }
            QToolButton#channel { background: white; border: 1px solid #cbd5e1; border-radius: 3px; font-size: 11px; }
            QToolButton#channel:checked { background: #209f91; color: white; border-color: #1a8074; }
            QToolButton#channel:disabled { background: #e9eef4; color: #aab8cb; }
        """)
        layout = W.QVBoxLayout(self)
        toolbar = W.QHBoxLayout()
        self.source = W.QLabel()
        toolbar.addStretch(1)
        self.target_mode = W.QComboBox()
        for role, name in ROLES.items():
            self.target_mode.addItem(name.removeprefix("CS ").capitalize() + " config", role)
        self.target_mode.setToolTip(ROLE_HELP)
        toolbar.addWidget(self.target_mode)
        toolbar.addStretch(1)
        self.action_toolbar = W.QToolBar("Planner actions")
        self.action_toolbar.setMovable(True)
        self.action_toolbar.setFloatable(True)
        self.action_toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.action_toolbar.setIconSize(QtCore.QSize(18, 18))
        toolbar.addWidget(self.action_toolbar)
        self.toolbar_buttons = {}
        icon_specs = (
            ("Open…", "open", self.open_file),
            ("Save…", "save", self.save_file),
            ("Export C configuration…", "export-code", self.export_c),
            ("Export view…", "export-image", self.export_view),
            ("Fit views", "fit", self.refresh),
            ("Reset", "reset", self.reset),
        )
        for index, (title, icon_name, callback) in enumerate(icon_specs):
            if index == 2 or index == 4:
                self.action_toolbar.addSeparator()
            action = QtGui.QAction(icons.icon(icon_name), title, self)
            action.setToolTip(title)
            action.setStatusTip(title)
            action.triggered.connect(callback)
            self.action_toolbar.addAction(action)
            self.toolbar_buttons[title] = action
        layout.addLayout(toolbar)
        split = W.QSplitter()
        layout.addWidget(split, 1)
        left = W.QSplitter(QtCore.Qt.Orientation.Vertical)
        split.addWidget(left)
        self.settings = W.QTabWidget()
        self.settings.setMinimumWidth(355)
        self.example_panels = []
        left.addWidget(self.settings)
        self.build_help(left)
        self.build_controls()
        # The operation mode is part of the scenario, so it is saved and restored with it.
        self.controls["configuration.role"] = self.target_mode
        self.register_help("configuration.role", "Operation mode", ROLE_HELP, self.target_mode)
        self.target_mode.currentIndexChanged.connect(self.edited)
        self.build_host_controls()
        for key in ("configuration.mode", "configuration.cs_enhancements_1", "configuration.channel_selection_type",
                    "procedure.tone_antenna_config_selection"):
            self.controls[key].currentIndexChanged.connect(self.update_mode_controls)
        self.controls["procedure.subevents_per_event"].valueChanged.connect(self.update_mode_controls)
        self.target_mode.currentIndexChanged.connect(self.update_mode_controls)
        right = W.QWidget()
        right_layout = W.QVBoxLayout(right)
        self.metrics = W.QToolButton()
        self.metrics.setObjectName("diagnosticSummary")
        self.metrics.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.metrics.setAutoRaise(False)
        self.metrics.setSizePolicy(W.QSizePolicy.Policy.Expanding, W.QSizePolicy.Policy.Fixed)
        self.metrics.clicked.connect(self.toggle_diagnostics)
        self._diagnostics_expanded = False
        self._diagnostics_had_error = False
        nav = W.QHBoxLayout()
        self.procedure_select = W.QComboBox()
        self.event_select, self.subevent_select, self.step_select = (W.QComboBox() for _ in range(3))
        self.selection_label = W.QLabel("Select a procedure, event, subevent, or step in the preview")
        self.selection_label.setToolTip("Click a procedure, event, subevent, or step in the preview to inspect it.")
        self.selection_label.setStyleSheet("color: #536981; padding: 6px 10px; background: #eef3f9; border: 1px solid #d5dfe9;")
        nav.addWidget(self.selection_label, 1)
        self.event_select.currentIndexChanged.connect(self.event_changed)
        self.procedure_select.currentIndexChanged.connect(self.event_changed)
        self.subevent_select.currentIndexChanged.connect(self.subevent_changed)
        self.step_select.currentIndexChanged.connect(self.draw_step)
        right_layout.addLayout(nav)
        self.views = W.QTabWidget()
        right_layout.addWidget(self.views, 1)
        self.connection_plot = Timeline(["Peripheral example", "Central / anchors", "Selected CS"])
        self.timeout_plot = Timeline(["No valid reception"])
        self.timeout_plot.time_origin = "last valid reception (hypothetical silence)"
        self.timeout_plot.setLabel("bottom", "Time since last valid reception", units="ms")
        self.procedure_plot = Timeline(["Procedure instances", "CS events", "ACL anchors"])
        self.event_plot = Timeline(["Reserved subevent", "Occupied", "Mode 0", "Mode 1", "Mode 2", "Mode 3"])
        self.step_plot = Timeline(["Timing", "Reflector TX", "Initiator TX"], True)
        self.connection_info = self.view_page(
            "1  Connection", self.connection_plot, self.timeout_plot,
            footer="The upper timeline shows the first 12 ACL anchor positions. The lower timeline explains timeout from a hypothetical last valid reception at t = 0.",
        )
        self.procedure_info = self.view_page("2  Procedures", self.procedure_plot)
        self.event_info = self.view_page("3  Events && subevents", self.event_plot)
        self.step_info = self.view_page("4  Individual step", self.step_plot)
        self.hop_plot = HopPlot()
        self.channel_plot = SpectrumPlot(["Wi-Fi reference", "CS channels"])
        self.channel_info = self.view_page("5  Channels", self.hop_plot, self.channel_plot)
        self.details = W.QTextBrowser()
        self.details.setObjectName("diagnosticDetails")
        self.details.setMaximumHeight(150)
        self.details.setReadOnly(True)
        self.details.setFrameShape(W.QFrame.Shape.NoFrame)
        self.details.setVisible(False)
        split.addWidget(right)
        split.setSizes([395, 1045])
        summary = W.QWidget()
        summary_layout = W.QVBoxLayout(summary)
        summary_layout.setContentsMargins(0, 4, 0, 0)
        summary_layout.setSpacing(4)
        diagnostics = W.QFrame()
        diagnostics.setObjectName("diagnostics")
        diagnostics_layout = W.QVBoxLayout(diagnostics)
        diagnostics_layout.setContentsMargins(0, 0, 0, 0)
        diagnostics_layout.setSpacing(0)
        status_row = W.QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        self.diagnostics_toggle = W.QToolButton()
        self.diagnostics_toggle.setObjectName("diagnosticToggle")
        self.diagnostics_toggle.setText("▼")
        self.diagnostics_toggle.setToolTip("Expand or collapse processed timing diagnostics")
        self.diagnostics_toggle.setAutoRaise(True)
        self.diagnostics_toggle.clicked.connect(self.toggle_diagnostics)
        status_row.addWidget(self.metrics, 1)
        status_row.addWidget(self.diagnostics_toggle)
        diagnostics_layout.addLayout(status_row)
        diagnostics_layout.addWidget(self.details)
        summary_layout.addWidget(diagnostics)
        layout.addWidget(summary)
        left.setSizes([560, 240])
        self.settings.currentChanged.connect(self.show_tab_help)
        self.show_tab_help()
        self.status_message.emit("Scroll to zoom • drag to pan • click a block to inspect • right-click for plot tools", 0)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.recalculate)
        self.populate()

    def view_page(self, title, *plots, footer=None):
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        info = W.QLabel()
        info.setWordWrap(True)
        info.setStyleSheet("padding: 10px; background: white;")
        layout.addWidget(info)
        for plot in plots:
            layout.addWidget(plot, 3 if plot is plots[0] else 1)
        if footer:
            label = W.QLabel(footer)
            label.setWordWrap(True)
            label.setStyleSheet("color: #536981; padding: 8px 10px; background: #eef3f9;")
            layout.addWidget(label)
        self.views.addTab(page, title)
        return info

    def form(self, title):
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        content = W.QWidget()
        form = W.QFormLayout(content)
        form.setFieldGrowthPolicy(W.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        scroll.setWidget(content)
        self.settings.addTab(scroll, title)
        return form

    def field(self, form, key, label, minimum=0, maximum=65535, suffix="", choices=None, tip=""):
        tip = tip or next(texts[key] for texts in (CONNECTION_CONTROL_HELP, CS_CONTROL_HELP, SCHEDULE_CONTROL_HELP,
                                                   CHANNEL_CONTROL_HELP, EXAMPLE_CONTROL_HELP) if key in texts)
        if choices is not None:
            widget = W.QComboBox()
            for value, text in choices:
                widget.addItem(text, value)
            widget.currentIndexChanged.connect(self.edited)
        else:
            widget = W.QSpinBox()
            widget.setRange(minimum, maximum)
            widget.setSuffix(suffix)
            widget.valueChanged.connect(self.edited)
        self.add_row(form, key, label, widget, tip)
        self.controls[key] = widget

    def add_row(self, form, key, label, widget, tip):
        """Add a labeled row whose label, control and combo options all show tip, and whose help entry is key."""
        text = W.QLabel(label)
        for target in (text, widget):
            target.setToolTip(tip)
        if isinstance(widget, W.QSpinBox):
            widget.lineEdit().setToolTip(tip)
        elif isinstance(widget, W.QComboBox) and tip:
            for i in range(widget.count()):
                widget.setItemData(i, f"{widget.itemText(i)}\n\n{tip}", QtCore.Qt.ItemDataRole.ToolTipRole)
        form.addRow(text, widget)
        self.register_help(key, label, tip, widget, text)

    def build_help(self, splitter):
        """Help pane below the settings: an overview of the current tab and the detailed entry of one setting."""
        self.help_pane = W.QTabWidget()
        self.tab_help, self.setting_help = W.QTextBrowser(), W.QTextBrowser()
        for browser, title in ((self.tab_help, "About this tab"), (self.setting_help, "Setting details")):
            browser.setOpenLinks(False)
            browser.anchorClicked.connect(self.help_link_clicked)
            self.help_pane.addTab(browser, title)
        splitter.addWidget(self.help_pane)
        self.help_events = HelpEvents(self)
        self.help_events.requested.connect(self.show_setting_help)

    def register_help(self, key, label, tip, control, *widgets):
        """Show the help entry of key when control or one of widgets is hovered or selected."""
        if key not in CONTROL_DETAILS:
            raise KeyError(f"No detailed help for {key}")
        self.help_rows[key] = (label, tip, control)
        extra = (control.lineEdit(),) if isinstance(control, W.QSpinBox) else ()
        extra += tuple(control.boxes) if isinstance(control, PeerAntennaEditor) else ()
        for widget in (control, *widgets, *extra):
            self.help_events.watch(widget, key)

    def help_link_clicked(self, url):
        self.show_setting_help(url.fragment())

    def show_tab_help(self, *_):
        """Show the overview of the current settings tab."""
        page = self.settings.currentWidget()
        settings = [(key, label) for key, (label, _, control) in self.help_rows.items()
                    if page is not None and page.isAncestorOf(control) and not control.isHidden()]
        self.tab_help.setHtml(tab_html(self.settings.tabText(self.settings.currentIndex()), settings))
        self.help_pane.setCurrentWidget(self.tab_help)

    def show_setting_help(self, key):
        """Show the detailed entry of setting key."""
        if key not in self.help_rows:
            return
        label, tip, control = self.help_rows[key]
        self.setting_help.setHtml(detail_html(key, label, tip, read_only=not control.isEnabled()))
        self.help_pane.setCurrentWidget(self.setting_help)

    def build_controls(self):
        f = self.form("Connection")
        self.field(f, "connection.interval_min", "Requested minimum", 6, 3200, " × 1.25 ms")
        self.field(f, "connection.interval_max", "Requested maximum", 6, 3200, " × 1.25 ms")
        self.field(f, "connection.latency", "Peripheral latency", 0, 499, " events")
        self.field(f, "connection.timeout", "Supervision timeout", 10, 3200, " × 10 ms")
        n = self.example_panel(f)
        self.field(n, "connection.interval", "Selected interval", 6, 3200, " × 1.25 ms")
        self.field(n, "connection.activity_us", "ACL activity example", 0, 100000, " µs")
        self.field(n, "event_offset_us", "CS offset from anchor", 0, 4000000, " µs")
        f = self.form("CS modes")
        self.field(f, "configuration.mode", "Mode combination", choices=list(MODES.items()))
        self.field(f, "configuration.mode_0_steps", "Mode-0 prefix", 1, 3, " steps")
        self.field(f, "configuration.main_mode_repetition", "Repeat previous main", 0, 3, " steps")
        self.field(f, "configuration.min_main_mode_steps", "Minimum main run", 1, 255)
        self.field(f, "configuration.max_main_mode_steps", "Maximum main run", 1, 255)
        self.field(f, "configuration.cs_sync_phy", "CS_SYNC PHY", choices=[(1, "LE 1M"), (2, "LE 2M"), (3, "LE 2M 2BT")])
        self.field(f, "configuration.rtt_type", "RTT sequence", choices=list(enumerate(["AA only", "32-bit sounding", "96-bit sounding", "32-bit random", "64-bit random", "96-bit random", "128-bit random"])))
        self.field(f, "procedure.tone_antenna_config_selection", "Antenna configuration", choices=list(enumerate(["A1:B1", "A2:B1", "A3:B1", "A4:B1", "A1:B2", "A1:B3", "A1:B4", "A2:B2"])))
        self.field(f, "configuration.cs_enhancements_1", "Inline PCT transfer (IPT)",
                   choices=[(0, "Off"), (ENHANCEMENTS_1_IPT, "Requested")])
        n = self.example_panel(f)
        self.field(n, "main_steps", "Illustrative main run", 1, 255)
        for name, label, values in (("t_ip1_time_us", "T_IP1", IP_TIMES), ("t_ip2_time_us", "T_IP2", IP_TIMES), ("t_fcs_time_us", "T_FCS", FCS_TIMES), ("t_pm_time_us", "T_PM", (10, 20, 40))):
            key = "configuration." + name
            mandatory = TIMING_MANDATORY_VALUES[key]
            self.field(n, key, label, choices=[(v, f"{v} µs" + (" (mandatory)" if f"{v} µs" == mandatory else "")) for v in values])
        self.field(n, "t_sw_us", "T_SW", choices=[(v, f"{v} µs") for v in (0, 1, 2, 4, 10)])
        self.field(n, "t_sw_ipt_us", "T_SW_IPT", choices=[(v, f"{v} µs") for v in (0, 1, 2, 4, 10)])
        f = self.form("Schedule")
        self.field(f, "procedure.subevent_len", "Subevent budget", 1250, 4000000, " µs")
        self.controls["procedure.subevent_len"].setSingleStep(1000)
        self.subevent_minimum = W.QLabel()
        self.subevent_minimum.setWordWrap(True)
        self.subevent_minimum.setStyleSheet("color: #536981;")
        f.addRow("", self.subevent_minimum)
        self.field(f, "procedure.max_procedure_len", "Procedure budget", 1, 65535, " × 625 µs")
        self.field(f, "procedure.procedure_interval", "Procedure spacing", 1, 65535, " ACL intervals")
        self.field(f, "procedure.procedure_count", "Procedure count", 0, 65535)
        n = self.example_panel(f)
        self.field(n, "target_steps", "Fresh-step workload", 1, 256, " steps")
        self.field(n, "procedure.subevents_per_event", "Subevents / event", 1, 32)
        self.field(n, "procedure.subevent_interval", "Subevent spacing", 0, 65535, " × 625 µs")
        self.field(n, "procedure.event_interval", "CS event spacing", 1, 65535, " ACL intervals")
        self.field(n, "preview_count", "Preview instances", 1, 10)
        f = self.form("Channels")
        editor = ChannelMapEditor(CHANNEL_CONTROL_HELP["configuration.channel_map"])
        editor.changed.connect(self.edited)
        label = W.QLabel("Channel map")
        label.setToolTip(editor.toolTip())
        # Full-width rows: the channel grid does not fit beside a label.
        f.addRow(label)
        f.addRow(editor)
        self.controls["configuration.channel_map"] = editor
        self.register_help("configuration.channel_map", "Channel map", editor.toolTip(), editor, label, editor.hex)
        self.field(f, "configuration.channel_map_repetition", "Map repetition", 1, 255, " × map")
        self.field(f, "configuration.channel_selection_type", "Channel selection", choices=[(0, "CSA #3b"), (1, "CSA #3c")])
        self.field(f, "configuration.ch3c_shape", "#3c shape", choices=[(0, "Hat"), (1, "X")])
        # Wide range so controller-supplied #3b packets are not clamped; validation enforces 2–8 for #3c.
        self.field(f, "configuration.ch3c_jump", "#3c jump", 0, 255, " channels")
        n = self.example_panel(f)
        self.field(n, "channel_seed", "Example seed", 0, 2147483647)

    def build_host_controls(self):
        form = self.host_form = self.form("Host")
        choices = {
            "gap_role": [(0, "Central"), (1, "Peripheral")],
            "cs_sync_antenna_selection": [(1, "ANT1"), (2, "ANT2"), (3, "ANT3"), (4, "ANT4"),
                                           (254, "Repetitive"), (255, "No recommendation")],
            "phy": [(1, "LE 1M"), (2, "LE 2M"), (3, "LE Coded S8"), (4, "LE Coded S2")],
            "creation_context": [(0, "Local"), (1, "Local and remote")],
        }
        snr = [(v, f"{v * 3 + 18} dB") for v in range(5)] + [(255, "Not used")]
        choices.update(snr_control_initiator=snr, snr_control_reflector=snr)
        for name in HOST_DEFAULTS:
            if name in choices:
                control = W.QComboBox()
                for value, label in choices[name]:
                    control.addItem(label, value)
                if name == "gap_role":
                    peripheral_index = control.findData(1)
                    control.model().item(peripheral_index).setEnabled(False)
                    control.setItemData(
                        peripheral_index,
                        "Peripheral is retained for saved configurations but cannot be selected here.",
                        QtCore.Qt.ItemDataRole.ToolTipRole,
                    )
                control.currentIndexChanged.connect(self.host_edited)
            elif name == "preferred_peer_antenna":
                control = PeerAntennaEditor()
                control.valueChanged.connect(self.host_edited)
            else:
                control = W.QSpinBox()
                control.setRange(-127 if name == "max_tx_power" else -128 if name == "tx_power_delta" else 0,
                                 20 if name == "max_tx_power" else 127 if name == "tx_power_delta" else 15)
                control.valueChanged.connect(self.host_edited)
            self.host_controls[name] = control
            self.add_row(form, name, name.replace("_", " ").capitalize(), control, HOST_CONTROL_HELP[name])
        self.patterns = W.QPlainTextEdit()
        self.patterns.setPlaceholderText("Peripheral name prefixes, one per line (1–8)")
        self.patterns.setMaximumHeight(110)
        self.patterns.textChanged.connect(self.host_edited)
        self.add_row(form, "peripheral_patterns", "Peripheral prefixes", self.patterns, HOST_CONTROL_HELP["peripheral_patterns"])
        self.device_name = W.QLineEdit()
        self.device_name.setPlaceholderText("Firmware default (CS Client)")
        self.device_name.textChanged.connect(self.host_edited)
        self.add_row(form, "device_name", "Bluetooth name", self.device_name, HOST_CONTROL_HELP["device_name"])
        self.target_mode.currentIndexChanged.connect(self.host_edited)

    def example_panel(self, form):
        """Add the panel for example values the controller selects: editable, never sent or exported."""
        box = W.QGroupBox("Example config values selected by the controller")
        box.setObjectName("example")
        box.setToolTip(CONTROLLER_SELECTED_NOTE + " Other values in this panel are planner assumptions or examples. "
                       "The values are not sent to the client or exported to C, and are saved in planner files.")
        panel = W.QFormLayout(box)
        panel.setFieldGrowthPolicy(W.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow(box)
        self.example_panels.append(box)
        return panel

    def host_edited(self, *_):
        if self.loading:
            return
        for name, control in self.host_controls.items():
            self.host_settings[name] = control.currentData() if isinstance(control, W.QComboBox) else control.value()
        self.host_settings["peripheral_patterns"] = self.patterns.toPlainText().splitlines()
        self.host_settings["device_name"] = self.device_name.text()
        valid = not validate_device_name(self.device_name.text())
        self.device_name.setStyleSheet("" if valid else "border: 1px solid #b44136;")
        self.patterns.setEnabled(self.host_settings["gap_role"] == 0)
        self.configuration_changed.emit()

    def edited(self, *_):
        if not self.loading:
            # An explicit edit invalidates the saved range even if later reverted.
            sender = self.sender()
            for name in ("procedure_interval", "subevent_len"):
                if sender is self.controls.get("procedure." + name):
                    self.host_settings.pop("_selected_" + name, None)
            self.timer.start()
            self.configuration_changed.emit()

    def populate(self):
        self.loading = True
        # Fields the mode combination does not use always show their defaults.
        self.scenario = apply_mode_defaults(self.scenario)
        self.host_settings = {**self.host_settings, **{name: HOST_DEFAULTS[name] for name in
                              unused_host_fields(self.scenario.configuration.mode, self.scenario.configuration.role)}}
        for key, widget in self.controls.items():
            self.set_control_value(widget, scenario_value(self.scenario, key))
        for name, control in self.host_controls.items():
            self.set_control_value(control, self.host_settings[name])
        self.patterns.setPlainText("\n".join(self.host_settings.get("peripheral_patterns", [])))
        self.device_name.setText(self.host_settings.get("device_name") or "")
        self.patterns.setEnabled(self.host_settings["gap_role"] == 0)
        self.loading = False
        self.update_mode_controls()
        self.refresh()
        self.populated.emit()

    @staticmethod
    def set_control_value(widget, value):
        if isinstance(widget, W.QComboBox):
            index = widget.findData(value)
            if index < 0:
                # Keep imported values visible; validation explains why they are rejected.
                widget.addItem(f"Unknown ({value})", value)
                index = widget.count() - 1
            widget.setCurrentIndex(index)
        else:
            widget.setValue(value)

    def update_mode_controls(self, *_):
        """Hold the controls the selected modes do not use at their defaults, read-only.

        The rules are inactive_fields (mode combination, IPT, channel selection, subevents per
        event) and unused_host_fields (mode combination, operation mode).
        """
        scenario = self.read_controls()
        c = scenario.configuration
        inactive, unused_host = inactive_fields(scenario), unused_host_fields(c.mode, c.role)
        if not self.loading:
            for key, value in inactive.items():
                self.set_control_value(self.controls[key], value)
            for name in unused_host:
                self.set_control_value(self.host_controls[name], HOST_DEFAULTS[name])
        for key in CONDITIONAL_FIELDS:
            self.controls[key].setEnabled(key not in inactive)
        for name in CONDITIONAL_HOST_FIELDS:
            if name in self.host_controls:
                self.host_controls[name].setEnabled(name not in unused_host)
        # The peer's side of the antenna configuration: B for an initiator, A for a reflector.
        selection = scenario.procedure.tone_antenna_config_selection
        if 0 <= selection < len(TONE_ANTENNA_COUNTS):
            self.host_controls["preferred_peer_antenna"].set_needed(TONE_ANTENNA_COUNTS[selection][c.role != 1])

    def read_controls(self):
        groups = {"connection": {}, "configuration": {}, "procedure": {}}
        local = {}
        for key, widget in self.controls.items():
            value = widget.currentData() if isinstance(widget, W.QComboBox) else widget.value()
            if "." in key:
                group, name = key.split(".")
                groups[group][name] = value
            else:
                local[key] = value
        return replace(self.scenario, **{name: replace(getattr(self.scenario, name), **values) for name, values in groups.items()},
                       **local, provenance="Hypothetical configuration and schedule")

    def recalculate(self):
        self.scenario = self.read_controls()
        self.refresh()

    @staticmethod
    def set_options(widget, options):
        old = widget.currentData()
        widget.blockSignals(True)
        widget.clear()
        for text, value in options:
            widget.addItem(text, value)
        index = widget.findData(old)
        widget.setCurrentIndex(max(0, index) if widget.count() else -1)
        widget.blockSignals(False)

    def refresh(self):
        self.schedule = build_schedule(self.scenario)
        s, result = self.scenario, self.schedule
        try:
            minimum = minimum_subevent_len(s)
            self.subevent_minimum.setText(
                f"Calculated minimum for one fresh step, including the Mode-0 prefix: {minimum:,} µs")
        except (AttributeError, IndexError, KeyError, TypeError, ValueError):
            self.subevent_minimum.setText("Calculated minimum unavailable until mode and timing values are valid.")
        self.source.setText(s.provenance + "  •  timeline is a prediction")
        total = sum(len(se.steps) for se in result.subevents)
        status = "Fits workload" if result.complete else "Invalid timing" if result.errors else "Needs attention"
        summary_icon = "✓" if result.complete else "✕" if result.errors else "⚠"
        self.metrics.setText(f"{summary_icon} Processing complete · {status}   |   "
                             f"{result.completed_steps}/{result.target_steps} fresh steps   |   "
                             f"{len(result.subevents)} subevents / {result.event_count} CS events   |   "
                             f"{result.duration / 1000:.3f} ms elapsed   |   {total} total steps")
        if result.errors:
            self.metrics.setStyleSheet("background: #fde8e7; color: #9f2f28; border: 1px solid #e3aaa5; padding: 0 8px;")
        elif result.complete:
            self.metrics.setStyleSheet("background: #e6f4ea; color: #23643a; border: 1px solid #afd5ba; padding: 0 8px;")
        else:
            self.metrics.setStyleSheet("background: #fff3d6; color: #805b13; border: 1px solid #e5c47b; padding: 0 8px;")
        if result.errors:
            self.set_diagnostics_expanded(True)
        elif self._diagnostics_had_error:
            self.set_diagnostics_expanded(False)
        self._diagnostics_had_error = bool(result.errors)
        def diagnostic(text, icon, color):
            message, _, correction = text.partition("\nCorrect: ")
            body = (f'<div style="margin:2px 0"><span style="color:{color}; font-size:15px">{icon}</span> '
                    f'<b style="color:{color}">{escape(message)}</b>')
            if correction:
                body += f'<br><span style="margin-left:20px"><b>What to correct:</b> {escape(correction)}</span>'
            return body + "</div>"
        messages = [f'<div style="color:#536981; margin-bottom:5px">'
                    f'{escape(s.provenance)} · timeline is a prediction</div>']
        messages.append(diagnostic(result.stop_reason, "✓" if result.complete else "⚠", "#23643a" if result.complete else "#805b13"))
        messages += [diagnostic(e, "✕", "#b44136") for e in result.errors]
        messages += [diagnostic(n, "i", "#527ba8") if "\nCorrect: " in n else
                    f'<div style="margin:2px 0"><span style="color:#527ba8">i</span> {escape(n)}</div>'
                    for n in result.notes]
        self.details.setHtml("".join(messages))
        count = min(s.preview_count, s.procedure.procedure_count or s.preview_count)
        self.set_options(self.procedure_select, [(str(i + 1), i) for i in range(count)])
        self.set_options(self.event_select, [(f"Event {i + 1}", i) for i in range(result.event_count)])
        self.draw_connection()
        self.draw_procedures()
        self.draw_channels()
        self.event_changed()

    def toggle_diagnostics(self):
        self.set_diagnostics_expanded(not self._diagnostics_expanded)

    def set_diagnostics_expanded(self, expanded):
        self._diagnostics_expanded = bool(expanded)
        self.details.setVisible(self._diagnostics_expanded)
        self.diagnostics_toggle.setText("▲" if self._diagnostics_expanded else "▼")

    def draw_connection(self):
        s, plot = self.scenario, self.connection_plot
        a = s.connection
        plot.clear()
        c = a.interval_us
        for i in range(12):
            anchor = i * c
            plot.anchor(anchor)
            plot.block(anchor, a.activity_us, 1, f"ACL {i}", "#527ba8", f"Anchor {i}: {anchor / 1000:g} ms. Activity width is illustrative.")
            attends = i % (a.latency + 1) == 0
            plot.block(anchor, a.activity_us, 0, "Attend" if attends else "May skip", "#209f91" if attends else "#b7c5d4",
                       "Example maximum-skip pattern, not a prediction of actual peripheral attendance.")
        for se in self.schedule.subevents:
            begin = s.event_offset_us + se.start
            if begin < 12 * c:
                plot.block(begin, se.duration, 2, f"SE {se.index + 1}", "#8b75cb",
                           f"Procedure 1, event {se.event + 1}, subevent {se.index + 1}. {len(se.steps)} steps including Mode-0 calibration. This box shows occupied time.",
                           action=lambda i=se.index: self.select_subevent(i, procedure=0))
        plot.fit(0, 12 * c)
        self.connection_info.setText(
            f"Requested interval: {a.interval_min * 1.25:g}–{a.interval_max * 1.25:g} ms. Selected: {c / 1000:g} ms. "
            f"Anchor n = n × {c / 1000:g} ms. Latency {a.latency} permits up to {a.latency} skipped events under allowed conditions; "
            "anchors do not move. CS activity shown is the first procedure. Central/peripheral roles are independent of CS initiator/reflector roles.")
        self.timeout_plot.clear()
        self.timeout_plot.block(0, a.timeout * 10000, 0, f"Supervision timeout · {a.timeout * 10} ms", "#b77b45",
                                "Hypothetical silence after the last valid reception. A valid reception restarts supervision.")
        self.timeout_plot.fit(0, a.timeout * 10000)

    def draw_procedures(self):
        s, result, plot = self.scenario, self.schedule, self.procedure_plot
        p, c = s.procedure, s.connection.interval_us
        plot.clear()
        count = min(s.preview_count, p.procedure_count or s.preview_count)
        spacing = p.procedure_interval * c
        for i in range(count):
            start = s.event_offset_us + i * spacing
            plot.block(start, p.max_procedure_len * 625, 0, "Budget", "#d3deed",
                       f"Maximum allowed duration for procedure {i + 1}. The procedure may finish earlier when its workload is complete.",
                       action=lambda instance=i: self.select_procedure(instance))
            if result.duration:
                plot.block(start, result.duration, 0, f"Procedure {i + 1}", "#446fac",
                           f"Illustrative instance {i + 1}; includes all CS events and their scheduled gaps. Same workload/cadence replayed for the preview.",
                           action=lambda instance=i: self.select_procedure(instance))
            for event in range(result.event_count):
                subs = [se for se in result.subevents if se.event == event]
                begin = subs[0].start
                span = subs[-1].start + subs[-1].duration - begin
                plot.block(start + begin, span, 1, f"E{event + 1}", "#209f91",
                           f"Procedure {i + 1}, CS event {event + 1}: {len(subs)} subevents. Span includes the gaps between subevents.",
                           action=lambda e=event, instance=i: self.select_event(e, procedure=instance))
                anchor = i * spacing + event * p.event_interval * c
                plot.block(anchor, max(50, min(c * .015, 1000)), 2, "", "#527ba8",
                           f"ACL anchor {anchor / c:g} at {anchor / 1000:g} ms. An anchor is a point in time; marker width is only for visibility, not ACL airtime.",
                           timing_duration=0)
        plot.fit(0, s.event_offset_us + (count - 1) * spacing + max(result.duration, p.max_procedure_len * 625))
        q = max(0, result.event_count - 1)
        self.procedure_info.setText(
            f"CS event spacing = {p.event_interval} × {c / 1000:g} = {p.event_interval * c / 1000:g} ms. "
            f"Procedure spacing = {spacing / 1000:g} ms; budget = {p.max_procedure_len * .625:g} ms. "
            f"{result.event_count} CS-bearing anchors; {q * p.event_interval + 1 if result.event_count else 0} ACL anchor positions from first to last. "
            "Elapsed time includes gaps. Click a procedure or event to inspect that instance on the same ACL time origin.")

    @property
    def procedure_start(self):
        s = self.scenario
        instance = self.procedure_select.currentData() or 0
        return s.event_offset_us + instance * s.procedure.procedure_interval * s.connection.interval_us

    def select_procedure(self, index):
        self.procedure_select.setCurrentIndex(self.procedure_select.findData(index))
        self.select_event(0)

    def select_event(self, index, procedure=None):
        if procedure is not None:
            self.procedure_select.setCurrentIndex(self.procedure_select.findData(procedure))
        self.event_select.setCurrentIndex(self.event_select.findData(index))
        # Clicking the already-selected event restores its full bounds too.
        self.event_changed()
        self.views.setCurrentIndex(2)

    def event_changed(self, *_):
        event = self.event_select.currentData()
        subs = [se for se in self.schedule.subevents if se.event == event]
        self.set_options(self.subevent_select, [(f"SE {se.index + 1}", se.index) for se in subs])
        self.draw_event(subs)
        self.update_step_options()

    def draw_event(self, subs):
        plot, s = self.event_plot, self.scenario
        plot.clear()
        origin = self.procedure_start
        for se in subs:
            detail = (f"Subevent {se.index + 1}: {len(se.steps)} steps; occupied {se.duration} µs, "
                      f"budget {s.procedure.subevent_len} µs, unused {s.procedure.subevent_len - se.duration} µs. "
                      "Mode-0 calibration precedes repetitions and fresh measurements.")
            action = lambda i=se.index: self.select_subevent(i)
            plot.block(origin + se.start, s.procedure.subevent_len, 0, f"SE {se.index + 1} budget", "#a6b6ca", detail + " This box is the reserved budget.", action)
            plot.block(origin + se.start, se.duration, 1, f"{se.duration} µs occupied", "#527ba8", detail + " This box is executed activity, including internal gaps.", action)
            for index, step in enumerate(se.steps):
                plot.block(origin + step.start, step.duration, step.mode + 2,
                           f"{step.index + 1}" + (" R" if step.repeated else ""), COLORS[step.mode],
                           f"Step {step.index + 1} · Mode {step.mode} · {step.duration} µs · example channel {step.channel} "
                           f"({2402 + step.channel} MHz). " + MODE_HELP[step.mode] + (" Repeated main step; does not advance the fresh workload." if step.repeated else ""),
                           lambda si=se.index, st=step.index: self.select_step(si, st))
                if index < len(se.steps) - 1:
                    plot.block(origin + step.start + step.duration, s.configuration.t_fcs_time_us,
                               step.mode + 2, "T_FCS", "#d5dde7",
                               "Frequency-change/settling gap before the next step; excluded from the individual step duration.")
        if subs:
            start, end = origin + subs[0].start, origin + subs[-1].start + subs[-1].duration
            plot.fit(start, end, exact=True)
            self.set_event_info(f"Event {subs[0].event + 1}", start, end)
        else:
            plot.fit(0, 1)
            self.event_info.setText("No event available. See the correction suggestions below.")

    def set_event_info(self, title, start, end):
        self.event_info.setText(f"Procedure {(self.procedure_select.currentData() or 0) + 1} · {title} · "
                               f"Start {start / 1000:g} ms → End {end / 1000:g} ms · Duration {(end - start) / 1000:g} ms. "
                               "Time is measured from the first ACL anchor. The range ends at the last executed step; reserved budgets can extend beyond it. "
                               "Pale gaps are T_FCS. Click a subevent to zoom, or a step for its packet/tone structure.")

    def select_subevent(self, index, procedure=None):
        if procedure is not None:
            self.procedure_select.setCurrentIndex(self.procedure_select.findData(procedure))
        se = self.schedule.subevents[index]
        self.event_select.setCurrentIndex(self.event_select.findData(se.event))
        self.subevent_select.setCurrentIndex(self.subevent_select.findData(index))
        self.subevent_changed()
        self.views.setCurrentIndex(2)

    def selected_subevent(self):
        index = self.subevent_select.currentData()
        return self.schedule.subevents[index] if index is not None else None

    def subevent_changed(self, *_):
        se = self.selected_subevent()
        if se:
            start = self.procedure_start + se.start
            self.event_plot.fit(start, start + se.duration, exact=True)
            self.set_event_info(f"Subevent {se.index + 1}", start, start + se.duration)
        self.update_step_options()

    def update_step_options(self):
        se = self.selected_subevent()
        self.set_options(self.step_select, [(f"{st.index + 1} · M{st.mode}" + (" R" if st.repeated else ""), st.index) for st in se.steps] if se else [])
        self.update_selection_label()

    def update_selection_label(self):
        procedure = self.procedure_select.currentData()
        event = self.event_select.currentData()
        subevent = self.subevent_select.currentData()
        step = self.step_select.currentData()
        parts = []
        if procedure is not None:
            parts.append(f"Procedure {procedure + 1}")
        if event is not None:
            parts.append(f"Event {event + 1}")
        if subevent is not None:
            parts.append(f"SE {subevent + 1}")
        if step is not None:
            selected = self.selected_subevent()
            if selected and 0 <= step < len(selected.steps):
                parts.append(f"Step {step + 1} · M{selected.steps[step].mode}")
        self.selection_label.setText("  ›  ".join(parts) if parts else "Select a procedure, event, subevent, or step in the preview")
        self.draw_step()

    def select_step(self, subevent, step):
        self.select_subevent(subevent)
        self.step_select.setCurrentIndex(self.step_select.findData(step))
        self.views.setCurrentIndex(3)

    def draw_step(self, *_):
        plot, s = self.step_plot, self.scenario
        plot.clear()
        se = self.selected_subevent()
        step = next((st for st in se.steps if st.index == self.step_select.currentData()), None) if se else None
        if step is None:
            plot.fit(0, 1)
            self.step_info.setText("No step available. Resolve configuration errors or increase the timing budget.")
            return
        start = self.procedure_start + step.start
        ipt = ipt_enabled(s) and step.mode in (2, 3)
        for part in step_segments(s, step.mode):
            lane = {"Timing": 0, "Reflector": 1, "Initiator": 2}[part.lane]
            is_gap = part.label.startswith("T_") and part.label != "T_FM"
            color = "#a6b6ca" if is_gap else COLORS[step.mode]
            description = SEGMENT_HELP.get(part.label, "Tone phase-measurement slot for this illustrative antenna path.")
            if part.label == "Extension":
                color = "#c4a269"
                if ipt and part.lane == "Reflector":
                    description += " With IPT the reflector need not compensate its phase here; exclude it from slope fits."
            elif ipt and part.lane == "Reflector" and not is_gap and part.label != "CS_SYNC":
                color = IPT_TONE_COLOR
                description += (" IPT: the reflector transmits this tone pre-rotated by the phase it measured on the same path, "
                                "so the initiator measures the two-way phase directly.")
            plot.block(start + part.start, part.duration, lane, part.label, color,
                       f"{part.lane}. {description} Offset within step: {part.start} µs.")
        following = step != se.steps[-1]
        plot.fit(start, start + step.duration, exact=True)
        paths = ANTENNA_PATHS[s.procedure.tone_antenna_config_selection]
        self.step_info.setText(f"Step {step.index + 1} · Mode {step.mode} · Start {start} µs → End {start + step.duration} µs · "
                              f"Duration {step.duration} µs · {paths} antenna path(s) · example channel {step.channel} "
                              f"({2402 + step.channel} MHz; depends on CS DRBG state). Time origin: first ACL anchor. "
                              f"Offset within procedure: {step.start} µs. " +
                              (f"The following {s.configuration.t_fcs_time_us} µs T_FCS gap is outside this step, visible in the event view. " if following else "") +
                              (f"IPT: switch periods are T_SW_IPT = {s.t_sw_ipt_us} µs; reflector real-time margin T_RD + T_IP2 = "
                               f"{ipt_margin_us(s)} µs per path. " if ipt else "") +
                              "Hover each segment for its meaning and timings. Antenna permutation and extension TX presence are illustrative.")

    def draw_hops(self):
        plot, result = self.hop_plot, self.schedule
        plot.clear()
        if plot.plotItem.legend is None:
            plot.addLegend(offset=(-10, 10), colCount=4)
        plot.plotItem.legend.clear()
        steps = [(se, st) for se in result.subevents for st in se.steps]
        fresh = [(st.index, st.channel) for _, st in steps if st.mode and not st.repeated]
        if fresh:
            plot.plot(*zip(*fresh), pen=pg.mkPen("#cbd5e1", width=1))
        for se in result.subevents:
            if se.steps:
                plot.addItem(pg.InfiniteLine(se.steps[0].index - .5, pen=pg.mkPen("#d4dce6", style=QtCore.Qt.PenStyle.DashLine)))
        for mode in range(4):
            for repeated in (False, True):
                points = [(se, st) for se, st in steps if st.mode == mode and st.repeated == repeated]
                if not points:
                    continue
                spots = [{"pos": (st.index, st.channel), "data": (se.index, st.index)} for se, st in points]
                item = pg.ScatterPlotItem(spots=spots, hoverable=True, hoverSize=11, tip=self.hop_tip, size=7,
                                          symbol="o" if mode else "s", pen=pg.mkPen(COLORS[mode], width=1.5),
                                          brush="white" if repeated else COLORS[mode],
                                          name=f"Mode {mode}" + (" repeated" if repeated else ""))
                item.sigClicked.connect(self.hop_clicked)
                plot.addItem(item)
        plot.setXRange(-.5, max(1, len(steps)) - .5, padding=.01)
        # Headroom above channel 78 keeps the legend clear of the markers.
        plot.setYRange(0, 92, padding=.02)

    def hop_tip(self, x, y, data):
        se_index, st_index = data
        se = self.schedule.subevents[se_index]
        step = next(st for st in se.steps if st.index == st_index)
        return (f"Step {step.index + 1} · Mode {step.mode}" + (" · repeated channel" if step.repeated else "") +
                f"\nSubevent {se.index + 1}, event {se.event + 1}\nChannel {step.channel} · {2402 + step.channel} MHz"
                "\nExample only: depends on CS DRBG state. Click to inspect.")

    def hop_clicked(self, item, points, *_):
        if len(points):
            self.select_step(*points[0].data())

    def draw_channels(self):
        s, plot = self.scenario, self.channel_plot
        self.draw_hops()
        plot.clear()
        enabled = set(enabled_channels(s.configuration.channel_map))
        editor = self.controls["configuration.channel_map"]
        visits = {}
        for se in self.schedule.subevents:
            for st in se.steps:
                counts = visits.setdefault(st.channel, [0, 0])
                counts[0 if st.mode else 1] += 1
        for name, center in WIFI_CHANNELS:
            overlap = sum(1 for ch in enabled & set(ALLOWED_CHANNELS) if abs(2402 + ch - center) <= 10)
            plot.block(center - 10, 20, 0, name, "#c4a269",
                       f"{overlap} enabled CS channel(s) inside this 20 MHz band. Reference only; actual Wi-Fi use depends on the deployment.")
        for ch in range(79):
            allowed = ch in ALLOWED_CHANNELS
            if not allowed:
                state, color = ("reserved but set" if ch in enabled else "reserved"), ("#b44136" if ch in enabled else "#b7c5d4")
            else:
                state, color = ("enabled", "#209f91") if ch in enabled else ("disabled", "#d5dde7")
            used, calibration = visits.get(ch, (0, 0))
            plot.block(2402 + ch - .35, .7, 1, str(ch), color,
                       f"Channel {ch} · {2402 + ch} MHz · {state}. In the example procedure: "
                       f"{used} non-mode-0 step(s), {calibration} mode-0 step(s).",
                       action=(lambda c=ch: editor.toggle(c)) if allowed else None)
        plot.fit()
        c, result = s.configuration, self.schedule
        algorithm = (f"CSA #3c, {('Hat', 'X')[c.ch3c_shape] if c.ch3c_shape in (0, 1) else 'invalid'} shape, jump {c.ch3c_jump}"
                     if c.channel_selection_type == 1 else "CSA #3b")
        allowed_enabled = enabled & set(ALLOWED_CHANNELS)
        measured = {ch for ch, (used, _) in visits.items() if used}
        missing = len(allowed_enabled - measured)
        self.channel_info.setText(
            f"<b>Example hop sequence, procedure 1 (seed {s.channel_seed}).</b> The actual sequence depends on the CS DRBG state, "
            "which comes from the security setup and advances every procedure, so it cannot be predicted offline. "
            "The structure follows Core 6.1 Vol 6 Part H §4.1–4.2: mode-0 uses its own shuffle (#3a); "
            f"non-mode-0 uses {algorithm}; mode-1 sub-mode steps and repeated steps reuse channels; "
            f"the procedure closes after {c.channel_map_repetition} non-mode-0 array(s).<br>"
            f"{len(allowed_enabled)} of {len(ALLOWED_CHANNELS)} channels enabled · {result.channel_cycles} of "
            f"{c.channel_map_repetition} array(s) used · {len(measured)} distinct channels measured" +
            (f" · {missing} enabled channel(s) not measured" if missing else "") +
            ". Filled markers are fresh steps, hollow markers repeated steps; dashed lines separate subevents. "
            "Click a marker to inspect its step, or a channel below to toggle it.")

    def flush_edits(self):
        """Fold a pending control edit into the scenario before it is read or replaced."""
        if self.timer.isActive():
            self.timer.stop()
            self.recalculate()

    def apply_scenario(self, scenario, host=None, source=None):
        """Replace the scenario (and host settings, when given) and redraw every view."""
        self.timer.stop()
        if host is not None:
            self.host_settings = {**HOST_DEFAULTS, "peripheral_patterns": [],
                                  **standalone_host_settings(host)}
        self.scenario = replace(scenario, provenance=source or scenario.provenance)
        self.populate()
        return self.scenario

    def apply_channel_list(self, channels, source=None):
        """Update the channel map from CS channel indices or a raw 10-byte map.

        Other fields are unchanged. Reserved channels are kept and reported by validation.
        """
        if isinstance(channels, (bytes, bytearray, memoryview)):
            channel_map = bytes(channels)
            if len(channel_map) != 10:
                raise ValueError(f"A CS channel map must contain 10 bytes, not {len(channel_map)}")
        else:
            channels = tuple(channels)
            if not all(isinstance(ch, int) and not isinstance(ch, bool) and 0 <= ch < 80 for ch in channels):
                raise ValueError("CS channel indices must be integers 0–79")
            channel_map = channel_map_bytes(channels)
        self.flush_edits()
        s = self.scenario
        return self.apply_scenario(replace(s, configuration=replace(s.configuration, channel_map=channel_map)),
                                   source=source)

    def export_c(self):
        self.flush_edits()
        roles = ["reflector", "initiator", "both"]
        current = 1 if self.scenario.configuration.role == 0 else 0
        role, ok = W.QInputDialog.getItem(self, "Export C configuration", "Roles", roles, current, False)
        if not ok:
            return
        try:
            output = generate(self.scenario, self.host_settings, role=role)
            folder = W.QFileDialog.getExistingDirectory(self, "Export folder")
            if not folder:
                return
            paths = {r: Path(folder) / (f"cs_generated_config_{r}.c" if role == "both" else "cs_generated_config.c")
                     for r in output}
            if any(path.exists() for path in paths.values()) and W.QMessageBox.question(
                    self, "Overwrite exports?", "Replace existing generated configuration files?") != W.QMessageBox.StandardButton.Yes:
                return
            for selected, text in output.items():
                paths[selected].write_text(text, encoding="utf-8")
            self.status_message.emit("C configuration exported", 5000)
        except (ValueError, OSError) as error:
            W.QMessageBox.warning(self, "Cannot export C configuration", str(error))

    def reset(self):
        self.apply_scenario(Scenario(), {})

    def open_path(self, path):
        """Load a planner JSON file or ble-channel-sounding C export; raises ValueError or OSError."""
        scenario, host = load_document(Path(path).read_text(encoding="utf-8"))
        return self.apply_scenario(scenario, host, source=f"Loaded from {Path(path).name}")

    def open_file(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Open planner configuration", "", "Planner configuration (*.json *.c)")
        if path:
            try:
                self.open_path(path)
            except (ValueError, OSError) as error:
                W.QMessageBox.warning(self, "Cannot open configuration", str(error))

    def save_file(self):
        self.flush_edits()
        errors = validate(self.scenario)
        if errors:
            W.QMessageBox.warning(self, "Cannot save configuration", "Resolve these parameter errors first:\n" + "\n".join(errors))
            return
        path, _ = W.QFileDialog.getSaveFileName(self, "Save planner configuration", "cs-plan.json", "Planner JSON (*.json)")
        if path:
            try:
                Path(path).write_text(document(self.scenario, self.host_settings), encoding="utf-8")
                self.status_message.emit(f"Saved {Path(path).name}", 5000)
            except OSError as error:
                W.QMessageBox.warning(self, "Cannot save configuration", str(error))

    def export_view(self):
        path, _ = W.QFileDialog.getSaveFileName(self, "Export current view", "cs-timing.png", "PNG image (*.png)")
        if path and not self.views.currentWidget().grab().save(path, "PNG"):
            W.QMessageBox.warning(self, "Export failed", "Could not save the image.")
