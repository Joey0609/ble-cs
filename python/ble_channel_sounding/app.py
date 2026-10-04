"""Integrated host UI for configuration, live measurements and run recording."""
import argparse
from datetime import datetime
import logging
from pathlib import Path
import sys
from PyQt6 import QtCore, QtGui, QtWidgets as W
import pyqtgraph as pg
from . import __version__
from .protocol import PROTOCOL_VERSION
from .protocol.config import ClientConfig
from .protocol.packets import (OperationMode, OperationModeMask, PeripheralPatternsPacket, DeviceNamePacket, ClientState, CsFaeTablePacket, PacketType, ProtocolStatus,
                                ConnectionParametersPacket, CommandResponsePacket, ConnectResponsePacket, CsCapabilitiesPacket, CsConfigurationPacket,
                                CsInitiatorConfigPacket, CsProcedureEnableCompletePacket, CsReflectorConfigPacket,
                                ClientStatePacket, T_PM_DEFAULT_US)
from .planner.bridge import HOST_DEFAULTS
from .planner.model import uses_pbr
from .log_config import DEFAULT_LOG, log_packet, normalize_log
from .views.results_view import ResultsWidget
from .views.radio_results_view import RadioResultsWidget
from .views.controller_view import ControllerView
from .planner.export_c import document, load_document
from .qt_session import QtSession
from .session import LINK_ACTIVE, NOT_SYNCED
from .transport import SerialTransport
from .simulator import Simulator
from .views.port_view import PortView, SIMULATOR
from .views.general_view import GeneralView
from .views.recording_view import RecordingView
from .views import tooltips
from .views.sync_dialog import SyncDialog
from .views.cs_view import CsView
from .views.radio_test_view import RadioTestView, preset_json
from .views.run_bar import RunBar
from .views.peers_view import PeersView
from .views.peer_console_view import PeerConsoleView
from .views.help_dialog import HelpDialog
from .peer_console import PeerConsoleReader
from .report_log import ERROR, INFO, WARNING
from .session_history import HostMessage, normalize_host_level
from .recorder import update_description

APP_ICON = Path(__file__).resolve().parent / "assets" / "logo" / "senswear-logo.png"


def link_state_name(state):
    try:
        return ClientState(state).name
    except ValueError:
        return str(state)


PEER_LINKED_STATES = (ClientState.LINK_CONNECTED, ClientState.RAS_READY,
                      ClientState.RUNNING, ClientState.STOPPED)


class _SaveSignals(QtCore.QObject):
    finished = QtCore.pyqtSignal(str)
    failed = QtCore.pyqtSignal(str)


class _HostLogBridge(QtCore.QObject):
    """Marshal logging records from worker threads onto the GUI thread."""

    message = QtCore.pyqtSignal(str, str, str)


class _PeerConsoleBridge(QtCore.QObject):
    """Marshal serial-reader callbacks onto the GUI thread."""

    line = QtCore.pyqtSignal(str, str, object)
    error = QtCore.pyqtSignal(str)


class _SaveSessionJob(QtCore.QRunnable):
    def __init__(self, history, path, kwargs):
        super().__init__()
        self.history, self.path, self.kwargs = history, path, kwargs
        self.signals = _SaveSignals()

    def run(self):
        try:
            self.history.save_hdf5(self.path, **self.kwargs)
        except Exception as error:
            self.signals.failed.emit(str(error))
        else:
            self.signals.finished.emit(str(self.path))


class _AppLogHandler(logging.Handler):
    """Route warning-and-error application logging into the current history."""

    def __init__(self, bridge):
        super().__init__(level=logging.WARNING)
        self.bridge = bridge

    def emit(self, record):
        try:
            level = ERROR if record.levelno >= logging.ERROR else WARNING
            self.bridge.message.emit(level, record.name, self.format(record))
        except Exception:
            # A diagnostic handler must never create a logging recursion or affect the app.
            pass


