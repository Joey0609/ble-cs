"""PyQt6 / PyQtGraph views of received CS protocol packets.

Tabs cover every client -> host frame type and any host -> client frame found
in a capture:

1. Mode-0 / FFO: measured Mode-0 offsets and reported frequency compensation
   by initiator result report over the recent time window.
2. PBR per channel: amplitude and phase of both PCTs, their reciprocal product,
   unwrapped phase with slope distance, IFFT range profile, and per-channel values.
3. RTT: mode-1/3 distance per step against channel, its histogram and steps.
4. Estimates: RTT and PBR distance estimates over the recent time window.

The timeline of the open session and its parsed records are the Session tab
(``session_view.SessionView``, owned here because it shows the same session).
ble_channel_sounding feeds it live packets; the session toolbar's **Open capture…** loads a
JSON-lines capture, raw frames or an HDF5 recording. The store keeps only the newest entries
(``ble_channel_sounding.results.MAX_*``).
"""

from __future__ import annotations

import cmath
from collections import Counter, OrderedDict
import io
import math
from pathlib import Path
import sqlite3
import time

from PyQt6 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg

from ..planner.model import uses_pbr, uses_rtt
from ..pbr_ifft import ifft_range
from ..protocol.frame import ProtocolError
from ..protocol.packets import (ConnectionParametersPacket, CsCapabilitiesPacket, CsConfigurationPacket,
                                CsInitiatorSubeventResultPacket, CsInitiatorConfigPacket, CsPeerDataPacket,
                                CsProcedureEnableCompletePacket,
                                CsReflectorConfigPacket, CsSubeventResultPacket, DeviceNamePacket,
                                PeripheralPatternsPacket, TpmPacket, packet_from_dict)
from .cells import fill_table, make_table
from .session_view import MemoryHistory, SessionView

from ..results import (CORRECTION_COMPENSATION, CORRECTION_MEASURED, CORRECTION_NONE,
                    MAX_BIT_ERRORS, SPEED_OF_LIGHT_M_S, TIME_DIFFERENCE_UNIT_NS, ResultStore, analyze_pbr,
                    analyze_rtt, load_timed_capture, centi_ppm, STEP_FLAG_FREQ_OFFSET_VALID)

SERIES = {"initiator": "#2a78d6", "reflector": "#eb6834", "raw": "#898781", "corrected": "#1baf7a"}
RTT_SERIES = {"mode 1": "#2a78d6", "mode 3": "#1baf7a", "rejected": "#c9c7c1", "median": "#eb6834", "pbr": "#0b0b0b"}
HISTOGRAM_MAX_BINS = 60
ESTIMATE_WINDOW_S = 30.0
ESTIMATE_TABLE_ROWS = 20
EMPTY_RESULTS_STATUS = "No data yet. Open a capture or connect a serial port."
# Plot-line checkboxes of the PBR per channel tab; a product line is named after its correction.
PBR_PRODUCT_LINES = (CORRECTION_NONE, CORRECTION_MEASURED, CORRECTION_COMPENSATION)
PBR_LINES = (("initiator", "Initiator PCT"), ("reflector", "Reflector PCT"),
             (CORRECTION_NONE, "Product raw"), (CORRECTION_MEASURED, "Product Mode-0"),
             (CORRECTION_COMPENSATION, "Product freq. comp."))
SIGN_HELP = (
    "<b>Direction of correction lines</b><br>"
    "<i>sign +</i> subtracts 2π·ppm·10⁻⁶·f·Δt from each product’s phase; <i>sign −</i> adds it. This "
    "applies to both the Mode-0 measured offset and reported frequency compensation lines. Their relative "
    "polarity is controller-specific, so compare both signs against a known range.<br><br>"
    "The correction is proportional to f and mainly changes the fitted phase slope. The raw PBR line remains "
    "available as the uncompensated reference."
)
SIGN_CHOICES = (
    ("sign +", 1, "Corrected phase = raw − correction; Correction (rad) carries the sign of the offset."),
    ("sign −", -1, "Corrected phase = raw + correction; Correction (rad) carries the opposite sign. "
                    "Use when <i>sign +</i> moves the distance away from the known truth."),
)


SIGN_OPTION_HELP = tuple((label, help_text) for label, _, help_text in SIGN_CHOICES)


def _option_help(label: str, help_text: str, shared: str = "") -> str:
    """Help for one option, headed by its label and followed by the selector's shared text."""
    return f"<b>{label}</b><br><br>{help_text}" + (f"<br><br>{shared}" if shared else "")


def _add_option(combo, label: str, value, help_text: str):
    """Append one option and give it a tooltip headed by its own label."""
    combo.addItem(label, value)
    combo.setItemData(combo.count() - 1, _option_help(label, help_text), QtCore.Qt.ItemDataRole.ToolTipRole)


def _selected_help(combo, choices, shared: str) -> str:
    """The selected option's help followed by shared, for the closed combo box and its label.

    The item tooltips are only reachable with the popup open, so the control itself has to
    describe the option in use as well as the mechanism behind every option.
    """
    index = max(combo.currentIndex(), 0)
    label, help_text = choices[index]
    return _option_help(label, help_text, shared)


def _iq(z: complex) -> str:
    return f"{z.real:+.0f}{z.imag:+.0f}j  |{abs(z):.1f}| ∠{math.degrees(cmath.phase(z)):+.1f}°"


def _procedure_label(key) -> str:
    """The Procedure.label wording for a procedure known only by its history key."""
    config, acl, counter = key
    return f"Procedure {counter} · config {config} · ACL {acl}"


def _metres(value, unit=" m") -> str:
    return "n/a" if value is None else f"{value:.2f}{unit}"


_table, _fill = make_table, fill_table


def _plots_with_lines(plots, choices, tooltip=""):
    """A page of plots beside a "Plot lines" column with one checked box per (name, label).

    The boxes are stacked to the left of the plots, so they take width instead of the height
    the plots need.  Returns the page and the boxes by name.
    """
    group = W.QGroupBox("Plot lines")
    group.setToolTip(tooltip)
    column = W.QVBoxLayout(group)
    checks = {}
    for name, label in choices:
        checks[name] = check = W.QCheckBox(label)
        check.setChecked(True)
        column.addWidget(check)
    column.addStretch(1)
    page = W.QWidget()
    row = W.QHBoxLayout(page)
    row.setContentsMargins(0, 0, 0, 0)
    row.addWidget(group)
    row.addWidget(plots, 1)
    return page, checks


class ProcedureSelector(W.QComboBox):
    """Procedure dropdown sized to the procedures it lists, up to ten with a scrollbar."""

    MAX_VISIBLE_ITEMS = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(190)
        self.setMaxVisibleItems(self.MAX_VISIBLE_ITEMS)
        self.view().setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view().setVerticalScrollMode(W.QAbstractItemView.ScrollMode.ScrollPerItem)

    def showPopup(self):
        """Drop ten procedures below the selector and scroll through the rest.

        The popup is as tall as the procedures it lists, never taller, so a
        replay holding three of them gets three rows rather than ten rows of
        empty space.  Beyond ten the list scrolls.

        macOS styles the combo popup as a separate window placed so that the
        selected row covers the closed box, which for a resized list leaves it
        floating away from the selector, over the window's toolbar.  Both the
        embedded list and that container are therefore given the height of the
        rows, and the container is anchored under the selector like an ordinary
        drop-down — above it when the screen leaves no room below.
        """
        view = self.view()
        row_height = view.sizeHintForRow(0)
        if row_height <= 0:
            row_height = max(1, self.fontMetrics().lineSpacing())
        rows = min(max(view.model().rowCount(), 1), self.MAX_VISIBLE_ITEMS)
        view_height = rows * row_height + 2 * view.frameWidth()
        view.setMinimumHeight(view_height)
        view.setMaximumHeight(view_height)
        super().showPopup()
        popup = view.window()
        if popup is None or popup is self.window():
            return
        height = view_height + 2 * popup.frameWidth()
        screen = popup.screen() or self.screen()
        available = screen.availableGeometry() if screen is not None else None
        if available is not None:
            height = min(height, available.height())
        popup.setMinimumHeight(height)
        popup.setMaximumHeight(height)
        area = QtCore.QRect(self.mapToGlobal(QtCore.QPoint(0, self.height())),
                            QtCore.QSize(max(popup.width(), self.width()), height))
        if available is not None:
            if area.bottom() > available.bottom():
                above = self.mapToGlobal(QtCore.QPoint(0, 0)).y() - height
                area.moveTop(max(available.top(), min(above, available.bottom() - height)))
            area.moveLeft(min(max(area.left(), available.left()), available.right() - area.width()))
        popup.setGeometry(area)