class _RunDescriptionDialog(W.QDialog):
    """Non-modal editor for the description of a completed recording."""

    saved = QtCore.pyqtSignal(str)

    def __init__(self, path, initial="", parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.setWindowTitle("Run description")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = W.QVBoxLayout(self)
        layout.addWidget(W.QLabel(f"Description for {self.path.name}"))
        self.editor = W.QPlainTextEdit(str(initial or ""))
        self.editor.setPlaceholderText("Optional notes about this run")
        self.editor.setMinimumSize(440, 130)
        layout.addWidget(self.editor)
        buttons = W.QDialogButtonBox()
        self.save_button = buttons.addButton("Save", W.QDialogButtonBox.ButtonRole.AcceptRole)
        self.skip_button = buttons.addButton("Skip", W.QDialogButtonBox.ButtonRole.RejectRole)
        self.save_button.clicked.connect(self.save_text)
        self.skip_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def save_text(self, *_args, silent=False):
        try:
            update_description(self.path, self.editor.toPlainText())
        except (OSError, ValueError) as error:
            if not silent:
                W.QMessageBox.warning(self, "Cannot save description", str(error))
            return False
        self.saved.emit(self.editor.toPlainText())
        self.accept()
        return True


class MainWindow(W.QMainWindow):
    def __init__(self, *, simulate=False, capture=None):
        super().__init__()
        self.setWindowTitle("BLE Channel Sounding Host")
        self.setWindowIcon(QtGui.QIcon(str(APP_ICON)))
        self.resize(1500, 1000)
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("Help topics…", lambda: self.show_help())
        help_menu.addAction("About BLE Channel Sounding Host", self.show_about)
        self.loading = False
        self.mode = OperationMode.CS_INITIATOR
        self.run_number = 0
        self.link_number = 0
        self._active_recording_path = None
        self._session_recorded = False
        self._session_saved = False
        self._close_after_save = False
        self._scan_guidance_announced = False
        self._active_alerts = []
        # Set once the window close is certain: closing ends the run too, and
        # its own unsaved-session prompt replaces the end-of-run offer.
        self._closing = False
        self._description_dialog = None
        self._help_dialog = None
        self._peer_console_transport = None
        self._peer_console_reader = None
        self._peer_console_bridge = _PeerConsoleBridge(self)
        self._peer_console_bridge.line.connect(self.peer_console_line)
        self._peer_console_bridge.error.connect(self.peer_console_error)
        self._host_log_bridge = _HostLogBridge(self)
        self._host_log_bridge.message.connect(self._record_host_from_log)
        self.qt = QtSession(self)
        self.session = self.qt.core
        # The simulator is always offered as a port; --simulate only preselects it (and loads a capture).
        self.capture = capture
        self.simulator = Simulator(capture=capture) if simulate else None
        root = W.QWidget()
        layout = W.QVBoxLayout(root)
        self.setCentralWidget(root)
        # Top panel: serial port and recording settings side by side, with the
        # session actions in a detachable toolbar above them.
        top = W.QFrame()
        top.setFrameShape(W.QFrame.Shape.StyledPanel)
        top_layout = W.QVBoxLayout(top)
        top_layout.setContentsMargins(6, 4, 6, 4)
        top_layout.setSpacing(4)
        top_summary = W.QFrame()
        top_summary.setObjectName("configurationSummary")
        top_summary_layout = W.QHBoxLayout(top_summary)
        top_summary_layout.setContentsMargins(0, 0, 0, 0)
        self.configuration_summary = W.QToolButton()
        self.configuration_summary.setObjectName("configurationSummaryText")
        self.configuration_summary.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.configuration_summary.setAutoRaise(False)
        self.configuration_summary.setSizePolicy(W.QSizePolicy.Policy.Expanding, W.QSizePolicy.Policy.Fixed)
        self.configuration_summary.clicked.connect(self.toggle_configuration_panel)
        top_summary_layout.addWidget(self.configuration_summary, 1)
        self.configuration_toggle = W.QToolButton()
        self.configuration_toggle.setObjectName("configurationSummaryToggle")
        self.configuration_toggle.setText("▲")
        self.configuration_toggle.setToolTip("Expand or collapse configuration controls")
        self.configuration_toggle.setAutoRaise(True)
        self.configuration_toggle.clicked.connect(self.toggle_configuration_panel)
        top_summary_layout.addWidget(self.configuration_toggle)
        self.configuration_panel = W.QFrame()
        self.configuration_panel.setObjectName("configurationPanel")
        configuration_layout = W.QVBoxLayout(self.configuration_panel)
        configuration_layout.setContentsMargins(0, 0, 0, 0)
        configuration_layout.setSpacing(4)
        groups = W.QHBoxLayout()
        self.port_view = PortView()
        self.peer_console_view = PeerConsoleView()
        self.serial_port_group = W.QGroupBox("Serial port")
        serial_port_layout = W.QVBoxLayout(self.serial_port_group)
        serial_port_layout.setContentsMargins(4, 4, 4, 4)
        serial_port_layout.setSpacing(0)
        self.serial_port_tabs = W.QTabWidget()
        self.serial_port_tabs.setObjectName("serialPortTabs")
        self.serial_port_tabs.addTab(self.port_view, "Client")
        peer_console_tab = self.serial_port_tabs.addTab(self.peer_console_view, "Peer")
        self.serial_port_tabs.setTabEnabled(peer_console_tab, False)
        serial_port_layout.addWidget(self.serial_port_tabs)
        self.general_view = GeneralView()
        self.recording_view = RecordingView()
        for group, stretch in ((self.serial_port_group, 1), (self.recording_view, 1)):
            groups.addWidget(group, stretch)
        configuration_layout.addLayout(groups)
        self.run_bar = RunBar()
        self.peers_view = PeersView()
        self.peers_view.scan = self.run_bar.buttons["Scan"]
        self.peers_view.connect = self.run_bar.buttons["Connect peer"]
        self._peer_controls_visible = False
        self._peer_connect_attempt = None
        self._reconnect_after_peer_disconnect = False
        self.run_bar.add_peer_controls(self.peers_view.peers, self.peers_view.show_all)
        configuration_layout.addWidget(self.peers_view)
        self.run_bar.buttons["Scan"].clicked.connect(lambda: self.invoke(self.scan_peers))
        self.run_bar.buttons["Connect peer"].clicked.connect(lambda: self.invoke(self.toggle_peer_connection))
        self.peers_view.advertise.clicked.connect(lambda: self.invoke(self.session.advertise))
        self.peers_view.show_all.toggled.connect(
            lambda _checked: (self.refresh_peers(replace=True), self.update_controls()))
        self.peer_console_view.open_requested.connect(self.open_peer_console)
        self.peer_console_view.close_requested.connect(self.close_peer_console)
        self.peer_console_view.settings_changed.connect(self.peer_console_settings_changed)
        # A QToolBar can only be docked and floated by a QMainWindow. Keep the
        # session toolbar local to the top configuration section, just as the
        # planner toolbar is local to the Configuration view.
        top_content = W.QWidget()
        top_content_layout = W.QVBoxLayout(top_content)
        top_content_layout.setContentsMargins(0, 0, 0, 0)
        top_content_layout.setSpacing(4)
        top_content_layout.addWidget(top_summary)
        top_content_layout.addWidget(self.configuration_panel)
        self.general_control_host = W.QMainWindow()
        self.general_control_host.setObjectName("generalControlHost")
        self.general_control_host.setCentralWidget(top_content)
        self.general_toolbar = W.QToolBar("General settings")
        self.general_toolbar.setObjectName("generalToolbar")
        self.general_toolbar.setMovable(True)
        self.general_toolbar.setFloatable(True)
        self.general_toolbar.addWidget(W.QLabel("Operation mode:"))
        self.general_toolbar.addWidget(self.general_view.mode)
        self.general_toolbar.addSeparator()
        self.general_toolbar.addWidget(W.QLabel("Console log:"))
        self.general_toolbar.addWidget(self.general_view.log_controls["console"])
        self.general_toolbar.addWidget(W.QLabel("Host log:"))
        self.general_toolbar.addWidget(self.general_view.log_controls["host"])
        self.general_control_host.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, self.general_toolbar)
        self.general_control_host.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, self.run_bar)
        top_layout.addWidget(self.general_control_host)
        layout.addWidget(top)
        self.setStyleSheet(self.styleSheet() + """
            QFrame#configurationSummary { background: #eef3f9; border: 1px solid #cbd8e6; border-radius: 4px; }
            QToolButton#configurationSummaryText { color: #21334b; font-size: 12px; font-weight: normal; text-align: left; border: 0; border-radius: 3px; padding: 7px 9px; }
            QToolButton#configurationSummaryToggle { color: #536981; font-size: 12px; border: 0; padding: 5px 9px; }
            QFrame#configurationPanel { background: transparent; }
            QMainWindow#generalControlHost { background: transparent; }
        """)
        # Status bar: port / client status left-aligned, then transient messages, session state on the right.
        # Transient messages use our own label: QStatusBar.showMessage would hide the left-aligned widgets.
        self.port_status = W.QLabel()
        self.statusBar().addWidget(self.port_status)
        self.message_label = W.QLabel()
        self.message_label.setSizePolicy(W.QSizePolicy.Policy.Ignored, W.QSizePolicy.Policy.Preferred)
        self.statusBar().addWidget(self.message_label, 1)
        self.message_timer = QtCore.QTimer(self, singleShot=True)
        self.message_timer.timeout.connect(self.message_label.clear)
        self.state_label = W.QLabel("Disconnected")
        self.statusBar().addPermanentWidget(self.state_label)
        self.tabs = W.QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.cs_view = CsView()
        # Keep the long-standing GeneralView API for callers and saved-session
        # helpers, while the actual field is rendered in CS setup.
        self.general_view.device_name = self.cs_view.device_name
        self.cs_view.host_settings["peripheral_patterns"] = ["CS"]
        self.cs_view.populate()
        self.peer_console_view.set_settings(self.cs_view.host_settings.get("peer_console", {}))
        self.cs_view.host_settings["peer_console"] = self.peer_console_view.settings()
        self.radio_view = RadioTestView()
        # RadioTestView already owns the left settings tabs and right preview;
        # do not wrap it in a second, single-page tab widget.
        self.config_stack = W.QStackedWidget()
        # QToolBar floating/movement is implemented by QMainWindow. Keep that
        # window local to Configuration so the toolbar never becomes global app chrome.
        self.configuration_host = W.QMainWindow()
        self.configuration_host.setObjectName("configurationViewHost")
        self.configuration_host.setCentralWidget(self.cs_view)
        self.configuration_toolbar = self.cs_view.action_toolbar
        self.configuration_toolbar.setObjectName("configurationToolbar")
        self.configuration_toolbar.setMovable(True)
        self.configuration_toolbar.setFloatable(True)
        self.configuration_toolbar.setAllowedAreas(
            QtCore.Qt.ToolBarArea.TopToolBarArea | QtCore.Qt.ToolBarArea.BottomToolBarArea
        )
        self.configuration_host.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, self.configuration_toolbar)
        self.config_stack.addWidget(self.configuration_host)
        self.config_stack.addWidget(self.radio_view)
        self.tabs.addTab(self.config_stack, "Configuration")
        self.controller_view = ControllerView()
        self.results = ResultsWidget(controller=self.controller_view, recording_playback=bool(capture))
        self.results.replay_configuration_loaded.connect(self.replay_configuration_loaded)
        self.radio_results = RadioResultsWidget()
        self.results_stack = W.QStackedWidget()
        self.results_stack.addWidget(self.results)
        self.results_stack.addWidget(self.radio_results)
        self.tabs.addTab(self.results_stack, "Results")
        # The Session tab is the timeline of the open session (live, last or a capture); Results
        # keeps the analysis views and owns the session the timeline shows.
        self.session_view = self.results.session_view
        self.tabs.addTab(self.session_view, "Session")
        self.results.session_path_factory = self.default_session_path
        self._session_started_at = None
        self._save_offered = False
        self._log_handler = _AppLogHandler(self._host_log_bridge)
        logging.getLogger("ble_channel_sounding").addHandler(self._log_handler)
        self.port_view.connect_requested.connect(self.connect_port)
        self.port_view.status_message.connect(self.port_status.setText)
        self.general_view.selected.connect(self.select_role)
        self.cs_view.device_name.textChanged.connect(self.device_name_edited)
        self.general_view.log_changed.connect(self.log_edited)
        self.general_view.gap_role_changed.connect(self.cs_view.set_gap_role)
        self.general_view.patterns_changed.connect(self.cs_view.set_patterns)
        self.radio_view.log_changed.connect(self.log_edited)
        self.cs_view.role_changed.connect(self.select_role)
        self.cs_view.populated.connect(self.restore_general)
        self.general_view.set_host(self.cs_view.host_settings["gap_role"], self.cs_view.host_settings["peripheral_patterns"])
        self.general_view.set_log(self.cs_view.host_settings.get("log", DEFAULT_LOG))
        self.radio_view.set_log(self.general_view.log_config())
        self.cs_view.configuration_changed.connect(self.edited)
        self.radio_view.configuration_changed.connect(self.edited)
        self.qt.packet_sent.connect(self.packet_sent)
        self.qt.packet_received.connect(self.packet_received)
        self.qt.session_started.connect(self.clear_session_reports)
        self.qt.session_started.connect(self.peer_console_session_started)
        self.qt.history_started.connect(self.history_started)
        self.qt.history_error.connect(self.history_error)
        self.results.save_session_requested.connect(self.save_session)
        self.recording_view.save_session_requested.connect(self.session_view.save_session)
        self.recording_view.history_limit_changed.connect(self.history_limit_changed)
        self.history_limit_changed(self.recording_view.history_bytes())
        self.qt.config_received.connect(self.config_received)
        self.qt.attached_to_run.connect(self.attached_to_run)
        self.qt.sync_changed.connect(lambda state: self.results_peer_data())
        self.qt.config_received.connect(lambda config: self.results_peer_data())
        self.qt.client_info.connect(self.client_info)
        self.qt.link_error.connect(self.error)
        self.qt.sync_failed.connect(self.config_sync_failed)
        self.qt.start_failed.connect(self.start_failed)
        self.qt.recording_discarded.connect(self.recording_discarded)
        self.qt.command_result.connect(self.command_result)
        self.qt.state_changed.connect(self.session_state_changed)
        self.qt.link_state_changed.connect(lambda state: self.update_controls())
        self.qt.sync_changed.connect(lambda state: self.update_controls())
        self.tabs.currentChanged.connect(self.update_configuration_toolbar)
        self.config_stack.currentChanged.connect(self.update_configuration_toolbar)
        self.qt.run_started.connect(self.radio_run_started)
        self.qt.run_started.connect(self.apply_result_mode)
        self.qt.run_started.connect(lambda reason: self.update_controls())
        self.qt.run_finished.connect(self.run_finished)
        self.qt.run_finished.connect(lambda _reason: self.close_peer_console())
        self.qt.run_started.connect(self.peer_console_run_started)
        self.cs_view.status_message.connect(self.show_message)
        self.run_bar.buttons["Connect"].clicked.connect(self.toggle_connection)
        self.run_bar.buttons["Apply config"].clicked.connect(self.apply)
        self.run_bar.buttons["Describe session"].clicked.connect(lambda: self.results.edit_description())
        self.run_bar.buttons["Open capture…"].clicked.connect(self.open_capture)
        self.run_bar.buttons["Clear"].clicked.connect(self.clear_results)
        self.run_bar.buttons["Help"].clicked.connect(lambda: self.show_help(topic="toolbar"))
        for label, method in (("Synchronise", self.resolve_sync), ("Start session", self.start),
                              ("Stop session", self.session.stop),
                              ("Record from now", self.session.record_from_now)):
            self.run_bar.buttons[label].clicked.connect(lambda checked=False, method=method: self.invoke(method))
        self.recording_view.logging.toggled.connect(self.logging_changed)
        self.recording_view.converted.connect(lambda path: self.show_message(f"Wrote {path}", 5000))
        self.poll = QtCore.QTimer(self, interval=100)
        self.poll.timeout.connect(self.tick)
        self.poll.start()
        self.select_role(self.mode)
        self.update_controls()
        self.update_configuration_toolbar()
        if simulate:
            self.port_view.port.setCurrentIndex(self.port_view.port.findData(SIMULATOR))

    def record_host(self, text, *, level=INFO, source="host", timestamp=None):
        """Persist one host-side or peer-console message in the open session's timeline.

        Before the first session there is no history file; the message then goes to the
        in-memory store, which the Session tab shows until a session starts.
        """
        text = str(text)
        if self.session.history is None:
            self.results.add_packet(HostMessage(normalize_host_level(level), source, text), timestamp)
            return
        self.session.record_host(level, source, text, timestamp=timestamp)
        self.results.draw_history()

    @QtCore.pyqtSlot(str, str, str)
    def _record_host_from_log(self, level, source, text):
        self.record_host(text, level=level, source=source)

    def peer_console_settings_changed(self, settings):
        self.cs_view.host_settings["peer_console"] = dict(settings)

    def _configured_peer_console(self):
        settings = self.cs_view.host_settings.get("peer_console", {})
        if not isinstance(settings, dict):
            return None
        port = str(settings.get("port", "")).strip()
        try:
            baud = int(settings.get("baud", 921600))
        except (TypeError, ValueError):
            return None
        return (port, baud) if port and baud > 0 else None

    def peer_console_session_started(self, *_):
        if self.mode == OperationMode.HOSTLESS_CS:
            self.peer_console_run_started("partial")

    def peer_console_run_started(self, reason):
        if reason not in ("started", "partial") or self._peer_console_transport is not None:
            return
        settings = self._configured_peer_console()
        if settings is not None:
            self.open_peer_console(*settings)

    def show_message(self, text, timeout=0, level=INFO, source="host"):
        self.message_label.setText(str(text))
        if timeout:
            self.message_timer.start(timeout)
        else:
            self.message_timer.stop()
        self.record_host(text, level=level, source=source)

    def show_alert(self, title, text, *, warning=False):
        """Show a dismissible alert without blocking scan and session updates."""
        box = W.QMessageBox(self)
        box.setIcon(W.QMessageBox.Icon.Warning if warning else W.QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(text)
        box.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self._active_alerts.append(box)
        box.finished.connect(lambda _result, alert=box: self._active_alerts.remove(alert)
                             if alert in self._active_alerts else None)
        box.open()

    def invoke(self, method):
        try:
            method()
        except (ValueError, OSError, TypeError) as error:
            self.error(str(error))
        self.update_controls()

    def error(self, text):
        if self.session.state == "FAILED" and self.session.info is None and getattr(self, "port_name", None):
            self.port_view.mark_rejected(self.port_name, str(text))  # connect handshake failed
        self.port_status.setText(str(text))
        self.show_message(text, level=ERROR)
        self.update_controls()

    def toggle_configuration_panel(self):
        expanded = not self.configuration_panel.isVisible()
        self.configuration_panel.setVisible(expanded)
        self.configuration_toggle.setText("▲" if expanded else "▼")

    def update_configuration_toolbar(self, *_):
        """Keep the detachable toolbar scoped to the visible Configuration page."""
        visible = (
            self.tabs.currentWidget() is self.config_stack
            and self.config_stack.currentWidget() is self.configuration_host
        )
        self.configuration_toolbar.setVisible(visible)

    def update_configuration_summary(self):
        """Update the compact disclosure summary for the upper configuration panel."""
        port = self.port_view.port.currentText().strip() or "No port selected"
        if len(port) > 42:
            port = port[:39] + "…"
        baud = self.port_view.baud.currentText().strip() or "—"
        mode = self.general_view.mode.currentText() or "No mode"
        role = self.cs_view.host_controls["gap_role"].currentText()
        recording = "on" if self.recording_view.logging.isChecked() else "off"
        session = self.session.state.replace("_", " ").lower()
        self.configuration_summary.setText(
            f"Configuration  ·  {port}  ·  {baud} baud  ·  {mode}  ·  {role}  ·  Recording {recording}  ·  {session}"
        )

    def config_sync_failed(self, text):
        """Show a configuration refusal prominently, including its concrete reason."""
        self.error(str(text))
        W.QMessageBox.warning(self, "Configuration synchronisation refused", str(text))

    def connect_port(self, port, baud):
        if self.session.transport:
            return
        self.port_name, self.baud = port, baud
        if port == SIMULATOR:
            if self.simulator is None:
                self.simulator = Simulator(capture=self.capture)
            transport = self.simulator.transport
        else:
            transport = SerialTransport(port, baud, self)
        hostless = self.general_view.mode.currentData() == OperationMode.HOSTLESS_CS
        if hostless:
            self.session.connect_hostless(transport)
        else:
            self.session.connect(transport)
        # Hostless connections have no CLIENT_INFO response to confirm a
        # successful open. Only replace the port status after the transport
        # actually reached HOSTLESS CS; otherwise retain the open error that
        # ``connect_hostless`` reported.
        if hostless and self.session.state == "HOSTLESS CS" and self.session.transport is not None:
            self.port_view.clear_rejected(port)
            self.port_status.setText("Hostless CS · receiving protocol frames")
        self.update_controls()

    def toggle_connection(self):
        """Connect, cancel CONNECT, or end the client session but keep its port open."""
        if self.session.transport is None:
            self.port_view.connect_port()
        elif self.session.state == "DISCONNECTED":
            # Disconnect link ended the session but left the port open (§7.8):
            # a new handshake goes over the transport that is already there.
            self.invoke(self.session.reconnect)
        elif self.session.state == "CONNECTING":
            self.invoke(self.session.cancel_connect)
            if self.session.transport is None:
                port = getattr(self, "port_name", None) or "the port"
                self.port_status.setText(f"Connection to {port} cancelled")
                self.show_message(f"Connection to {port} cancelled")
        else:
            if self.session.hostless:
                self.invoke(self.session.close)
            else:
                self.invoke(self.session.disconnect_link)

    def clear_session_reports(self):
        """Start each device connection with reports belonging only to it."""
        self.results.clear()
        self.radio_results.clear()
        self.controller_view.clear()
        self.peers_view.clear()
        self.port_status.clear()
        self.message_timer.stop()
        self.message_label.clear()
        self.link_number = 0
        self._active_recording_path = None
        self._session_recorded = False
        self._session_saved = False
        self.results.session_recording_path = None
        # A new session starts without a Results mode selection. The planner
        # mode is applied only after START is confirmed.
        self.results.set_measurement_mode(None)

    @staticmethod
    def client_status_text(info):
        return (f"Firmware 0x{info.firmware_version:08x} · state {info.client_state} · "
                f"configuration {'held' if info.config_valid else 'empty'} · "
                f"Connected board supports {info.num_antennas_supported} "
                f"{'antenna' if info.num_antennas_supported == 1 else 'antennas'}")

    def client_info(self, info):
        self.port_view.clear_rejected(getattr(self, "port_name", None))
        self.port_status.setText(self.client_status_text(info))
        self.general_view.set_supported_modes(info.supported_modes)
        if info.config_valid:
            self.select_role(OperationMode(info.operation_mode))
        # A running client's configuration is fetched by the session (attached_to_run).
        if not self.session.in_sync and not self.session.attached_to_run:
            QtCore.QTimer.singleShot(0, self.resolve_sync)

    def attached_to_run(self, event):
        """The client was already running: its configuration now replaces the host's."""
        differences = event["differences"]
        if differences is None:
            detail = "This host had no configuration of its own."
        elif not differences:
            detail = "It matches this host's configuration."
        else:
            detail = "It differs from this host's configuration in: " + ", ".join(differences) + "."
        text = ("Attached to a run that this host did not start. The client's configuration was "
                "loaded into the views; the run was not stopped. " + detail)
        self.error(text)
        W.QMessageBox.warning(self, "Client already running", text)

    def results_peer_data(self):
        """Results need the reflector data setting: CS_PEER_DATA comes only once per link."""
        peer_data = self.session.applied_peer_data
        if peer_data is not None:
            self.results.set_peer_data(peer_data)

    def resolve_sync(self):
        if self.session.transport is None:
            return
        dialog = SyncDialog(self.session.host_config, self.session.client_config, self,
                            client_empty=not self.session.client_valid)
        dialog.exec()
        if dialog.action == "get":
            if (self.session.host_config is not None and self.session.client_valid
                    and not self.session.in_sync):
                answer = W.QMessageBox.warning(
                    self, "Replace UI configuration?",
                    "The UI configuration will be overwritten by the configuration of the device. Are you sure?",
                    W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.Cancel,
                    W.QMessageBox.StandardButton.Cancel)
                if answer != W.QMessageBox.StandardButton.Yes:
                    message = "Upload the current UI configuration to the device instead?"
                    active = self.session.link_state in LINK_ACTIVE
                    if active:
                        message += " This will stop active Bluetooth activity and disconnect the peer if connected."
                    upload = W.QMessageBox.question(
                        self, "Upload UI configuration?", message,
                        W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.No,
                        W.QMessageBox.StandardButton.No)
                    if upload == W.QMessageBox.StandardButton.Yes:
                        self.apply(disconnect_confirmed=active)
                    return
            self.invoke(self.session.fetch_config)
        elif dialog.action == "apply":
            self.apply()

    def select_role(self, mode):
        self.mode = OperationMode(mode)
        if self.mode == OperationMode.RADIO_TX_TEST:
            self.show_alert(
                "Radio Test is disabled",
                "Radio Test is temporarily unavailable in this application build.",
                warning=True,
            )
            self.mode = OperationMode.CS_INITIATOR
        if self.mode == OperationMode.CS_REFLECTOR:
            self.mode = OperationMode.CS_INITIATOR
        self.general_view.set_mode(self.mode)
        radio = self.mode == OperationMode.RADIO_TX_TEST
        hostless = self.mode == OperationMode.HOSTLESS_CS
        self.config_stack.setCurrentWidget(self.radio_view if radio else self.configuration_host)
        if not radio:
            self.cs_view.settings.setCurrentWidget(self.cs_view.host_page)
        # CS views keep their settings but stop updating while the radio test is selected.
        self.cs_view.set_dormant(radio)
        self.cs_view.set_readonly(hostless)
        if not radio and not hostless:
            self.cs_view.set_mode(self.mode)
        results_index = self.tabs.indexOf(self.results_stack)
        self.results_stack.setCurrentWidget(self.radio_results if radio else self.results)
        self.tabs.setTabText(results_index, "Radio RX results" if radio else "Results")
        self.tabs.setTabToolTip(results_index, "Radio RX statistics" if radio else "CS measurement results")
        if hostless:
            self.results.set_measurement_mode(None)
            # Nothing is requested of a hostless device, so the Controller tab drops
            # the configuration the previous mode left on it.
            self.update_requested()
        else:
            self.edited()

    def device_name_edited(self, name):
        self.cs_view.host_settings["device_name"] = name
        self.edited()

    def log_edited(self, value):
        """Keep the General controls and radio presets on the same log levels."""
        levels = normalize_log(value)
        self.cs_view.host_settings["log"] = levels
        self.general_view.set_log(levels)
        self.radio_view.set_log(levels)
        self.edited()

    def restore_general(self):
        host = self.cs_view.host_settings
        self.peer_console_view.set_settings(host.get("peer_console", {}))
        host["peer_console"] = self.peer_console_view.settings()
        self.general_view.set_device_name(host.get("device_name", ""))
        self.cs_view.set_device_name(host.get("device_name", ""))
        self.general_view.set_host(host["gap_role"], host.get("peripheral_patterns", []))
        self.general_view.set_log(host.get("log", DEFAULT_LOG))
        self.radio_view.set_log(self.general_view.log_config())
        if not self.loading:
            self.edited()

    def collect_config(self):
        if self.mode == OperationMode.HOSTLESS_CS:
            raise ValueError("Hostless CS has no host configuration")
        if self.mode == OperationMode.RADIO_TX_TEST:
            raise ValueError("Radio Test is temporarily disabled in this application build")
        packet = self.cs_view.collect_config(self.mode)
        names = self.cs_view.collect_patterns()
        name = self.cs_view.host_settings.get("device_name", "")
        return ClientConfig(self.mode, packet, PeripheralPatternsPacket.from_patterns(names) if names else None,
                            DeviceNamePacket.from_name(name) if name else None,
                            self.cs_view.host_settings.get("peer_data", 0),
                            log=log_packet(self.general_view.log_config()),
                            t_pm=self.requested_t_pm())

    def requested_t_pm(self):
        """Preferred T_PM to send; only a CS initiator carries one (SET_T_PM)."""
        if self.mode != OperationMode.CS_INITIATOR or not uses_pbr(self.cs_view.scenario.configuration.mode):
            return T_PM_DEFAULT_US
        return self.cs_view.host_settings.get("t_pm", HOST_DEFAULTS["t_pm"])

    def edited(self):
        if self.loading or self.mode == OperationMode.HOSTLESS_CS:
            self.update_requested()
            return
        try:
            config = self.collect_config()
            self.session.set_host_config(config)
        except (ValueError, TypeError):
            self.session.set_host_config(None)
        self.update_requested()
        self.update_controls()

    def current_results(self):
        """The results widget the Results tab shows: CS analysis, or radio RX."""
        return self.results_stack.currentWidget()

    def open_capture(self):
        """Session toolbar *Open capture…*: load a file into the results view on show."""
        self.current_results().open_capture()

    def clear_results(self):
        """Session toolbar *Clear*: drop what the results view on show holds."""
        self.current_results().clear()

    def replay_configuration_loaded(self, context):
        """Restore the configuration view from a replayed session's saved configuration."""
        if self.current_results() is not self.results or not isinstance(context, dict):
            return

        scenario = None
        host = None
        scenario_json = context.get("scenario_json", "")
        try:
            if scenario_json:
                scenario, host = load_document(scenario_json)
        except (TypeError, ValueError, KeyError) as error:
            self.show_message(f"Replay configuration could not be loaded: {error}", 10000, level=WARNING)
            return

        host_config = context.get("host_config")
        # Only a hosted recording carries the configuration its host asked for. The
        # role a hostless one reports is what the link settled on, not a request, so
        # replaying it keeps the selected mode and compares its reports with nothing.
        hosted = host_config is not None or scenario is not None
        role = (0 if isinstance(host_config, CsInitiatorConfigPacket) else
                1 if isinstance(host_config, CsReflectorConfigPacket) else
                getattr(scenario.configuration, "role", None) if scenario is not None else None)
        packets = [context.get(name) for name in ("host_config", "selected_config", "procedure", "connection")]
        packets = [packet for packet in packets if packet is not None]
        if scenario is None and not packets:
            return

        self.loading = True
        try:
            if role in (OperationMode.CS_INITIATOR, OperationMode.CS_REFLECTOR):
                self.select_role(role)
            if scenario is not None:
                self.cs_view.host_settings = host
                self.cs_view.apply_config(scenario)
            if packets:
                self.cs_view.apply_config(*packets)

            # These settings are stored separately from the planner and host
            # configuration packets in the HDF5 config group.
            host = dict(self.cs_view.host_settings)
            for key in ("peer_data", "t_pm", "patterns", "device_name", "log"):
                if key not in context:
                    continue
                target = "peripheral_patterns" if key == "patterns" else key
                host[target] = context[key]
            self.cs_view.host_settings = host
            self.cs_view.populate()
            if hosted:
                self.update_requested()
            else:
                self.controller_view.set_requested(None)
        finally:
            self.loading = False

    def apply_result_mode(self, reason):
        """Apply the planner mode only when a new hosted run is confirmed."""
        if reason != "started" or self.loading or self.mode in (OperationMode.RADIO_TX_TEST, OperationMode.HOSTLESS_CS):
            return
        self.cs_view.flush_edits()
        self.results.set_measurement_mode(self.cs_view.scenario.configuration.mode)

    def update_requested(self):
        """Compare controller reports with the configuration the client holds, else the one being edited."""
        config = self.session.client_config or self.session.host_config
        if self.mode == OperationMode.HOSTLESS_CS:
            config = None
        initiator = bool(config) and config.mode == OperationMode.CS_INITIATOR
        self.controller_view.set_requested(
            config.config if config and config.mode != OperationMode.RADIO_TX_TEST else None,
            config.peer_data if initiator else 0,
            config.t_pm if initiator else T_PM_DEFAULT_US)

    def config_received(self, config):
        self.loading = True
        try:
            self.select_role(config.mode)
            self.cs_view.host_settings["log"] = normalize_log(config.log)
            self.general_view.set_log(self.cs_view.host_settings["log"])
            self.radio_view.set_log(self.cs_view.host_settings["log"])
            if config.mode == OperationMode.RADIO_TX_TEST:
                self.radio_view.apply_config(config.config)
            else:
                self.cs_view.host_settings["device_name"] = config.device_name.text() if config.device_name else ""
                self.cs_view.set_device_name(self.cs_view.host_settings["device_name"])
                self.cs_view.host_settings["peripheral_patterns"] = config.patterns.names() if config.patterns else []
                self.cs_view.host_settings["peer_data"] = config.peer_data
                self.cs_view.host_settings["t_pm"] = config.t_pm
                self.cs_view.apply_config(config.config)
        finally:
            self.loading = False
        self.edited()
        if not self.session.in_sync:
            self.error("The view cannot represent the client configuration exactly; Start is refused until it is synced")

    def apply(self, *, disconnect_confirmed=False):
        try:
            self.session.set_host_config(self.collect_config())
        except (ValueError, TypeError) as error:
            self.show_message("Configuration is not valid", 5000)
            W.QMessageBox.warning(self, "Cannot apply configuration", "Resolve these problems first:\n" + str(error))
            self.update_controls()
            return
        if self.session.running:
            W.QMessageBox.warning(self, "Cannot apply configuration",
                                  "The configuration cannot be changed while running. Stop the run first.")
            self.update_controls()
            return
        active = self.session.link_state in LINK_ACTIVE
        if active and not disconnect_confirmed:
            message = {
                ClientState.SCANNING: "Applying stops the active scan. Continue?",
                ClientState.ADVERTISING: "Applying stops Bluetooth advertising. Continue?",
                ClientState.LINK_CONNECTING: "Applying cancels the Bluetooth connection attempt. Continue?",
            }.get(self.session.link_state, "Applying disconnects the Bluetooth link. Continue?")
            if W.QMessageBox.question(self, "Apply configuration?", message) != W.QMessageBox.StandardButton.Yes:
                return
        try:
            self.session.apply(allow_interrupt=active)
        except (ValueError, OSError, TypeError) as error:
            self.config_sync_failed(error)
        self.update_controls()

    def start(self):
        # Fold pending edits in first, so START carries the CRC of exactly what the views show.
        self.edited()
        if not self.session.in_sync:
            self.show_message("Synchronise the configuration before starting.", 10000, level=WARNING)
            self.show_alert("Synchronise configuration", "Synchronise the configuration before starting.",
                            warning=True)
            return
        requires_peer = self.mode in (OperationMode.CS_INITIATOR, OperationMode.CS_REFLECTOR)
        if requires_peer and self.session.link_state not in PEER_LINKED_STATES:
            if self.cs_view.host_settings["gap_role"] != 0:
                if self.session.link_state != ClientState.ADVERTISING:
                    self.session.advertise()
                self.show_message("Advertising is active. Connect a device before starting.",
                                  10000, level=INFO)
                self.show_alert("Connect a device", "Advertising is active. Connect a device before starting.")
                return
            visible = self.session.visible_peers(self.peers_view.show_all.isChecked())
            if self.session.link_state != ClientState.SCANNING:
                self.scan_peers()
                message = ("A matching device is available. Connect it before starting." if visible else
                           "No peer is connected. Scanning now; connect a matching device before starting.")
                self.show_message(message, 10000, level=INFO)
            elif visible:
                message = "A matching device is available. Connect it before starting."
                self.show_message(message, 10000, level=INFO)
            else:
                message = ("Scanning for a device matching the configured name prefixes. "
                           "Connect it before starting.")
                self.show_message(message, 10000, level=INFO)
            self.show_alert("Connect a peer before starting", message)
            return
        self.session.start()

    def disconnect_link(self, *, reconnect=False):
        """Drop the peer link, optionally opening a fresh host session over the same port."""
        if reconnect:
            question = ("Disconnecting the Bluetooth link stops the run. The client will reconnect "
                        "so you can scan for another peer. Continue?" if self.session.running else
                        "Disconnecting the Bluetooth link will reconnect the client so you can scan "
                        "for another peer. Continue?")
        else:
            question = ("Disconnecting the Bluetooth link stops the run and ends the session. Continue?"
                        if self.session.running else
                        "Disconnecting the Bluetooth link also ends the session. Continue?")
        if W.QMessageBox.question(self, "Disconnect link?",
                                  question) != W.QMessageBox.StandardButton.Yes:
            return
        self.show_message("Disconnecting Bluetooth link…", 5000)
        self._reconnect_after_peer_disconnect = reconnect
        self.session.disconnect_link()

    def session_state_changed(self, state):
        """Reconnect the host session after a user requested peer disconnect."""
        if state == "DISCONNECTED" and self._reconnect_after_peer_disconnect:
            self._reconnect_after_peer_disconnect = False
            if self.session.transport is not None:
                self.invoke(self.session.reconnect)
                return
        self.update_controls()

    def command_result(self, packet):
        if (packet.request_type == PacketType.SET_OPERATION_MODE and
                packet.status == ProtocolStatus.UNSUPPORTED):
            self.operation_mode_unsupported()
        if packet.request_type == PacketType.LINK_DISCONNECT and packet.status == ProtocolStatus.OK:
            self.show_message("Bluetooth link disconnected", 5000)

    def operation_mode_unsupported(self):
        """Select a mode advertised by the client after it rejects our request."""
        info = self.session.info
        config = self.session.host_config
        requested = config.mode if config is not None else self.mode
        supported = int(info.supported_modes) if info is not None else 0
        fallback = next((mode for mode in (OperationMode.CS_INITIATOR,)
                         if supported & (1 << mode)), None)
        requested_name = self._operation_mode_name(requested)
        if fallback is None:
            self.show_alert(
                "Unsupported operation mode",
                f"The client does not support {requested_name}, and it did not report a supported mode this host can select.",
                warning=True)
            return

        self.select_role(fallback)
        fallback_name = self._operation_mode_name(fallback)
        self.show_alert(
            "Unsupported operation mode",
            f"The client does not support {requested_name}. Switching to {fallback_name}. "
            "Apply the configuration to send the supported mode to the client.",
            warning=True)

    @staticmethod
    def _operation_mode_name(mode):
        try:
            mode = OperationMode(mode)
        except (TypeError, ValueError):
            return str(mode)
        return {
            OperationMode.CS_INITIATOR: "CS initiator",
            OperationMode.CS_REFLECTOR: "CS reflector",
            OperationMode.RADIO_TX_TEST: "Radio Test",
            OperationMode.HOSTLESS_CS: "CS Hostless",
        }[mode]

    def start_failed(self, text):
        self.show_message("Start refused: configuration is not synced", 10000, level=WARNING)
        self.update_controls()
        W.QMessageBox.warning(self, "Cannot start", str(text))

    def recording_discarded(self, path):
        """A run that never started keeps neither its recording nor its saved configuration."""
        self.recording_view.config_path_for(path).unlink(missing_ok=True)
        if self._active_recording_path == path:
            self._active_recording_path = None
        self._session_recorded = False
        self.results.session_recording_path = None

    def history_limit_changed(self, max_bytes):
        """Disk bound for the next session history (§7.1)."""
        self.session.history_kwargs["max_bytes"] = int(max_bytes)

    def history_started(self, history):
        """A confirmed START or hostless Connect opened a new session history."""
        # An error stays in the status bar until something replaces it; the previous session's must not
        # outlive that session. A timed message (the saved run configuration) expires on its own.
        if not self.message_timer.isActive():
            self.message_label.clear()
        if self.session.info is not None:
            self.port_status.setText(self.client_status_text(self.session.info))
        self._session_started_at = datetime.now()
        self._session_saved = False
        self._save_offered = False
        self.results.begin_session(history)
        self.update_controls()

    def history_error(self, text):
        """Detach a live history after its writer has been disabled."""
        self.show_message(f"Session history disabled: {text}", 10000, level=WARNING)
        if self.results.live_history and self.session.history is None:
            self.results.set_session_history(None)

    def default_session_path(self) -> str:
        # Qt widgets and QFileDialog require str, while the recording view builds
        # paths with pathlib.Path.
        return str(self.recording_view.session_path_for(self.mode, self._session_started_at))

    def logging_changed(self, checked):
        self.session.logging_factory = self.create_recording if checked else None

    def save_session(self, path, description=None):
        history = self.session.history
        if history is None or history.empty:
            self.show_message("No session history to save", 5000)
            return False
        path = Path(path)
        if path.exists():
            W.QMessageBox.warning(self, "Cannot save session", f"File already exists: {path}")
            return False
        config = None if self.mode == OperationMode.HOSTLESS_CS else (self.session.client_config or self.session.host_config)
        radio = config is not None and config.mode == OperationMode.RADIO_TX_TEST
        scenario = "" if radio else document(self.cs_view.scenario, self.cs_view.host_settings)
        description = (self.results.description_text or self.recording_view.description.text()
                       if description is None else str(description))
        self.results.set_description(description)
        kwargs = dict(config=config, scenario_json=scenario,
                      metadata=dict(protocol_version=PROTOCOL_VERSION,
                                    firmware_version=getattr(self.session.info, "firmware_version", 0),
                                    operation_mode=int(config.mode) if config is not None else int(self.mode),
                                    port=getattr(self, "port_name", "simulator"),
                                    baud=getattr(self, "baud", 921600)),
                      log_config=self.general_view.log_config(),
                      write_config=self.mode != OperationMode.HOSTLESS_CS,
                      description=description)
        self._saving_config_path = None
        if scenario:
            # As for recordings: the session's configuration beside the file, reloadable with Open….
            self._saving_config_path = self.recording_view.config_path_for(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._saving_config_path.write_text(scenario)
        job = _SaveSessionJob(history, path, kwargs)
        self._save_jobs = getattr(self, "_save_jobs", set())
        self._save_jobs.add(job)
        job.signals.finished.connect(self.session_saved)
        job.signals.failed.connect(self.session_save_failed)
        QtCore.QThreadPool.globalInstance().start(job)
        self.show_message(f"Saving session to {path}…", 0)
        return True

    def session_saved(self, path):
        self.show_message(f"Saved session to {path}", 5000)
        self.recording_view.set_last(path)
        self.results.capture_path = Path(path)
        self._session_saved = True
        self.results.set_description(self.results.description_text)
        if self._close_after_save:
            self._close_after_save = False
            self.close()
            return
        # The saved file is the session: browse it in replay instead of the
        # temporary history (§7.9).  A run that is still going keeps its live
        # views; the offer after it stops opens the file then.
        if not self.session.running and not self._closing:
            self.results.open_capture_path(Path(path))

    def session_save_failed(self, text):
        self._close_after_save = False
        # save_hdf5 removed its partial file; the configuration written beside it goes too.
        if getattr(self, "_saving_config_path", None) is not None:
            self._saving_config_path.unlink(missing_ok=True)
        self.show_message(f"Session save failed: {text}", 10000, level=ERROR)

    def create_recording(self, session, partial):
        from .recorder import RunRecorder
        self.run_number += 1
        # A hostless stream is not produced by the configuration the editor holds
        # for the other modes, so the recording keeps none (as save_session does).
        hostless = self.mode == OperationMode.HOSTLESS_CS
        config = None if hostless else (session.client_config if partial and session.client_config
                                        else session.host_config)
        mode = config.mode if config is not None else self.mode
        path = self.recording_view.path_for(mode)
        radio = mode == OperationMode.RADIO_TX_TEST
        scenario = "" if radio or hostless else document(self.cs_view.scenario, self.cs_view.host_settings)
        # The run's configuration is also saved beside the recording, reloadable with Open… / Open preset….
        config_path = self.recording_view.config_path_for(path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config is not None:
            config_path.write_text(preset_json(config.config, self.general_view.log_config()) if radio else scenario)
        try:
            recorder = RunRecorder(path, config=config, scenario_json=scenario, context=session.context.values(), partial=partial,
                                   log_config=self.general_view.log_config(),
                                   description=self.recording_view.description.text(),
                                   metadata=dict(protocol_version=PROTOCOL_VERSION, firmware_version=getattr(session.info, "firmware_version", 0),
                                                 operation_mode=int(mode),
                                                 port=getattr(self, "port_name", "simulator"), baud=getattr(self, "baud", 921600),
                                                 run_number=self.run_number, link_number=self.link_number))
        except Exception:
            config_path.unlink(missing_ok=True)
            raise
        self.recording_view.set_last(path)
        self._active_recording_path = path
        self._session_recorded = True
        # A recording covers its whole run, which is the session (§7.1): Save session offers it.
        self.results.session_recording_path = path
        if config is not None:
            self.show_message(f"Saved configuration to {config_path}", 5000)
        return recorder

    def radio_run_started(self, reason):
        if self.mode == OperationMode.RADIO_TX_TEST and reason == "started":
            self.radio_results.clear()

    def run_finished(self, reason):
        """Refresh controls, offer non-modal metadata editing for a closed recording, and the save."""
        self.update_controls()
        path, self._active_recording_path = self._active_recording_path, None
        if path is not None and Path(path).exists():
            if self._description_dialog is not None and self._description_dialog.isVisible():
                self._description_dialog.close()
            # Notes written while the run was recording (Describe session) win over the
            # Recording field, as they do when a session is saved.
            initial = self.results.description_text or self.recording_view.description.text()
            self._description_dialog = _RunDescriptionDialog(path, initial, self)
            self._description_dialog.saved.connect(self.results.set_description)
            self._description_dialog.show()
            self._description_dialog.raise_()
            self._description_dialog.activateWindow()
        self.offer_session_save()

    def offer_session_save(self):
        """Offer the save that turns a stopped session into a browsable file (§7.9).

        The temporary history is not the session: the whole timeline, its
        search and the procedure selector are browsed in replay over the saved
        file, which this app opens as soon as the save has finished.  A session
        already in a recording or a save needs no offer, and a hidden window
        (the headless test harness) cannot answer one.
        """
        if self._closing or not self.isVisible() or not self._unsaved_session_prompt():
            return
        if self._save_offered:
            # A teardown ends the run twice: on the client's interrupt report and
            # again on CLOSE_SESSION.  One offer per session (§7.8).
            return
        self._save_offered = True
        answer = W.QMessageBox.question(
            self, "Save session",
            "The run has stopped. Save this session to browse and analyse its history?",
            W.QMessageBox.StandardButton.Save | W.QMessageBox.StandardButton.Cancel)
        if answer == W.QMessageBox.StandardButton.Save:
            self.session_view.save_session()

    def _unsaved_session_prompt(self):
        history = self.session.history
        return (history is not None and not history.empty and
                not self._session_saved and not self._session_recorded)

    def scan_peers(self):
        self._scan_guidance_announced = False
        self._peer_controls_visible = True
        self.peers_view.peers.setVisible(True)
        self.peers_view.show_all.setVisible(True)
        self.session.scan()
        self.refresh_peers(replace=True)
        self.show_message("Scanning for devices matching the configured name prefixes.", 10000, level=INFO)

    def refresh_peers(self, replace=False):
        self.peers_view.refresh(self.session.visible_peers(self.peers_view.show_all.isChecked()), replace)

    def connect_selected_peer(self):
        if (self.session.host_config is None or self.session.host_config.config is None or
                not self.session.in_sync):
            message = "Synchronise the configuration before connecting to a peer."
            self.show_message(message,
                              10000, level=WARNING)
            self.show_alert("Synchronise configuration", message, warning=True)
            return
        visible = self.session.visible_peers(self.peers_view.show_all.isChecked())
        if not visible and self.session.link_state != ClientState.SCANNING:
            self.scan_peers()
            message = "Starting a scan. Connect a matching device after it appears."
            self.show_message(message,
                              10000, level=INFO)
            self.show_alert("Scan for a peer", message)
            return
        if not visible:
            message = "No device matches the configured name prefixes. Scanning for a match."
            self.show_message(message,
                              10000, level=INFO)
            self.show_alert("No matching device", message)
            return
        key = self.peers_view.peers.currentData()
        if key is None:
            message = "A matching device is available. Select it, then press Connect peer."
            self.show_message(message,
                              7000, level=INFO)
            self.show_alert("Select a peer", message)
            return
        peer = self.session.peers.get(key)
        if peer is None or not peer.flags & 1:
            message = "The selected device is not connectable. Select a connectable device."
            self.show_message(message,
                              7000, level=WARNING)
            self.show_alert("Device cannot connect", message, warning=True)
            return
        self.session.connect_peer(key)
        self._peer_connect_attempt = key

    def toggle_peer_connection(self):
        if self.session.link_state in PEER_LINKED_STATES:
            self.disconnect_link(reconnect=True)
        else:
            self.connect_selected_peer()

    def open_peer_console(self, port, baud):
        if self._peer_console_transport is not None:
            return
        reader = PeerConsoleReader(lambda level, text, timestamp:
                                   self._peer_console_bridge.line.emit(level, text, timestamp))
        transport = SerialTransport(port, baud, self)
        transport.on_data = reader.feed
        transport.on_error = self._peer_console_bridge.error.emit
        try:
            transport.open()
        except (OSError, ValueError) as error:
            transport.close()
            self.peer_console_view.set_opened(False)
            self.show_message(f"Peer console failed: {error}", 10000, level=WARNING)
            return
        self._peer_console_reader = reader
        self._peer_console_transport = transport
        self.peer_console_view.set_opened(True)
        self.show_message(f"Peer console opened on {port}", 5000)

    def peer_console_line(self, level, text, received_at=None):
        if text:
            self.record_host(text, level=level, source="peer", timestamp=received_at)

    def peer_console_error(self, text):
        self.show_message(f"Peer console: {text}", 10000, level=WARNING)
        self.close_peer_console()

    def close_peer_console(self):
        if self._peer_console_reader is not None:
            self._peer_console_reader.flush()
        transport, self._peer_console_transport = self._peer_console_transport, None
        self._peer_console_reader = None
        if transport is not None:
            transport.close()
        self.peer_console_view.set_opened(False)

    def packet_sent(self, packet):
        self.results.add_packet(packet, direction="sent")
        if packet.PACKET_TYPE == PacketType.SCAN_START:
            # Clear again at the actual restart, after STOP is acknowledged,
            # including any old scan reports received while STOP was pending.
            self.refresh_peers(replace=True)

    def packet_received(self, packet):
        # Do not put unsolicited hosted frames into the Results/history view
        # while CONNECT is still awaiting its response.  Hostless CS has no
        # handshake and is intentionally allowed to stream immediately.
        if (not self.session.hostless and not self.session.connect_confirmed and
                not (isinstance(packet, ConnectResponsePacket) and
                     packet.status == ProtocolStatus.OK and packet.protocol_version == PROTOCOL_VERSION)):
            return
        if type(packet).__name__ == "ScanResultPacket":
            self.refresh_peers()
            visible = self.session.visible_peers(self.peers_view.show_all.isChecked())
            if (visible and not self._scan_guidance_announced and
                    self.session.link_state == ClientState.SCANNING):
                self._scan_guidance_announced = True
                message = "Matching devices found. Scanning continues; select a peer to connect or press Scan to restart."
                self.show_message(message,
                                  10000, level=INFO)
        if isinstance(packet, ClientStatePacket) and self._peer_connect_attempt is not None:
            if packet.state in PEER_LINKED_STATES:
                self._peer_connect_attempt = None
            elif packet.state in (ClientState.LINK_LOST, ClientState.LINK_DISCONNECTED, ClientState.ERROR):
                failed_key, self._peer_connect_attempt = self._peer_connect_attempt, None
                self.session.peers.pop(failed_key, None)
                self.refresh_peers(replace=True)
        if (isinstance(packet, CommandResponsePacket) and self._peer_connect_attempt is not None and
                packet.request_type == PacketType.PEER_CONNECT and packet.status != ProtocolStatus.OK):
            failed_key, self._peer_connect_attempt = self._peer_connect_attempt, None
            self.session.peers.pop(failed_key, None)
            self.refresh_peers(replace=True)
        if self.mode != OperationMode.HOSTLESS_CS:
            self.radio_results.add_packet(packet, getattr(self.session, "last_received_at", None))
        if self.mode not in (OperationMode.RADIO_TX_TEST, OperationMode.HOSTLESS_CS):
            self.cs_packet_received(packet)
        elif self.mode == OperationMode.HOSTLESS_CS:
            self.cs_packet_received(packet)
        if type(packet).__name__ == "CsProceduresCompletePacket":
            self.port_status.setText(f"Run complete: {packet.procedures_completed} procedures completed "
                                     "(max procedure count reached)")

    def cs_packet_received(self, packet):
        self.results.add_packet(packet, getattr(self.session, "last_received_at", None))
        if isinstance(packet, (CsCapabilitiesPacket, CsConfigurationPacket, CsProcedureEnableCompletePacket,
                               ConnectionParametersPacket)):
            self.update_requested()
            self.controller_view.add_packet(packet)
        if isinstance(packet, CsFaeTablePacket):
            self.controller_view.set_fae_table(packet, link_number=self.link_number,
                                               timestamp=datetime.now().isoformat())
        elif isinstance(packet, CsProcedureEnableCompletePacket) and not packet.state:
            # A disable report only says procedures stopped; the planner keeps the enabled schedule.
            pass
        elif isinstance(packet, (CsConfigurationPacket, CsProcedureEnableCompletePacket,
                                 ConnectionParametersPacket)):
            if isinstance(packet, CsConfigurationPacket):
                # Hostless sessions have no START confirmation to select the
                # Results mode; use the controller-negotiated mode as soon as
                # the configuration report arrives. This also keeps hosted
                # Results aligned if negotiation changes the requested mode.
                self.results.set_measurement_mode(packet.mode)
            # Negotiated timings and ACL parameters update the illustration, not the requested host config.
            self.loading = True
            try:
                self.cs_view.apply_config(packet)
            finally:
                self.loading = False
        elif type(packet).__name__ == "ClientStatePacket":
            if packet.state == ClientState.LINK_CONNECTED:
                self.link_number += 1
            elif packet.state in (ClientState.LINK_LOST, ClientState.LINK_DISCONNECTED):
                self.controller_view.clear()

    def update_controls(self):
        core = self.session
        hostless = self.mode == OperationMode.HOSTLESS_CS
        busy = bool(core.pending or core.queue)
        connected = core.transport is not None and core.state not in ("CONNECTING", "FAILED", "DISCONNECTED")
        connecting = core.transport is not None and core.state == "CONNECTING"
        running = core.running
        role = getattr(core.host_config.config, "gap_role", None) if core.host_config else None
        # A disconnected session has no active firmware capability mask to
        # enforce, even if the serial port stays open for the next handshake.
        # Restore all host-selectable modes so the user can choose a
        # configuration before connecting. client_info() reapplies the
        # connected client's actual supported modes.
        if core.transport is None or core.state in ("DISCONNECTED", "FAILED"):
            self.general_view.set_supported_modes(int(
                OperationModeMask.CS_INITIATOR | OperationModeMask.CS_REFLECTOR |
                OperationModeMask.RADIO_TX_TEST))
        self.run_bar.set_connection_state(connected, connecting)
        self.config_stack.setEnabled(not busy)
        # The configuration is locked while running; the CS views stay available for inspection.
        self.cs_view.set_locked(running or hostless)
        self.cs_view.set_readonly(hostless)
        self.radio_view.setEnabled(not running and not hostless)
        self.recording_view.setEnabled(True)
        self.port_view.setEnabled(core.transport is None)
        # Keep the mode selector usable in hostless mode so the user can
        # switch back to a hosted configuration.  Hostless-specific fields
        # are hidden/read-only by GeneralView.set_mode().
        self.general_view.setEnabled(not busy and not running)
        self.general_toolbar.setEnabled(not busy and not running)
        discovery_ready = connected and not busy and not running and core.in_sync
        inactive = core.link_state not in (ClientState.LINK_CONNECTING, ClientState.LINK_CONNECTED,
                                           ClientState.RAS_READY, ClientState.ADVERTISING, ClientState.STOPPED)
        peer_connected = core.link_state in PEER_LINKED_STATES
        for label, button in self.run_bar.buttons.items():
            enabled = connected and not busy and not hostless
            if label == "Help":
                enabled = True
            elif label == "Connect":
                # While connecting the action cancels the handshake, so it stays available.
                # With the port open and no session it opens a new one over that port (§7.8).
                enabled = (core.transport is None or connecting or core.state == "DISCONNECTED"
                           or (connected and not busy))
            elif label == "Apply config":
                enabled &= not running
            elif label == "Synchronise":
                # A started session owns the applied configuration until it stops.
                # The planner Reset action is covered by CsView.set_locked below.
                enabled &= not running
            elif label == "Start session":
                requires_peer = self.mode in (OperationMode.CS_INITIATOR, OperationMode.CS_REFLECTOR)
                scanned = (bool(core.visible_peers(self.peers_view.show_all.isChecked()))
                           if requires_peer and role == 0 else True)
                linked = core.link_state in PEER_LINKED_STATES
                enabled &= not running and core.in_sync and (not requires_peer or linked)
                if not core.in_sync:
                    button.setToolTip("Synchronise the configuration before starting")
                elif requires_peer and not linked and role == 0 and not scanned:
                    button.setToolTip("Scan for a matching peer, then connect to it before starting")
                elif requires_peer and not linked:
                    button.setToolTip("Connect to a scanned peer before starting")
                else:
                    button.setToolTip("Start session")
            elif label == "Stop session":
                enabled &= core.state == "RUNNING" or core.link_state in (ClientState.SCANNING, ClientState.ADVERTISING, ClientState.LINK_CONNECTING)
            elif label == "Scan":
                enabled = discovery_ready and inactive and role == 0
                button.setToolTip("Restart scanning and clear the peer list" if core.link_state == ClientState.SCANNING
                                  else "Scan for nearby peers matching the configured name prefixes")
            elif label == "Connect peer":
                self.run_bar.set_peer_connection_state(peer_connected)
                if peer_connected:
                    enabled = connected and not busy and role == 0
                else:
                    has_peers = bool(core.visible_peers(self.peers_view.show_all.isChecked()))
                    enabled = (connected and not busy and not running and role == 0 and
                               (core.link_state == ClientState.SCANNING or inactive or has_peers))
            elif label == "Record from now":
                enabled &= core.state == "RUNNING" and core.recorder is None and core.logging_factory is not None
            elif label == "Describe session":
                # Notes belong to the session or the open capture, not to the link: an
                # opened recording and a finished session stay describable offline.
                enabled = (bool(self.results.description_text) or self.results.capture_path is not None
                           or self.results.session_history is not None)
            elif label in ("Open capture…", "Clear"):
                # Offline view actions: no link is needed, but a live run owns the views.
                enabled = not running
            button.setEnabled(enabled)
        self.peers_view.setVisible(self.mode not in (OperationMode.RADIO_TX_TEST, OperationMode.HOSTLESS_CS))
        # Scanning and connecting are central-only; advertising is peripheral-only.
        central = self.cs_view.host_settings["gap_role"] == 0
        for widget in (self.peers_view.scan, self.peers_view.peers, self.peers_view.show_all,
                       self.peers_view.connect):
            widget.setVisible(central)
        self.peers_view.peers.setVisible(central and self._peer_controls_visible)
        self.peers_view.show_all.setVisible(central and self._peer_controls_visible)
        self.peers_view.advertise.setVisible(not central)
        self.peers_view.advertise.setEnabled(discovery_ready and inactive and role == 1)
        self.run_bar.buttons["Connect peer"].setToolTip(
            "Disconnect from the connected Bluetooth peer" if peer_connected else
            ("Synchronise the configuration first" if not core.in_sync else
             "Connect to the selected peer; if none is listed, this starts a scan"))
        self.recording_view.update_controls(core.recorder is not None)
        self.recording_view.save_session.setEnabled(self.session.history is not None and not self.session.history.empty)
        # Results remain usable during a run for live analysis, but changing
        # the followed procedure does not.
        self.results.set_running(running)
        # Online means that a connected UART device is actively receiving the
        # run. Hostless CS streams reports while its link state remains IDLE,
        # so it is online even though the normal run-state flag is false. A
        # connected, stopped hosted device remains a replay/browsing view.
        self.results.set_online(connected and (running or hostless))
        self.radio_results.set_running(running)
        self.state_label.setText(f"Session {core.state} · {'in sync' if core.in_sync else 'modified / mismatch'} · "
                                 f"link {link_state_name(core.link_state)} ·{core.frames} frames / {core.packet_errors} errors / {core.ras_lost} RAS lost")
        self.update_configuration_summary()

    def tick(self):
        if self.simulator:
            try:
                self.simulator.tick()
            except (ValueError, OSError) as error:
                self.session.fail(str(error))
        if self.session.state == "CONNECTING" and self.session.pending:
            self.port_status.setText(f"Connecting… {max(0, self.session.pending[1] - self.session.clock()):.1f} s")
        self.update_controls()

    def current_help_topic(self):
        """Choose help that matches the main page and operation mode currently in view."""
        current = self.tabs.currentWidget()
        if current is self.results_stack:
            return "results"
        if current is self.session_view:
            return "session"
        if current is self.config_stack:
            return "hostless" if self.mode == OperationMode.HOSTLESS_CS else "configuration"
        return "about"

    def show_help(self, topic=None):
        """Open or retarget the non-modal help window beside the app."""
        topic = topic or self.current_help_topic()
        if self._help_dialog is None:
            self._help_dialog = HelpDialog(self, topic=topic)
        else:
            self._help_dialog.show_topic(topic)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    def show_about(self):
        W.QMessageBox.about(
            self,
            "About BLE Channel Sounding Host",
            f"<b>BLE Channel Sounding Host {__version__}</b><p>Desktop application for Bluetooth Channel Sounding: plan the "
            "CS configuration, control a client board, view live results and record sessions.</p>"
            "<p>Help → Help topics… explains what the application does and how to use it.</p>",
        )

    def closeEvent(self, event):
        if self._description_dialog is not None and self._description_dialog.isVisible():
            # Closing the application while the non-modal editor is open keeps typed notes.
            self._description_dialog.save_text(silent=True)
        # Hidden windows are used by the headless test harness and cannot present
        # a modal choice; only a user-visible application close needs the prompt.
        if self.isVisible() and self._unsaved_session_prompt():
            box = W.QMessageBox(self)
            box.setIcon(W.QMessageBox.Icon.Question)
            box.setWindowTitle("Unsaved session")
            box.setText("This session has not been recorded or saved.")
            save = box.addButton("Save session", W.QMessageBox.ButtonRole.AcceptRole)
            discard = box.addButton("Discard", W.QMessageBox.ButtonRole.DestructiveRole)
            cancel = box.addButton("Cancel", W.QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked == cancel:
                event.ignore()
                return
            if clicked == save:
                path, _ = W.QFileDialog.getSaveFileName(self, "Save session", self.default_session_path(),
                                                        "HDF5 recordings (*.h5 *.hdf5)")
                if not path:
                    event.ignore()
                    return
                self._close_after_save = self.save_session(path, self.results.description_text)
                # The export is intentionally backgrounded; close again after it completes.
                event.ignore()
                return
            if clicked == discard and self.session.history is not None:
                self.session.history.close(discard=True)
                self.session.history = None
        # Only once the close is certain: Cancel above keeps the session and its peer console.
        self._closing = True
        self.close_peer_console()
        if self.session.transport:
            if self.session.pending:
                self.session.fail("Window closed")
            else:
                self.session.close()
                if self.session.transport:
                    self.session.fail("Window closed before CLOSE_SESSION confirmation")
        logging.getLogger("ble_channel_sounding").removeHandler(self._log_handler)
        event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Desktop host for Bluetooth Channel Sounding clients.",
        epilog=(
            "Examples:\n"
            "  ble-channel-sounding                     Start and choose a serial client or Simulator.\n"
            "  ble-channel-sounding --simulate          Start with the in-memory simulator selected.\n"
            "  ble-channel-sounding --simulate run.h5   Load an HDF5 capture into the simulator.\n\n"
            "The simulator does not require hardware; its measurements are synthetic. Hardware use requires a compatible client.\n"
            "Guide: https://github.com/Sens-Wear/ble-cs/blob/main/python/ble_channel_sounding/GETTING_STARTED.md"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--simulate", nargs="?", const="", default=None, metavar="CAPTURE",
        help="preselect the in-memory simulator; optionally replay an HDF5 capture",
    )
    args = parser.parse_args(argv)
    pg.setConfigOptions(antialias=True, foreground="#40556d")
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon(str(APP_ICON)))
    tooltips.install(app)
    window = MainWindow(simulate=args.simulate is not None, capture=args.simulate or None)
    window.show()
    return app.exec()