class ResultsWidget(W.QWidget):
    status_message = QtCore.pyqtSignal(str)
    save_session_requested = QtCore.pyqtSignal(str, str)
    # Emitted after a replay has loaded both the timeline and the configuration
    # saved alongside it.  MainWindow uses this to hydrate the planner view.
    replay_configuration_loaded = QtCore.pyqtSignal(object)
    def __init__(self, controller=None, recording_playback=False):
        super().__init__()
        self.store = ResultStore()
        self.session_history = None
        # A simulator fed from a recording is still reported as running, but
        # its Session tab is a recording browser rather than a hardware live
        # tail.  SessionView uses this to keep browsing controls available.
        self.recording_playback = bool(recording_playback)
        self._recording_playback_default = self.recording_playback
        # True while session_history is the live session's history (not an opened capture).
        self.live_history = False
        self.capture_path = None
        # Set by the app: the default Save session path, and the recording that holds the session.
        self.session_path_factory = None
        self.session_recording_path = None
        self.description_text = ""
        self.running = False
        # Online means that the view belongs to the connected UART session.
        # It is deliberately separate from ``running``: a link can be open
        # while the CS run-state is stopped, and it is still not a replay.
        self.online_mode = False
        # Procedure key chosen by "follow latest"; a different selection stops following.
        self.followed = None
        # Procedures averaged in the PBR tab, and whether the last of them had both roles when drawn.
        self.pbr_keys, self.pbr_complete = (), False
        self.estimate_has_rtt = False
        self.estimate_has_pbr = False
        self.measurement_mode = None
        # Procedures that received reports since the last refresh; their selector labels change.
        self.updated = set()
        # Procedure key -> (inputs it was computed from, estimate); cleared when the analysis settings change.
        self.estimates = {}
        self._estimates_centered = False
        # Procedures the open history holds: key -> [initiator reports, reflector reports, last record index].
        # Accumulated from the history index so the replay selector can offer procedures the
        # bounded store no longer decodes; see history_procedures().
        self._history_procedures = OrderedDict()
        self._history_cursor = None
        self._history_source = None
        self.timer = QtCore.QTimer(self, singleShot=True, interval=150)
        self.timer.timeout.connect(self.refresh)

        layout = W.QVBoxLayout(self)
        layout.setSpacing(6)

        # Open capture and Clear are session toolbar actions.  What is left here
        # is the procedure selector, only meaningful before a run, and the
        # analysis controls, which remain available while live reports arrive.
        bar = W.QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        self.procedure_controls = W.QWidget()
        procedure_bar = W.QHBoxLayout(self.procedure_controls)
        procedure_bar.setContentsMargins(0, 0, 0, 0)
        procedure_bar.setSpacing(5)
        self.procedure_select = ProcedureSelector()
        procedure_bar.addWidget(W.QLabel("Procedure"))
        procedure_bar.addWidget(self.procedure_select)
        bar.addWidget(self.procedure_controls)

        separator = W.QFrame()
        separator.setFrameShape(W.QFrame.Shape.VLine)
        separator.setFrameShadow(W.QFrame.Shadow.Sunken)
        bar.addWidget(separator)

        analysis_bar = W.QHBoxLayout()
        analysis_bar.setContentsMargins(0, 0, 0, 0)
        analysis_bar.setSpacing(5)
        self.path_select = W.QComboBox()
        self.sign_select = W.QComboBox()
        for label, value, help_text in SIGN_CHOICES:
            _add_option(self.sign_select, label, value, f"{help_text}<br><br>{SIGN_HELP}")
        self.quality_only = W.QCheckBox("High-quality tones only")
        self.quality_only.setChecked(True)
        self.pbr_controls = W.QWidget()
        pbr_bar = W.QHBoxLayout(self.pbr_controls)
        pbr_bar.setContentsMargins(0, 0, 0, 0)
        pbr_bar.setSpacing(5)
        path_label = W.QLabel("Path")
        path_label.setToolTip(self.path_select.toolTip())
        pbr_bar.addWidget(path_label)
        pbr_bar.addWidget(self.path_select)
        self.update_selector_help()
        pbr_bar.addWidget(self.sign_select)
        pbr_bar.addWidget(self.quality_only)
        analysis_bar.addWidget(self.pbr_controls)

        self.rtt_controls = W.QWidget()
        rtt_bar = W.QHBoxLayout(self.rtt_controls)
        rtt_bar.setContentsMargins(8, 0, 0, 0)
        rtt_bar.setSpacing(5)
        self.rtt_separator = W.QFrame()
        self.rtt_separator.setFrameShape(W.QFrame.Shape.VLine)
        self.rtt_separator.setFrameShadow(W.QFrame.Shadow.Sunken)
        rtt_bar.addWidget(self.rtt_separator)
        self.aa_success_only = W.QCheckBox("AA successful only")
        self.aa_success_only.setChecked(True)
        self.aa_success_only.setToolTip("Reject a step pair unless both roles report packet quality 0 "
                                        "(access address found with no bit errors).")
        self.max_bit_errors = W.QSpinBox(minimum=0, maximum=MAX_BIT_ERRORS, value=MAX_BIT_ERRORS)
        self.max_bit_errors.setToolTip(f"Largest bit error count accepted on either role; "
                                       f"{MAX_BIT_ERRORS} accepts every step.")
        rtt_bar.addWidget(self.aa_success_only)
        rtt_bar.addWidget(W.QLabel("Max errors"))
        rtt_bar.addWidget(self.max_bit_errors)
        analysis_bar.addWidget(self.rtt_controls)
        bar.addLayout(analysis_bar)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.summary = W.QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("background: #e4edf8; padding: 6px 10px; font-size: 13px;")
        self.description_label = W.QLabel()
        self.description_label.setWordWrap(False)
        self.description_label.setStyleSheet("background: #fff8dc; padding: 4px 8px;")
        self.description_label.setVisible(False)

        self.tabs = W.QTabWidget()
        layout.addWidget(self.description_label)
        layout.addWidget(self.tabs, 1)
        self.mode0_status = EMPTY_RESULTS_STATUS
        self.status_summary = W.QLabel()
        self.status_summary.setWordWrap(True)
        self.status_summary.setStyleSheet("background: #e4edf8; padding: 6px 10px; font-size: 13px;")
        layout.addWidget(self.status_summary)
        self.controller_view = controller
        if controller is not None:
            self.tabs.addTab(controller, "Controller")
            controller.status_message.connect(self.controller_status_changed)
        self.build_mode0_tab()
        self.build_pbr_tab()
        self.build_rtt_tab()
        self.build_estimates_tab()
        self.procedure_select.currentIndexChanged.connect(self.select_procedure)
        for widget in (self.path_select, self.sign_select):
            widget.currentIndexChanged.connect(self.pbr_settings_changed)
        self.sign_select.currentIndexChanged.connect(self.update_selector_help)
        self.quality_only.toggled.connect(self.pbr_settings_changed)
        self.aa_success_only.toggled.connect(self.rtt_settings_changed)
        self.max_bit_errors.valueChanged.connect(self.rtt_settings_changed)
        self.tabs.currentChanged.connect(self.update_result_controls)
        self.tabs.currentChanged.connect(self.update_global_status)
        self.session_view = SessionView(self)
        self.session_view.save_session_requested.connect(self.save_session_requested)
        self.set_running(False)
        self.apply_mode()
        self.update_global_status()
        self.refresh()

    def set_peer_data(self, peer_data: int):
        """Reflector data of the applied configuration, for procedures that arrive from now on.

        CS_PEER_DATA reports override it when they arrive.
        """
        self.store.peer_data = peer_data

    def set_running(self, running: bool):
        """Update the session view while a live run or recording playback is active."""
        self.running = bool(running)
        # Keep direct ResultsWidget users backwards-compatible; MainWindow
        # supplies the authoritative UART state through set_online() below.
        if not self.recording_playback:
            self.set_online(self.running)
        self.procedure_controls.setEnabled(not running)
        if hasattr(self, "session_view"):
            self.session_view.set_running(running)

    def set_online(self, online: bool):
        """Set whether this is a UART/live view rather than a replay view."""
        online = bool(online) and not self.recording_playback
        changed = online != self.online_mode
        self.online_mode = online
        if changed and hasattr(self, "session_view"):
            self.session_view._set_browsing_controls()
            self.session_view.draw(force=True)

    def history_procedures(self):
        """Every procedure the open history holds, in arrival order, with its report counts.

        The decoded store is deliberately bounded, and a Session-history
        selection narrows it to the chosen procedure and its neighbours, while
        the replay selector has to offer the whole session.  The history index
        answers that without decoding a payload; the answer is accumulated so a
        growing session only aggregates the records that arrived since the last
        redraw, and procedures dropped by the history size limit fall out.
        """
        source = self.session_history
        if source is not self._history_source:
            self._history_procedures = OrderedDict()
            self._history_cursor = None
            self._history_source = source
        if source is None or not hasattr(source, "procedure_summaries"):
            return self._history_procedures
        try:
            summaries, highest, lowest = source.procedure_summaries(after=self._history_cursor)
        except (OSError, KeyError, ValueError, sqlite3.Error):
            return self._history_procedures
        for key in [key for key, counts in self._history_procedures.items() if counts[2] < lowest]:
            del self._history_procedures[key]
        for summary in summaries:
            counts = self._history_procedures.get(summary.key)
            if counts is None:
                self._history_procedures[summary.key] = [summary.initiator, summary.reflector,
                                                         summary.last_index]
            else:
                counts[0] += summary.initiator
                counts[1] += summary.reflector
                counts[2] = max(counts[2], summary.last_index)
        self._history_cursor = highest
        return self._history_procedures

    def _live_procedure_mode(self):
        return self.online_mode and not self.recording_playback

    def begin_session(self, history):
        """Replace the live ResultStore at a confirmed START/hostless connect."""
        self.clear()
        self.session_history = history
        self.live_history = history is not None
        self.set_description("")
        self.draw_history()

    def set_session_history(self, history):
        """Attach the live session's temporary history without changing decoded results."""
        self.session_history = history
        self.live_history = history is not None
        self.set_description(self.description_text)
        self.draw_history()

    def set_description(self, text):
        self.description_text = str(text or "")
        if self.description_text:
            one_line = " ".join(self.description_text.splitlines())
            self.description_label.setText(one_line)
            self.description_label.setToolTip(self.description_text)
            self.description_label.setVisible(True)
        else:
            self.description_label.clear()
            self.description_label.setToolTip("")
            self.description_label.setVisible(False)
        if hasattr(self, "session_view"):
            self.session_view.set_description(self.description_text)

    def edit_description(self):
        text, accepted = W.QInputDialog.getMultiLineText(self, "Run description", "Description:",
                                                          self.description_text)
        if not accepted:
            return
        self.set_description(text)
        if self.capture_path is not None:
            try:
                from ..recorder import update_description
                update_description(self.capture_path, text)
                self.status_message.emit(f"Updated description in {self.capture_path.name}")
            except (OSError, ValueError) as error:
                W.QMessageBox.warning(self, "Cannot update description", str(error))

    def set_measurement_mode(self, mode):
        """Show the views of the selected CS mode combination; None shows both analyses.

        A hosted run supplies the mode after START is confirmed; an unchanged mode keeps the tab and Estimates.
        """
        mode = mode if isinstance(mode, int) and not isinstance(mode, bool) else None
        if mode == self.measurement_mode:
            return
        self.measurement_mode = mode
        self.apply_mode()
        # A mode with a single analysis opens its tab instead of leaving the user on Estimates.
        if self.tabs.currentWidget() is self.estimates_page and self.estimate_has_rtt != self.estimate_has_pbr:
            self.tabs.setCurrentWidget(self.pbr_page if self.estimate_has_pbr else self.rtt_page)
        self.estimates.clear()
        self.draw_estimates()

    def analyses(self):
        """Return the visible (RTT, PBR) analyses for the active Results mode.

        Before a run selects a mode, keep both analyses available by default.
        """
        if self.measurement_mode is not None:
            return uses_rtt(self.measurement_mode), uses_pbr(self.measurement_mode)
        return True, True

    def set_estimate_line_enabled(self, name, checked):
        curve = self.estimate_curves[name]
        visible = checked and getattr(curve, "_analysis_visible", True)
        curve.setVisible(visible)
        label = self.estimate_curve_legends[name].getLabel(curve)
        if label is not None:
            label.setVisible(visible)

    def apply_mode(self):
        """Show only the tabs, filters, Estimates series and Controller rows of the active analyses.

        The one place mode-dependent visibility is decided; every mode or data change goes through it.
        """
        has_rtt, has_pbr = self.estimate_has_rtt, self.estimate_has_pbr = self.analyses()
        pages = ((self.pbr_page, has_pbr), (self.rtt_page, has_rtt))
        if any(page is self.tabs.currentWidget() and not visible for page, visible in pages):
            self.tabs.setCurrentWidget(self.estimates_page)
        for page, visible in pages:
            index = self.tabs.indexOf(page)
            # An unchanged setTabVisible() cancels the relayout Qt deferred for a hidden tab bar,
            # which leaves a gap where a tab was hidden.
            if self.tabs.isTabVisible(index) != visible:
                self.tabs.setTabVisible(index, visible)
        self.update_result_controls()
        for name, visible in (("RTT mean", has_rtt), ("RTT median", has_rtt),
                              ("PBR slope (raw)", has_pbr),
                              ("PBR slope (Mode-0 offset)", has_pbr),
                              ("PBR slope (frequency compensation)", has_pbr),
                              ("PBR IFFT (raw)", has_pbr),
                              ("PBR IFFT (Mode-0 offset)", has_pbr),
                              ("PBR IFFT (frequency compensation)", has_pbr)):
            curve = self.estimate_curves[name]
            curve._analysis_visible = visible
            self.set_estimate_line_enabled(name, self.estimate_line_checks[name].isChecked())
        for column in range(4, self.estimates_table.columnCount()):
            self.estimates_table.setColumnHidden(column, not (has_rtt if column < 8 else has_pbr))
        if self.controller_view is not None:
            self.controller_view.set_mode(self.measurement_mode)

    def update_result_controls(self, *_):
        """Show tab-specific filters in the shared Results configuration row."""
        current = self.tabs.currentWidget()
        self.procedure_controls.setVisible(current not in (self.controller_view, self.mode0_page))
        self.pbr_controls.setVisible(current is self.pbr_page or
                                     (current is self.estimates_page and self.estimate_has_pbr))
        self.rtt_controls.setVisible(current is self.rtt_page or
                                     (current is self.estimates_page and self.estimate_has_rtt))

    def update_global_status(self, *_):
        """Show the selected analysis tab's status in the shared footer."""
        if self.controller_view is not None and self.tabs.currentWidget() is self.controller_view:
            self.set_status_summary(self.controller_view.status_text)
            return
        if self.tabs.currentWidget() is self.mode0_page:
            self.set_status_summary(self.mode0_status)
            return
        sources = ((self.pbr_page, self.summary), (self.rtt_page, self.rtt_summary),
                   (self.estimates_page, self.estimates_summary))
        source = next((label for page, label in sources if self.tabs.currentWidget() is page), None)
        self.set_status_summary(source.text() if source is not None else "",
                                source.toolTip() if source is not None else "")

    def controller_status_changed(self, text):
        if self.tabs.currentWidget() is self.controller_view:
            self.set_status_summary(text)

    def set_status_summary(self, text, tooltip=""):
        """Set the shared footer, including status supplied by a sibling Results sub-tab."""
        self.status_summary.setText(text)
        self.status_summary.setToolTip(tooltip)

    def draw_history(self, *_):
        """Refresh the Session tab's timeline of the open session."""
        if hasattr(self, "session_view"):
            self.session_view.draw()

    def default_session_path(self) -> str:
        """Default *Save session…* file: ``session_<mode>_<start>.h5`` in the recording folder."""
        return str(self.session_path_factory()) if self.session_path_factory else "session.h5"

    def session_recording(self):
        """The recording that holds the whole open session, if *Recording* was on for it."""
        path = self.session_recording_path
        return path if path is not None and Path(path).exists() else None

    def open_capture_path(self, path):
        path = Path(path)
        try:
            data = path.read_bytes()
            packets, errors = load_timed_capture(data)
            # Session/recording configuration is written beside the HDF5 as
            # config_<recording>.json.  It is a planner preset, not a packet
            # capture; opening it as a capture used to replace the visible
            # history with an empty timeline.  If the companion recording is
            # present, follow it so opening the generated JSON still opens the
            # session the user selected.
            if not packets and errors and path.name.startswith("config_"):
                recording_name = path.name[len("config_"):]
                candidates = (path.with_name(recording_name).with_suffix(suffix)
                              for suffix in (".h5", ".hdf5"))
                recording = next((candidate for candidate in candidates if candidate.exists()), None)
                if recording is None:
                    raise ValueError(f"{path.name} is a configuration file, not a capture; "
                                     "open its accompanying .h5 recording")
                path, data = recording, recording.read_bytes()
            elif not packets and errors:
                raise ValueError(f"{path.name} is not a readable capture: {errors[0]}")
            self.load(data, path.name)
        except (OSError, ValueError) as error:
            W.QMessageBox.warning(self, "Cannot open capture", str(error))
            return
        self.capture_path = path
        self.set_description(self.description_text)
        self.draw_history()

    def build_mode0_tab(self):
        page = W.QWidget()
        self.mode0_page = page
        layout = W.QVBoxLayout(page)
        views = W.QTabWidget()
        layout.addWidget(views, 1)
        self.mode0_plot = pg.PlotWidget(background="white")
        self.mode0_plot.setLabel("bottom", "Host time since first report", units="s")
        self.mode0_plot.setLabel("left", "Frequency offset", units="ppm")
        self.mode0_plot.showGrid(x=True, y=True, alpha=.15)
        self.mode0_plot.addLegend(offset=(10, 10))
        self.mode0_curves = {
            name: self.mode0_plot.plot(name=name, pen=pg.mkPen(color, width=1), symbol=symbol,
                                       symbolSize=6, symbolBrush=color, symbolPen=None, connect="finite")
            for name, color, symbol in (("Mode-0 measured offset", "#2a78d6", "o"),
                                        ("Frequency compensation", "#eb6834", "t"))}
        self.mode0_marker = pg.InfiniteLine(pen=pg.mkPen("#d4dce6", style=QtCore.Qt.PenStyle.DashLine))
        self.mode0_plot.addItem(self.mode0_marker)
        views.addTab(self.mode0_plot, "Plot")
        self.mode0_table = _table(("Time (s)", "Procedure", "Config", "ACL event", "Report",
                                   "Mode-0 offset (ppm)", "Frequency compensation (ppm)"))
        views.addTab(self.mode0_table, "Table")
        self.tabs.addTab(page, "Mode 0 / FFO")

    def build_pbr_tab(self):
        page = W.QWidget()
        self.pbr_page = page
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        views = W.QTabWidget()
        plots_page = W.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.amplitude_plot, self.phase_plot, self.unwrapped_plot, self.ifft_plot = (
            pg.PlotWidget(background="white") for _ in range(4))
        top = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        bottom = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        labels = (("Amplitude", ""), ("Wrapped phase", "rad"),
                  ("Unwrapped product phase", "rad"), ("IFFT magnitude", ""))
        for plot, (label, units) in zip((self.amplitude_plot, self.phase_plot,
                                         self.unwrapped_plot, self.ifft_plot), labels):
            plot.setLabel("left", label, units=units)
            if plot is self.ifft_plot:
                plot.setLabel("bottom", "Range", units="m")
            else:
                plot.setLabel("bottom", "CS channel (2402 + ch MHz)")
            plot.showGrid(x=True, y=True, alpha=.15)
            plot.addLegend(offset=(-10, 10), colCount=4)
            if plot is self.ifft_plot:
                plot.setXRange(0, 30, padding=.01)
            else:
                plot.setXRange(0, 79, padding=.01)
            if plot in (self.phase_plot, self.unwrapped_plot):
                plot.setXLink(self.amplitude_plot)
        top.addWidget(self.amplitude_plot)
        top.addWidget(self.phase_plot)
        bottom.addWidget(self.unwrapped_plot)
        bottom.addWidget(self.ifft_plot)
        top.setSizes([300, 300])
        bottom.setSizes([300, 300])
        self.phase_plot.setYRange(-math.pi, math.pi, padding=.05)
        self.channel_table = _table(("Ch", "MHz", "N", "Initiator PCT", "Reflector PCT", "Product raw",
                                     "Mode-0 ppm", "Mode-0 correction (rad)", "Product Mode-0 corrected",
                                     "Freq. comp. ppm", "Freq. comp. correction (rad)",
                                     "Product freq. comp. corrected"))
        plots_page.addWidget(top)
        plots_page.addWidget(bottom)
        plots_page.setSizes([240, 300])
        plots_tab, self.pbr_line_checks = _plots_with_lines(
            plots_page, PBR_LINES,
            "Show or hide a line in every PBR plot that draws it: a PCT line in the amplitude and wrapped "
            "phase plots, a product line in the wrapped phase, unwrapped phase (with its fit) and IFFT plots. "
            "√|product| is shown while any product line is.")
        for check in self.pbr_line_checks.values():
            check.toggled.connect(self.draw_pbr)
        views.addTab(plots_tab, "Plots")
        views.addTab(self.channel_table, "Table")
        layout.addWidget(views, 1)
        self.tabs.addTab(page, "PBR per channel")

    def build_rtt_tab(self):
        page = W.QWidget()
        self.rtt_page = page
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rtt_summary = W.QLabel()
        self.rtt_summary.setStyleSheet("background: #e4edf8; padding: 6px 10px; font-size: 13px;")
        self.rtt_summary.setToolTip(
            f"ToF = (initiator ToA−ToD − reflector ToD−ToA) / 2, time differences in {TIME_DIFFERENCE_UNIT_NS} ns; "
            "distance = c·ToF.")

        views = W.QTabWidget()
        layout.addWidget(views, 1)
        plots_page = W.QSplitter(QtCore.Qt.Orientation.Vertical)
        top = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.rtt_channel_plot, self.rtt_histogram_plot = (pg.PlotWidget(background="white") for _ in range(2))
        for plot, left, bottom in ((self.rtt_channel_plot, "RTT distance", "CS channel (2402 + ch MHz)"),
                                   (self.rtt_histogram_plot, "Step pairs", "RTT distance")):
            plot.setLabel("left", left, units="m" if plot is not self.rtt_histogram_plot else "")
            plot.setLabel("bottom", bottom, units="m" if plot is self.rtt_histogram_plot else "")
            plot.showGrid(x=True, y=True, alpha=.15)
            plot.addLegend(offset=(-10, 10), colCount=4)
        self.rtt_channel_plot.setXRange(0, 79, padding=.01)
        top.addWidget(self.rtt_channel_plot)
        top.addWidget(self.rtt_histogram_plot)
        top.setSizes([500, 300])
        plots_page.addWidget(top)
        self.rtt_table = _table(("Step", "Report", "Mode", "Ch", "MHz", "ToA−ToD I (0.5 ns)", "ToD−ToA R (0.5 ns)",
                                 "ToF (ns)", "Distance (m)", "AA q I/R", "Bit err I/R", "NADM I/R", "RSSI I/R",
                                 "Ant I/R", "Accepted"))
        views.addTab(plots_page, "Plots")
        views.addTab(self.rtt_table, "Table")
        self.tabs.addTab(page, "RTT")

    def build_estimates_tab(self):
        page = W.QWidget()
        self.estimates_page = page
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.estimates_summary = W.QLabel()
        self.estimates_summary.setStyleSheet("background: #e4edf8; padding: 6px 10px; font-size: 13px;")
        self.estimates_summary.setToolTip(
            "One estimate per procedure with both roles reported. RTT uses the AA and bit error filters of the "
            "RTT tab; PBR uses the selected path and tone quality, without averaging procedures. Use the plot "
            "line checkboxes to show or hide RTT, PBR slope and PBR IFFT estimates.")
        line_choices = (("RTT mean", "RTT mean"), ("RTT median", "RTT median"),
                        ("PBR slope (raw)", "PBR slope raw"),
                        ("PBR slope (Mode-0 offset)", "PBR slope Mode-0"),
                        ("PBR slope (frequency compensation)", "PBR slope freq. comp."),
                        ("PBR IFFT (raw)", "PBR IFFT raw"),
                        ("PBR IFFT (Mode-0 offset)", "PBR IFFT Mode-0"),
                        ("PBR IFFT (frequency compensation)", "PBR IFFT freq. comp."))
        views = W.QTabWidget()
        layout.addWidget(views, 1)
        plot = pg.PlotWidget(background="white")
        plots_tab, self.estimate_line_checks = _plots_with_lines(plot, line_choices)
        plot.setLabel("left", "Distance", units="m")
        plot.setLabel("bottom", "Host time since first report", units="s")
        plot.showGrid(x=True, y=True, alpha=.15)
        plot.addLegend(offset=(10, 10), colCount=4)
        self.estimates_plot = plot
        self.estimate_curves = {}
        self.estimate_curve_legends = {}
        for name, color, symbol in (("RTT mean", RTT_SERIES["mode 1"], "o"),
                                    ("RTT median", RTT_SERIES["median"], "t"),
                                    ("PBR slope (raw)", SERIES["raw"], "o"),
                                    ("PBR slope (Mode-0 offset)", RTT_SERIES["pbr"], "s"),
                                    ("PBR slope (frequency compensation)", "#eb6834", "t"),
                                    ("PBR IFFT (raw)", SERIES["raw"], "d"),
                                    ("PBR IFFT (Mode-0 offset)", RTT_SERIES["pbr"], "d"),
                                    ("PBR IFFT (frequency compensation)", "#eb6834", "d")):
            self.estimate_curves[name] = plot.plot(
                name=name, pen=pg.mkPen(color, width=1, style=(QtCore.Qt.PenStyle.DashLine if "IFFT" in name
                                                              else QtCore.Qt.PenStyle.SolidLine)),
                symbol=symbol, symbolSize=6,
                symbolBrush=color, symbolPen=None, connect="finite")
            self.estimate_curve_legends[name] = plot.plotItem.legend
        self.estimates_legend = plot.plotItem.legend
        for name, check in self.estimate_line_checks.items():
            check.toggled.connect(lambda checked, curve_name=name:
                                  self.set_estimate_line_enabled(curve_name, checked))
        # A 1 px pen: Qt strokes a wider antialiased line through hundreds of
        # procedures in tens to hundreds of milliseconds per repaint once the
        # series alternates between two values, as multi-path PBR can.
        self.estimate_marker = pg.InfiniteLine(pen=pg.mkPen("#d4dce6", style=QtCore.Qt.PenStyle.DashLine))
        plot.addItem(self.estimate_marker)
        views.addTab(plots_tab, "Plots")
        self.estimates_table = _table(("Time (s)", "Procedure", "Config", "ACL event", "RTT mean (m)",
                                       "RTT median (m)", "RTT σ (m)", "RTT pairs", "PBR raw (m)",
                                       "PBR Mode-0 (m)", "PBR freq. comp. (m)", "IFFT raw (m)",
                                       "IFFT Mode-0 (m)", "IFFT freq. comp. (m)"))
        views.addTab(self.estimates_table, "Table")
        self.tabs.addTab(page, "Estimates")

    # Data input -----------------------------------------------------------

    @staticmethod
    def _hdf5_value(value):
        """Convert a scalar/array returned by h5py into packet-friendly values."""
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, bytes):
            return value
        return value

    @classmethod
    def _read_replay_configuration(cls, file):
        """Read configuration metadata stored by RunRecorder from an HDF5 session."""
        context = {}
        if "config/planner_scenario" in file:
            value = file["config/planner_scenario"][()]
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            context["scenario_json"] = str(value or "")

        packet_names = {
            int(CsInitiatorConfigPacket.PACKET_TYPE): "cs_initiator_config",
            int(CsReflectorConfigPacket.PACKET_TYPE): "cs_reflector_config",
        }
        if "config/cs_config" in file and len(file["config/cs_config"]):
            dataset = file["config/cs_config"]
            values = {name: cls._hdf5_value(dataset[-1][name]) for name in dataset.dtype.names}
            name = packet_names.get(int(dataset.attrs.get("packet_type", -1)))
            if name:
                try:
                    context["host_config"] = packet_from_dict(name, values)
                except (ProtocolError, TypeError, ValueError):
                    # The raw sent packet remains a usable fallback for older files.
                    pass

        if "config/peer_data" in file:
            context["peer_data"] = int(file["config/peer_data"][()])
        if "config/t_pm" in file:
            context["t_pm"] = int(file["config/t_pm"][()])
        if "config/peripheral_patterns" in file:
            names = file["config/peripheral_patterns"][:]
            context["patterns"] = [name.decode("utf-8", errors="replace") if isinstance(name, bytes)
                                    else str(name) for name in names]
        if "config/device_name" in file:
            name = file["config/device_name"][()]
            context["device_name"] = name.decode("utf-8", errors="replace") if isinstance(name, bytes) else str(name)
        if "config/log" in file:
            levels = file["config/log"][:]
            if len(levels) >= 2:
                context["log"] = {"console": int(levels[0]), "host": int(levels[1])}
        return context

    @staticmethod
    def _replay_packet_context(packets):
        """Return the latest configuration packets found in a replay timeline (enabled procedures only)."""
        context = {}
        for entry in reversed(packets):
            packet = entry[1]
            if "host_config" not in context and isinstance(packet, (CsInitiatorConfigPacket,
                                                                       CsReflectorConfigPacket)):
                context["host_config"] = packet
            if "selected_config" not in context and isinstance(packet, CsConfigurationPacket):
                context["selected_config"] = packet
            # A disable report carries no schedule; the planner restores the last enabled one.
            if "procedure" not in context and isinstance(packet, CsProcedureEnableCompletePacket) and packet.state:
                context["procedure"] = packet
            if "connection" not in context and isinstance(packet, ConnectionParametersPacket):
                context["connection"] = packet
            if "peer_data_packet" not in context and isinstance(packet, CsPeerDataPacket):
                context["peer_data_packet"] = packet
            if "patterns_packet" not in context and isinstance(packet, PeripheralPatternsPacket):
                context["patterns_packet"] = packet
            if "device_name_packet" not in context and isinstance(packet, DeviceNamePacket):
                context["device_name_packet"] = packet
            if "t_pm_packet" not in context and isinstance(packet, TpmPacket):
                context["t_pm_packet"] = packet
        return context

    def add_packet(self, packet, timestamp=None, direction="received"):
        """Add a decoded packet, Frame or wire frame received at ``timestamp`` (monotonic s, default now).

        Call on the GUI thread.
        """
        procedure = self.store.add(packet, time.monotonic() if timestamp is None else timestamp, direction)
        if procedure is not None:
            self.updated.add(procedure.key)
        if not self.timer.isActive():
            self.timer.start()

    def load(self, data: bytes, source: str = ""):
        packets, errors = load_timed_capture(data)
        self.clear()
        self.recording_playback = True
        description = ""
        replay_configuration = {}
        if data.startswith(b"\x89HDF\r\n\x1a\n"):
            try:
                import h5py
                with h5py.File(io.BytesIO(data), "r") as file:
                    value = file.attrs.get("description", "")
                    description = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
                    replay_configuration = self._read_replay_configuration(file)
            except (OSError, ValueError):
                description = ""
        self.session_history = MemoryHistory(packets)
        self.live_history = False
        self.set_description(description)
        for entry in packets:
            timestamp, packet, *direction = entry
            procedure = self.store.add(packet, timestamp, direction[0] if direction else "received")
            if procedure is not None:
                self.updated.add(procedure.key)
        # The Controller tab and the mode-dependent views come from the record
        # itself: the reports its link produced, and the configuration the host
        # that recorded it asked for.
        negotiated = next((entry[1] for entry in reversed(packets)
                           if isinstance(entry[1], CsConfigurationPacket)), None)
        self.set_measurement_mode(negotiated.mode if negotiated else None)
        replay_configuration = {**self._replay_packet_context(packets), **replay_configuration}
        if "patterns" not in replay_configuration and "patterns_packet" in replay_configuration:
            replay_configuration["patterns"] = replay_configuration["patterns_packet"].names()
        if "device_name" not in replay_configuration and "device_name_packet" in replay_configuration:
            replay_configuration["device_name"] = replay_configuration["device_name_packet"].text()
        if "peer_data" not in replay_configuration and "peer_data_packet" in replay_configuration:
            replay_configuration["peer_data"] = replay_configuration["peer_data_packet"].peer_data
        if "t_pm" not in replay_configuration and "t_pm_packet" in replay_configuration:
            replay_configuration["t_pm"] = replay_configuration["t_pm_packet"].t_pm_us
        if self.controller_view is not None:
            self.controller_view.replay((entry[1], entry[2] if len(entry) > 2 else "received") for entry in packets)
        # A capture is shown from its newest procedure; its backlog is not averaged.
        self.refresh(average=False)
        self.replay_configuration_loaded.emit(replay_configuration)
        message = f"Loaded {len(packets)} packets" + (f" from {source}" if source else "")
        if errors:
            message += f"; {len(errors)} skipped (first: {errors[0]})"
        self.status_message.emit(message)

    def open_capture(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Open capture", "",
                                                "Captures (*.jsonl *.json *.txt *.bin *.h5 *.hdf5);;All files (*)")
        if path:
            self.open_capture_path(path)

    def clear(self):
        self.store = ResultStore()
        self.session_history = None
        self.live_history = False
        self.recording_playback = self._recording_playback_default
        self.capture_path = None
        self.set_description("")
        self.followed = None
        self.pbr_keys, self.pbr_complete = (), False
        self.updated.clear()
        self.estimates.clear()
        self.procedure_select.blockSignals(True)
        self.procedure_select.clear()
        self.procedure_select.blockSignals(False)
        if hasattr(self, "session_view"):
            self.session_view.clear_detail()
        self.refresh()

    # Views ----------------------------------------------------------------

    def refresh(self, average=True):
        """Redraw from the store; ``average`` lets a followed PBR view average the procedures since the last redraw."""
        store = self.store
        select = self.procedure_select
        keys = list(store.procedures)
        positions = {key: n for n, key in enumerate(keys)}
        old = select.currentData()
        live = self._live_procedure_mode()
        history = {} if live else self.history_procedures()
        follow = live or old is None or old == self.followed or (old not in positions and old not in history)
        index = self.latest_index() if follow else positions.get(old, -1)
        # The replay list mirrors every procedure the session holds, which is
        # the history rather than the bounded decoded store; a live session
        # exposes only the procedure currently being followed.  Records reach
        # the store before the history writer has indexed them, so store
        # procedures the history does not know yet close the list.
        display_keys = ((() if index < 0 else (keys[index],)) if live else
                        tuple(history) + tuple(key for key in keys if key not in history))
        select.blockSignals(True)
        current = tuple(select.itemData(item) for item in range(select.count()))
        stale = set(display_keys)
        if current != display_keys:
            if current and display_keys[:len(current)] == current:
                # A replay that is still arriving only grows; appending keeps
                # a long session's list cheap to redraw.
                added = display_keys[len(current):]
                stale = set(added)
                for key in added:
                    select.addItem("", key)
            else:
                select.clear()
                for key in display_keys:
                    select.addItem("", key)
        # Counts change only for procedures that are still being reported, so
        # the rest of a long list keeps the text it was given.
        stale |= self.updated | set(keys)
        for item, key in enumerate(display_keys):
            if key not in stale:
                continue
            procedure = store.procedures.get(key)
            counts = ((len(procedure.initiator), len(procedure.reflector)) if procedure is not None
                      else tuple(history.get(key, (0, 0))[:2]))
            label = procedure.label if procedure is not None else _procedure_label(key)
            select.setItemText(item, f"{label} · {counts[0]}I/{counts[1]}R")
        self.updated.clear()
        selected_key = keys[index] if follow and index >= 0 else old
        selected_item = display_keys.index(selected_key) if selected_key in display_keys else -1
        select.setCurrentIndex(selected_item)
        select.blockSignals(False)
        if follow:
            previous, self.followed = self.followed, keys[index] if index >= 0 else None
            self.pbr_keys = (self.averaged_keys(previous, keys, positions, index) if average
                             else keys[index:index + 1])
        self.draw_history()
        self.draw_procedure()

    def averaged_keys(self, previous, keys, positions, index):
        """Procedures the PBR tab averages after following moved from ``previous`` to ``keys[index]``.

        These are the complete procedures that arrived since the previous redraw,
        including the previous one if it was drawn before both roles reported.
        The newest procedure alone when there are none, or when nothing was
        followed before.
        """
        if index < 0:
            return ()
        latest = keys[index]
        if previous == latest:
            kept = tuple(key for key in self.pbr_keys if key in positions)
            return kept if kept and kept[-1] == latest else (latest,)
        if previous not in positions or positions[previous] > index:
            return (latest,)
        first = positions[previous] + (1 if self.pbr_complete else 0)
        batch = tuple(key for key in keys[first:index + 1] if self.store.procedures[key].complete)
        return batch if batch and batch[-1] == latest else batch + (latest,)

    def latest_index(self):
        """The newest procedure, or the one before it while the newest still waits for the other role.

        The reflector's RAS report trails the initiator's by an ACL event, so the
        newest procedure is usually one-sided whenever the view redraws.
        """
        procedures = list(self.store.procedures.values())
        last = len(procedures) - 1
        if last >= 1 and not procedures[last].complete and procedures[last - 1].complete:
            return last - 1
        return last

    def selected_procedure(self):
        key = self.procedure_select.currentData()
        return self.store.procedures.get(key) if key is not None else None

    def select_procedure(self, *_):
        """A procedure chosen in the selector is shown on its own."""
        key = self.procedure_select.currentData()
        # The replay selector lists every procedure the history holds, of which
        # only a small window is decoded.  Decode the chosen one first;
        # select_procedure_key() comes back here once it is in the store.
        if key is not None and key not in self.store.procedures and self.select_procedure_key(key):
            return
        self.pbr_keys = () if key is None else (key,)
        self.draw_procedure()

    def select_procedure_key(self, key):
        """Show the procedure identified by a Session-history procedure key."""
        # The live ResultStore is intentionally bounded.  A stopped session or
        # an opened recording, however, can still expose an older history row.
        # Restore that procedure and the temporal context needed by the
        # Estimates view into a small analysis store before selecting it.
        # Controller reports are link-wide, not procedure-scoped, so this
        # path must not replay or otherwise refresh the Controller widget.
        if key not in self.store.procedures and not self._restore_history_context(key):
            return False
        # QComboBox.findData() does not reliably compare tuple-backed QVariant
        # payloads on all Qt/PyQt versions; compare the Python values directly.
        index = next((item for item in range(self.procedure_select.count())
                      if self.procedure_select.itemData(item) == key), -1)
        if index < 0:
            return False
        if self.procedure_select.currentIndex() == index:
            # Re-selecting the current procedure must also discard any PBR
            # averaging that was accumulated while following the live tail.
            self.select_procedure()
        else:
            self.procedure_select.setCurrentIndex(index)
        return True

    def _history_entries(self):
        """Iterate the open replay history without changing the Controller view."""
        source = self.session_history
        if source is None:
            return ()
        try:
            if hasattr(source, "iter_entries"):
                return source.iter_entries()
            return source.snapshot()
        except (OSError, KeyError, ValueError):
            return ()

    def _restore_history_context(self, selected_key):
        """Load a missing history procedure and its estimate-window context.

        The temporary ResultStore is deliberately scoped to analysis data.  The
        Session view keeps the complete history, while controller reports and
        FAE context remain owned by their existing widgets.
        """
        source = self.session_history
        if source is None:
            return False

        # Find unique procedures in timeline order without retaining decoded
        # packets.  A procedure can have several subevent records.
        procedure_keys = list(self.history_procedures())
        if not procedure_keys:
            seen = set()
            for entry in self._history_entries():
                key = getattr(entry, "procedure_key", None)
                if key is not None and key not in seen:
                    seen.add(key)
                    procedure_keys.append(key)
        try:
            selected_position = procedure_keys.index(selected_key)
        except ValueError:
            return False

        # The history index gives procedure order, but not the procedure time.
        # Read timestamps from the index without decoding payloads so an old
        # replay selection can still populate the full ±30-second estimate
        # window after the bounded ResultStore has evicted it.
        procedure_times = {}
        for entry in self._history_entries():
            if entry.procedure_key in procedure_keys and entry.procedure_key not in procedure_times:
                procedure_times[entry.procedure_key] = entry.timestamp
        selected_time = procedure_times.get(selected_key)
        if selected_time is None:
            neighbour_positions = range(max(0, selected_position - 1),
                                        min(len(procedure_keys), selected_position + 2))
            context_keys = set(procedure_keys[position] for position in neighbour_positions)
        else:
            context_keys = {key for key, timestamp in procedure_times.items()
                            if selected_time - ESTIMATE_WINDOW_S <= timestamp <= selected_time + ESTIMATE_WINDOW_S}
        context_packets = []
        for entry in self._history_entries():
            # The index knows which procedure a subevent record belongs to, so
            # the records of every other procedure are skipped without reading
            # or decoding them.  A long session is mostly those records.
            if entry.procedure_key is not None and entry.procedure_key not in context_keys:
                continue
            try:
                packet = source.read(entry)
            except (KeyError, OSError, ValueError):
                continue
            if isinstance(packet, CsSubeventResultPacket):
                procedure_key = (packet.config_id, packet.start_acl_conn_event, packet.procedure_counter)
                if procedure_key not in context_keys:
                    continue
                context_packets.append((entry.timestamp, packet, entry.direction))
            elif isinstance(packet, (CsCapabilitiesPacket, CsConfigurationPacket, CsPeerDataPacket,
                                     CsProcedureEnableCompletePacket)):
                # These reports are analysis context rather than a procedure.
                # Keep them in timeline order so a restored procedure gets the
                # same configuration, peer-data and timing assumptions.
                context_packets.append((entry.timestamp, packet, entry.direction))

        if not context_packets:
            return False

        old_origin = self.store.origin
        new_store = ResultStore(
            max_packets=max(self.store.packets.maxlen or 0, len(context_packets)),
            max_procedures=max(len(context_keys), 1),
            max_logs=self.store.logs.maxlen or 1,
        )
        new_store.peer_data = self.store.peer_data
        for timestamp, packet, direction in context_packets:
            new_store.add(packet, timestamp, direction)
        history_origin = getattr(source, "origin", None)
        if history_origin is not None:
            new_store.origin = history_origin
        elif old_origin is not None:
            new_store.origin = old_origin

        self.store = new_store
        self.followed = None
        self.pbr_keys = ()
        self.estimates.clear()
        self.procedure_select.blockSignals(True)
        self.procedure_select.clear()
        self.procedure_select.blockSignals(False)
        self.refresh(average=False)
        return selected_key in self.store.procedures

    def pbr_procedures(self):
        """The selected procedure, preceded by those averaged with it."""
        selected = self.selected_procedure()
        if selected is None:
            return []
        if self.pbr_keys and self.pbr_keys[-1] == selected.key:
            return [self.store.procedures[key] for key in self.pbr_keys if key in self.store.procedures]
        return [selected]

    def update_selector_help(self, *_):
        """Show the selected direction's help on the PBR sign selector."""
        self.sign_select.setToolTip(_selected_help(self.sign_select, SIGN_OPTION_HELP, SIGN_HELP))

    def pbr_settings_changed(self, *_):
        self.estimates.clear()
        self.draw_pbr()
        self.draw_estimates()

    def rtt_settings_changed(self, *_):
        self.estimates.clear()
        self.draw_rtt()
        self.draw_estimates()

    def draw_procedure(self, *_):
        procedure = self.selected_procedure()
        reports = []
        if procedure:
            reports = ([("Initiator", i, r) for i, r in enumerate(procedure.initiator)] +
                       [("Reflector", i, r) for i, r in enumerate(procedure.reflector)])
        paths = sorted({t.antenna_path for _, _, r in reports for s in r.steps for t in s.tones[:r.num_antenna_paths]})
        old = self.path_select.currentData()
        self.path_select.blockSignals(True)
        self.path_select.clear()
        for path in paths:
            self.path_select.addItem(f"Path {path}", path)
        self.path_select.setCurrentIndex(max(0, self.path_select.findData(old)))
        self.path_select.blockSignals(False)
        if self.path_select.currentData() != old:
            self.estimates.clear()
        self.draw_pbr()
        self.draw_rtt()
        self.draw_estimates()
        self.draw_mode0()

    def draw_mode0(self):
        """Plot Mode-0 measured offsets and header compensation per initiator report."""
        reports = []
        report_numbers = {}
        for received in self.store.packets:
            packet = received.packet
            if not isinstance(packet, CsInitiatorSubeventResultPacket):
                continue
            key = (packet.config_id, packet.start_acl_conn_event, packet.procedure_counter)
            report_no = report_numbers.get(key, 0) + 1
            report_numbers[key] = report_no
            measured = [centi_ppm(step.measured_freq_offset) for step in packet.steps
                        if step.mode == 0 and step.flags & STEP_FLAG_FREQ_OFFSET_VALID]
            measured = [value for value in measured if value is not None]
            reports.append((received.timestamp, key, report_no,
                            sum(measured) / len(measured) if measured else None,
                            centi_ppm(packet.frequency_compensation)))

        if not reports:
            for curve in self.mode0_curves.values():
                curve.setData([], [])
            _fill(self.mode0_table, [])
            self.mode0_marker.setVisible(False)
            self.mode0_status = EMPTY_RESULTS_STATUS
            self.update_global_status()
            return

        timed = all(item[0] is not None for item in reports)
        selected = self.selected_procedure()
        replay = self.recording_playback or (self.session_history is not None and not self.online_mode)
        centered = replay and selected is not None and selected.time is not None and timed
        if timed:
            if centered:
                start, end = selected.time - ESTIMATE_WINDOW_S, selected.time + ESTIMATE_WINDOW_S
            else:
                end = reports[-1][0]
                start = end - ESTIMATE_WINDOW_S
            reports = [item for item in reports if start <= item[0] <= end]
            if not reports:
                for curve in self.mode0_curves.values():
                    curve.setData([], [])
                _fill(self.mode0_table, [])
                self.mode0_marker.setVisible(False)
                self.mode0_status = f"No initiator reports in the selected {ESTIMATE_WINDOW_S:.0f} s window"
                self.update_global_status()
                return
            origin = self.store.origin if self.store.origin is not None else reports[0][0]
            xs = [item[0] - origin for item in reports]
            self.mode0_plot.setLabel("bottom", "Host time since first report", units="s")
        else:
            xs = [float(index) for index in range(len(reports))]
            self.mode0_plot.setLabel("bottom", "Initiator report (arrival order; capture has no timestamps)")

        rows = []
        marker = None
        for x, (timestamp, key, report_no, measured, compensation) in zip(xs, reports):
            if selected is not None and key == selected.key and marker is None:
                marker = x
            rows.append((f"{x:.3f}" if timed else int(x), key[2], key[0], key[1], report_no,
                         "n/a" if measured is None else f"{measured:+.2f}",
                         "n/a" if compensation is None else f"{compensation:+.2f}"))
        values = {
            "Mode-0 measured offset": [math.nan if item[3] is None else item[3] for item in reports],
            "Frequency compensation": [math.nan if item[4] is None else item[4] for item in reports],
        }
        for name, curve in self.mode0_curves.items():
            data = values[name]
            curve.setData(*((xs, data) if any(not math.isnan(value) for value in data) else ([], [])))
        self.mode0_marker.setVisible(marker is not None)
        if marker is not None:
            self.mode0_marker.setValue(marker)
        _fill(self.mode0_table, rows[::-1][:ESTIMATE_TABLE_ROWS])
        span = (f"{ESTIMATE_WINDOW_S:.0f} s around selected procedure" if centered else
                f"last {ESTIMATE_WINDOW_S:.0f} s" if timed else "all retained reports")
        latest = rows[-1]
        self.mode0_status = (
            f"Latest initiator report: procedure {latest[1]} · report {latest[4]} at {latest[0]}"
            f"{' s' if timed else ''} · {len(rows)} reports ({span})")
        self.update_global_status()

    def draw_pbr(self, *_):
        for plot in (self.amplitude_plot, self.phase_plot, self.unwrapped_plot, self.ifft_plot):
            plot.clear()
            plot.plotItem.legend.clear()
        procedures, path = self.pbr_procedures(), self.path_select.currentData()
        counts = f"{len(self.store.packets)} packets · {len(self.store.procedures)} procedures"
        if not procedures or path is None:
            _fill(self.channel_table, [])
            self.summary.setText(EMPTY_RESULTS_STATUS)
            self.update_global_status()
            return
        procedure = procedures[-1]
        configuration = self.store.configurations.get(procedure.config_id)
        steps, mismatched = [], 0
        for averaged in procedures:
            averaged_configuration = self.store.configurations.get(averaged.config_id)
            averaged_steps, averaged_mismatched = averaged.pbr_steps(
                averaged_configuration, self.store.t_sw_us(averaged_configuration))
            steps.extend(averaged_steps)
            mismatched += averaged_mismatched
        results = {
            source: analyze_pbr(steps, path, source, self.sign_select.currentData(), self.quality_only.isChecked())
            for source in (CORRECTION_NONE, CORRECTION_MEASURED, CORRECTION_COMPENSATION)
        }
        raw_result = results[CORRECTION_NONE]
        measured_result = results[CORRECTION_MEASURED]
        compensation_result = results[CORRECTION_COMPENSATION]
        ifft_results = {source: ifft_range(result) for source, result in results.items()}
        ifft_distances = {source: None if profile is None else profile.peak_distance_m
                          for source, profile in ifft_results.items()}
        points = raw_result.points
        channels = [p.channel for p in points]

        def series(plot, ys, name, color, symbol="o", style=QtCore.Qt.PenStyle.SolidLine):
            plot.plot(channels, ys, name=name, pen=pg.mkPen(color, width=1.5, style=style),
                      symbol=symbol, symbolSize=5, symbolBrush=color, symbolPen=None, connect="finite")

        # A hidden line is not drawn at all, so it also leaves its plot's legend.
        shown = {line for line, check in self.pbr_line_checks.items() if check.isChecked()}
        if "initiator" in shown:
            series(self.amplitude_plot, [abs(p.initiator) for p in points], "Initiator |PCT|", SERIES["initiator"])
        if "reflector" in shown:
            series(self.amplitude_plot, [abs(p.reflector) for p in points], "Reflector |PCT|", SERIES["reflector"])
        # The amplitude plot has one product line, kept while any product line is shown.
        if shown.intersection(PBR_PRODUCT_LINES):
            series(self.amplitude_plot, [math.sqrt(abs(p.product)) for p in points], "√|product|",
                   SERIES["corrected"], "t")
        for line, name, values, color, symbol in (
                ("initiator", "Initiator ∠PCT", [cmath.phase(p.initiator) for p in points],
                 SERIES["initiator"], "o"),
                ("reflector", "Reflector ∠PCT", [cmath.phase(p.reflector) for p in points],
                 SERIES["reflector"], "o"),
                (CORRECTION_NONE, "Product raw", [cmath.phase(p.product) for p in points], SERIES["raw"], "s"),
                (CORRECTION_MEASURED, "Product corrected (Mode-0 offset)",
                 [cmath.phase(p.corrected) for p in measured_result.points],
                 SERIES["initiator"], "d"),
                (CORRECTION_COMPENSATION, "Product corrected (frequency compensation)",
                 [cmath.phase(p.corrected) for p in compensation_result.points],
                 SERIES["reflector"], "+")):
            if line not in shown:
                continue
            self.phase_plot.plot(channels, values, name=name, pen=None, symbol=symbol, symbolSize=6,
                                 symbolBrush=color, symbolPen=None)
        if CORRECTION_NONE in shown:
            series(self.unwrapped_plot, list(raw_result.unwrapped_raw), "Raw", SERIES["raw"], "s")
        for line, label, color in ((CORRECTION_MEASURED, "Mode-0 offset", SERIES["initiator"]),
                                   (CORRECTION_COMPENSATION, "Frequency compensation", SERIES["reflector"])):
            if line not in shown:
                continue
            result_to_plot = results[line]
            series(self.unwrapped_plot, list(result_to_plot.unwrapped_corrected), label, color, "t")
            if result_to_plot.fit_corrected and channels:
                slope, intercept = result_to_plot.fit_corrected
                ends = [channels[0], channels[-1]]
                self.unwrapped_plot.plot(
                    ends, [slope * (2402 + ch) * 1e6 + intercept for ch in ends],
                    name=f"{label} fit", pen=pg.mkPen(color, width=1, style=QtCore.Qt.PenStyle.DashLine))
        for source, label, color in ((CORRECTION_NONE, "Raw", SERIES["raw"]),
                                     (CORRECTION_MEASURED, "Mode-0 offset", SERIES["initiator"]),
                                     (CORRECTION_COMPENSATION, "Frequency compensation", SERIES["reflector"])):
            profile = ifft_results[source]
            if profile is not None and source in shown:
                self.ifft_plot.plot(profile.distances_m, profile.magnitude, name=label,
                                    pen=pg.mkPen(color, width=1.5))
                self.ifft_plot.plot([profile.peak_distance_m], [profile.peak_magnitude],
                                    pen=None, symbol="o", symbolSize=7, symbolBrush=color, symbolPen=None)

        _fill(self.channel_table, [
            (raw.channel, 2402 + raw.channel, raw.count, _iq(raw.initiator), _iq(raw.reflector),
             _iq(raw.product), "n/a" if measured.offset_ppm is None else f"{measured.offset_ppm:+.2f}",
             f"{measured.correction_rad:+.3f}", _iq(measured.corrected),
             "n/a" if compensation.offset_ppm is None else f"{compensation.offset_ppm:+.2f}",
             f"{compensation.correction_rad:+.3f}", _iq(compensation.corrected))
            for raw, measured, compensation in zip(raw_result.points, measured_result.points,
                                                   compensation_result.points)])

        measured_offsets = [s.offset_ppm(CORRECTION_MEASURED) for s in steps
                            if s.offset_ppm(CORRECTION_MEASURED) is not None]
        compensation_offsets = [s.offset_ppm(CORRECTION_COMPENSATION) for s in steps
                                if s.offset_ppm(CORRECTION_COMPENSATION) is not None]
        ipt = bool(configuration is not None and configuration.cs_enhancements_1 & 0x01)
        delay = next((s.delay_us for s in steps if s.delay_us is not None), None)
        notes = []
        if configuration is None:
            notes.append("no CS_CONFIGURATION for this config ID, so Δt and the correction are unknown")
        if not measured_offsets:
            notes.append("no Mode-0 measured offset available")
        if not compensation_offsets:
            notes.append("no frequency compensation value available")
        if mismatched:
            notes.append(f"{mismatched} initiator/reflector steps did not line up")
        violations = sum(s.ipt_violations for s in steps)
        if violations:
            notes.append(f"IPT protocol violation: {violations} reflector tones with non-zero Q or negative I "
                         "(only the clamped I is used as amplitude)")
        if not procedure.complete:
            notes.append("waiting for the " + ("reflector" if procedure.initiator else "initiator") + " reports")
        elif procedure.peer_data == 1:
            notes.append("initiator-only IPT analysis; reflector amplitude is unit-weighted and RTT is unavailable")
        label = f"<b>{procedure.label}</b>"
        if len(procedures) > 1:
            label = (f"<b>{len(procedures)} procedures averaged</b> (counters {procedures[0].procedure_counter}–"
                     f"{procedure.procedure_counter}, config {procedure.config_id})")
        self.pbr_complete = procedure.complete
        self.summary.setText(
            f"{counts} · {label} · {len(steps)} PBR step pairs · {len(points)} channels on path {path}"
            f" · Mode-0 offset {'n/a' if not measured_offsets else f'{sum(measured_offsets) / len(measured_offsets):+.2f} ppm'}"
            f" · frequency compensation {'n/a' if not compensation_offsets else f'{sum(compensation_offsets) / len(compensation_offsets):+.2f} ppm'}"
            f" · Δt {'n/a' if delay is None else f'{delay} µs'} ("
            f"{'T_SW_IPT' if ipt else 'T_SW'} {self.store.t_sw_us(configuration)} µs)"
            f"<br>slope distance: raw <b>{_metres(raw_result.distance_raw_m)}</b> · "
            f"Mode-0 corrected <b>{_metres(measured_result.distance_corrected_m)}</b> · "
            f"frequency compensation corrected <b>{_metres(compensation_result.distance_corrected_m)}</b>" +
            f"<br>IFFT peak: raw <b>{_metres(ifft_distances[CORRECTION_NONE])}</b> · "
            f"Mode-0 corrected <b>{_metres(ifft_distances[CORRECTION_MEASURED])}</b> · "
            f"frequency compensation corrected <b>{_metres(ifft_distances[CORRECTION_COMPENSATION])}</b>" +
            (f"<br><span style='color:#b44136'>{'; '.join(notes)}.</span>" if notes else ""))
        self.update_global_status()

    def rtt_analysis(self, procedure):
        steps, mismatched = procedure.rtt_steps()
        return analyze_rtt(steps, self.aa_success_only.isChecked(), self.max_bit_errors.value()), mismatched

    def draw_rtt(self, *_):
        for plot in (self.rtt_channel_plot, self.rtt_histogram_plot):
            plot.clear()
            plot.plotItem.legend.clear()
        procedure = self.selected_procedure()
        if procedure is None:
            _fill(self.rtt_table, [])
            self.rtt_summary.setText(EMPTY_RESULTS_STATUS)
            self.update_global_status()
            return
        result, mismatched = self.rtt_analysis(procedure)

        for mode in (1, 3):
            steps = [s for s in result.accepted if s.mode == mode]
            if steps:
                self.rtt_channel_plot.plot([s.channel for s in steps], [s.distance_m for s in steps],
                                           name=f"Mode {mode}", pen=None, symbol="o", symbolSize=6,
                                           symbolBrush=RTT_SERIES[f"mode {mode}"], symbolPen=None)
        rejected = [s for s in result.rejected if s.distance_m is not None]
        if rejected:
            self.rtt_channel_plot.plot([s.channel for s in rejected], [s.distance_m for s in rejected],
                                       name="Rejected", pen=None, symbol="x", symbolSize=6,
                                       symbolBrush=RTT_SERIES["rejected"], symbolPen=RTT_SERIES["rejected"])
        for value, name, color, style in ((result.mean_m, "Mean", RTT_SERIES["mode 1"], QtCore.Qt.PenStyle.DashLine),
                                          (result.median_m, "Median", RTT_SERIES["median"], QtCore.Qt.PenStyle.DotLine)):
            if value is not None:
                self.rtt_channel_plot.plot([0, 79], [value, value], name=name,
                                           pen=pg.mkPen(color, width=1.5, style=style))

        distances = result.distances_m
        if distances:
            # One time-difference unit on each side moves the distance by c·0.25 ns; bin on that grid.
            quantum = SPEED_OF_LIGHT_M_S * TIME_DIFFERENCE_UNIT_NS / 2 * 1e-9
            low, high = min(distances), max(distances)
            width = quantum * max(1, math.ceil((high - low) / quantum / HISTOGRAM_MAX_BINS))
            counts = Counter(round((d - low) / width) for d in distances)
            bins = sorted(counts)
            self.rtt_histogram_plot.addItem(pg.BarGraphItem(
                x=[low + b * width for b in bins], height=[counts[b] for b in bins], width=width * 0.9,
                brush=RTT_SERIES["mode 1"], pen=None))
            if result.median_m is not None:
                self.rtt_histogram_plot.addItem(pg.InfiniteLine(result.median_m, pen=pg.mkPen(
                    RTT_SERIES["median"], width=1.5, style=QtCore.Qt.PenStyle.DotLine)))

        def pair(a, b, fmt="{}"):
            return "/".join("—" if v is None else fmt.format(v) for v in (a, b))
        accepted = set(result.accepted)
        rows = []
        for s in sorted(result.accepted + result.rejected, key=lambda s: s.ordinal):
            i, r = s.initiator, s.reflector
            rows.append((s.ordinal, s.subevent, s.mode, s.channel, 2402 + s.channel,
                         "—" if i.time_difference is None else i.time_difference,
                         "—" if r.time_difference is None else r.time_difference,
                         "—" if s.tof_ns is None else f"{s.tof_ns:+.2f}",
                         "—" if s.distance_m is None else f"{s.distance_m:+.2f}",
                         pair(i.aa_quality, r.aa_quality), pair(i.bit_errors, r.bit_errors), pair(i.nadm, r.nadm),
                         pair(i.rssi, r.rssi), pair(i.antenna, r.antenna), "yes" if s in accepted else "no"))
        _fill(self.rtt_table, rows)

        total = len(result.accepted) + len(result.rejected)
        text = (f"{len(result.accepted)}/{total} RTT step pairs accepted · mean <b>{_metres(result.mean_m)}</b>"
                f" · median <b>{_metres(result.median_m)}</b> · σ {_metres(result.std_m)}")
        if mismatched:
            text += f" · <span style='color:#b44136'>{mismatched} steps did not line up</span>"
        self.rtt_summary.setText(text)
        self.update_global_status()

    def estimate(self, procedure):
        """RTT, PBR slope and IFFT peak inputs for one procedure, cached until its reports change."""
        inputs = (len(procedure.initiator), len(procedure.reflector), procedure.config_id in self.store.configurations)
        cached = self.estimates.get(procedure.key)
        if cached is not None and cached[0] == inputs:
            return cached[1]
        rtt, _ = self.rtt_analysis(procedure)
        path = self.path_select.currentData()
        configuration = self.store.configurations.get(procedure.config_id)
        steps, _ = procedure.pbr_steps(configuration, self.store.t_sw_us(configuration))
        pbr, ifft_peaks = {}, {}
        if path is not None and steps:
            for correction in (CORRECTION_NONE, CORRECTION_MEASURED, CORRECTION_COMPENSATION):
                pbr[correction] = analyze_pbr(steps, path, correction, self.sign_select.currentData(),
                                              self.quality_only.isChecked())
                profile = ifft_range(pbr[correction])
                ifft_peaks[correction] = None if profile is None else profile.peak_distance_m
        self.estimates[procedure.key] = inputs, (rtt, pbr, ifft_peaks)
        return rtt, pbr, ifft_peaks

    def estimate_window(self):
        """Complete procedures in the active estimate time window, oldest first.

        Live results show the newest ``ESTIMATE_WINDOW_S`` seconds.  Replay
        results are centered on the selected procedure, with that many
        seconds on either side.  Untimed captures (JSON lines, raw frames) are
        placed by arrival order instead.
        """
        procedures = [p for p in self.store.procedures.values() if p.complete]
        if not procedures or any(p.time is None for p in procedures):
            self._estimates_centered = False
            return [(float(n), p) for n, p in enumerate(procedures)], False
        selected = self.selected_procedure()
        replay = self.recording_playback or (self.session_history is not None and not self.online_mode)
        self._estimates_centered = replay and selected is not None and selected.time is not None
        if self._estimates_centered:
            start = selected.time - ESTIMATE_WINDOW_S
            end = selected.time + ESTIMATE_WINDOW_S
        else:
            start = procedures[-1].time - ESTIMATE_WINDOW_S
            end = procedures[-1].time
        window = []
        for procedure in reversed(procedures):
            if procedure.time < start:
                break
            if procedure.time <= end:
                window.append((procedure.time - self.store.origin, procedure))
        return window[::-1], True

    def draw_estimates(self):
        window, timed = self.estimate_window()
        self.estimates_plot.setLabel("bottom", "Host time since first report" if timed
                                     else "Procedure (arrival order; capture has no timestamps)",
                                     units="s" if timed else "")
        shown = {procedure.key for _, procedure in window}
        for key in [key for key in self.estimates if key not in shown]:
            del self.estimates[key]
        xs, rows, series = [], [], {name: [] for name in self.estimate_curves}
        selected = self.selected_procedure()
        marker = None
        for x, procedure in window:
            rtt, pbr_by_correction, ifft_peaks = self.estimate(procedure)
            raw_pbr = pbr_by_correction.get(CORRECTION_NONE)
            measured_pbr = pbr_by_correction.get(CORRECTION_MEASURED)
            compensation_pbr = pbr_by_correction.get(CORRECTION_COMPENSATION)
            xs.append(x)
            for name, value in (("RTT mean", rtt.mean_m), ("RTT median", rtt.median_m),
                                ("PBR slope (raw)", None if raw_pbr is None else raw_pbr.distance_corrected_m),
                                ("PBR slope (Mode-0 offset)", None if measured_pbr is None
                                 else measured_pbr.distance_corrected_m),
                                ("PBR slope (frequency compensation)", None if compensation_pbr is None
                                 else compensation_pbr.distance_corrected_m),
                                ("PBR IFFT (raw)", ifft_peaks.get(CORRECTION_NONE)),
                                ("PBR IFFT (Mode-0 offset)", ifft_peaks.get(CORRECTION_MEASURED)),
                                ("PBR IFFT (frequency compensation)", ifft_peaks.get(CORRECTION_COMPENSATION))):
                series[name].append(math.nan if value is None else value)
            if procedure is selected:
                marker = x
            rows.append((f"{x:.3f}" if timed else int(x), procedure.procedure_counter, procedure.config_id,
                         procedure.start_acl_conn_event, _metres(rtt.mean_m, ""), _metres(rtt.median_m, ""),
                         _metres(rtt.std_m, ""), f"{len(rtt.accepted)}/{len(rtt.accepted) + len(rtt.rejected)}",
                         _metres(None if raw_pbr is None else raw_pbr.distance_corrected_m, ""),
                         _metres(None if measured_pbr is None else measured_pbr.distance_corrected_m, ""),
                         _metres(None if compensation_pbr is None else compensation_pbr.distance_corrected_m, ""),
                         _metres(ifft_peaks.get(CORRECTION_NONE), ""),
                         _metres(ifft_peaks.get(CORRECTION_MEASURED), ""),
                         _metres(ifft_peaks.get(CORRECTION_COMPENSATION), "")))
        # Without a selected mode, keep the default view permissive.
        if self.measurement_mode is None:
            self.apply_mode()
        has_rtt, has_pbr = self.estimate_has_rtt, self.estimate_has_pbr
        for name, curve in self.estimate_curves.items():
            values = series[name]
            # An all-NaN series makes pyqtgraph warn on every redraw.
            curve.setData(*((xs, values) if any(not math.isnan(v) for v in values) else ([], [])))
        self.estimate_marker.setVisible(marker is not None)
        if marker is not None:
            self.estimate_marker.setValue(marker)
        _fill(self.estimates_table, rows[::-1][:ESTIMATE_TABLE_ROWS], resize=not self.estimates_table.rowCount())
        if not rows:
            self.estimates_summary.setText(EMPTY_RESULTS_STATUS)
            self.update_global_status()
            return
        latest = rows[-1]
        if timed and self._estimates_centered:
            span = f"{ESTIMATE_WINDOW_S:.0f} s around selected procedure"
        elif timed:
            span = f"last {ESTIMATE_WINDOW_S:.0f} s"
        else:
            span = "all retained procedures"
        details = []
        if has_rtt:
            details.append(f"RTT mean <b>{_metres(rtt.mean_m)}</b> · median <b>{_metres(rtt.median_m)}</b>")
        if has_pbr:
            details.append(
                f"PBR slope: raw <b>{_metres(None if raw_pbr is None else raw_pbr.distance_corrected_m)}</b> · "
                f"Mode-0 <b>{_metres(None if measured_pbr is None else measured_pbr.distance_corrected_m)}</b> · "
                f"frequency compensation <b>{_metres(None if compensation_pbr is None else compensation_pbr.distance_corrected_m)}</b>"
            )
            details.append(
                f"PBR IFFT: raw <b>{_metres(ifft_peaks.get(CORRECTION_NONE))}</b> · "
                f"Mode-0 <b>{_metres(ifft_peaks.get(CORRECTION_MEASURED))}</b> · "
                f"frequency compensation <b>{_metres(ifft_peaks.get(CORRECTION_COMPENSATION))}</b>"
            )
        self.estimates_summary.setText(
            f"Latest: procedure {latest[1]} at {latest[0]}{' s' if timed else ''}"
            f" · {'<br>'.join(details)} · {len(rows)} procedures ({span})")
        self.update_global_status()
