"""Controller reports: capabilities, ACL parameters, completed configuration and procedure enable complete."""
from PyQt6 import QtCore, QtGui, QtWidgets as W
from ..controller import (DIFFERS, OK, OUTSIDE, RUN_FAILS, ControllerReports, capability_rows, check_compatibility,
                          compare_configuration, compare_connection, compare_procedure, source_label)
from ..planner.model import unused_fields
from ..protocol.packets import (CapabilitiesSource, ClientState, ClientStatePacket, CsInitiatorConfigPacket,
                                CsFaeTablePacket, CsReflectorConfigPacket, PeerDataPacket, T_PM_DEFAULT_US, TpmPacket)
from ..fae import FAE_CHANNELS, FaeTable
from .cells import set_cell, set_list

# Translucent tints read on light and dark palettes alike.
TINTS = {OK: QtGui.QColor(27, 175, 122, 50), DIFFERS: QtGui.QColor(230, 160, 20, 70),
         OUTSIDE: QtGui.QColor(220, 60, 60, 70)}
STATUS_TEXT = {OK: "✓", DIFFERS: "differs", OUTSIDE: "out of range"}
SOURCES = (CapabilitiesSource.LOCAL, CapabilitiesSource.REMOTE)
# Configuration and procedure rows of planner fields a mode combination can leave unused (unused_fields).
MODE_ROWS = {"configuration.min_main_mode_steps": "Min main-mode steps",
             "configuration.max_main_mode_steps": "Max main-mode steps", "configuration.rtt_type": "RTT type",
             "configuration.t_ip2_time_us": "T_IP2", "configuration.t_pm_time_us": "T_PM",
             "configuration.cs_enhancements_1": "IPT (enhancements 1)",
             "procedure.tone_antenna_config_selection": "Antenna configuration"}


def _table(headers):
    table = W.QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


class CollapsibleGroup(W.QGroupBox):
    """A titled Controller section whose header hides or reveals its contents."""

    def __init__(self, title, widget, parent=None):
        super().__init__(parent)
        self._title = title
        self.header = W.QToolButton()
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(True)
        self.header.setAutoRaise(True)
        self.header.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setArrowType(QtCore.Qt.ArrowType.DownArrow)
        self.content = widget
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.addWidget(self.header)
        layout.addWidget(self.content)
        self.header.toggled.connect(self.set_expanded)
        self._expanded_minimum = self.minimumHeight()
        self._expanded_maximum = self.maximumHeight()

    def title(self):
        return self._title

    def setTitle(self, title):
        self._title = str(title)
        if hasattr(self, "header"):
            self.header.setText(self._title)

    def set_expanded(self, expanded):
        splitter = self.parentWidget()
        old_sizes = splitter.sizes() if isinstance(splitter, W.QSplitter) else None
        index = splitter.indexOf(self) if isinstance(splitter, W.QSplitter) else -1
        self.content.setVisible(expanded)
        self.header.setArrowType(QtCore.Qt.ArrowType.DownArrow if expanded else QtCore.Qt.ArrowType.RightArrow)
        if expanded:
            self.setMinimumHeight(self._expanded_minimum)
            self.setMaximumHeight(self._expanded_maximum)
        else:
            # Hidden contents do not reliably shrink a QSplitter child. Limit
            # the group to the header and its layout margins.
            margins = self.layout().contentsMargins()
            collapsed_height = (self.header.sizeHint().height() + margins.top() + margins.bottom() +
                                self.layout().spacing())
            self.setMinimumHeight(collapsed_height)
            self.setMaximumHeight(collapsed_height)
        if old_sizes and 0 <= index < len(old_sizes):
            # QSplitter can retain its previous pane allocations after a child
            # changes maximum height, so explicitly give the released pixels
            # to the other visible sections (and take them back on expansion).
            sizes = list(old_sizes)
            target = self.maximumHeight() if not expanded else max(old_sizes[index], self.sizeHint().height())
            delta = target - sizes[index]
            sizes[index] = target
            others = [i for i in range(len(sizes)) if i != index]
            weight = sum(old_sizes[i] for i in others)
            if delta > 0:
                available = max(0, sum(old_sizes[i] for i in others) -
                                sum(splitter.widget(i).minimumSizeHint().height() for i in others))
                delta = min(delta, available)
                sizes[index] = old_sizes[index] + delta
                for i in others:
                    sizes[i] = max(1, old_sizes[i] - delta * old_sizes[i] // max(weight, 1))
            elif delta < 0:
                freed = -delta
                sizes[index] = target
                for i in others:
                    sizes[i] = old_sizes[i] + freed * old_sizes[i] // max(weight, 1)
            splitter.setSizes(sizes)


def _group(title, widget):
    return CollapsibleGroup(title, widget)


class ControllerView(W.QWidget):
    """Shows the latest controller reports next to the requested host configuration."""

    status_message = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.reports = ControllerReports()
        self.requested = None
        self.requested_peer_data = 0
        self.requested_t_pm = T_PM_DEFAULT_US
        # CS mode combination whose rows are shown; None uses the negotiated one.
        self.mode = None
        self.status_text = ""
        self.fae_table = None
        self.fae_link_number = 0
        self.fae_report_time = None
        layout = W.QVBoxLayout(self)
        splitter = W.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(splitter, 1)
        left = W.QSplitter(QtCore.Qt.Orientation.Vertical)
        splitter.addWidget(left)
        self.capabilities = _table(("Capability", "Local", "Remote"))
        for column in (1, 2):
            self.capabilities.horizontalHeader().setSectionResizeMode(column, W.QHeaderView.ResizeMode.Stretch)
        self.capabilities.setWordWrap(False)
        left.addWidget(_group("Capabilities", self.capabilities))
        self.fae = _table(("CS channel", "FAE (raw)", "FAE (ppm)"))
        self.fae_box = _group("Remote FAE table · not received", self.fae)
        left.addWidget(self.fae_box)
        left.setSizes([430, 280])
        right = W.QSplitter(QtCore.Qt.Orientation.Vertical)
        splitter.addWidget(right)
        # The ACL link is established before the CS configuration, and is shown first.
        self.connection = _table(("Field", "Requested", "Negotiated", "Status"))
        self.connection_box = _group("Connection parameters", self.connection)
        right.addWidget(self.connection_box)
        self.configuration = _table(("Field", "Requested", "Negotiated", "Status"))
        self.configuration_box = _group("Configuration complete", self.configuration)
        right.addWidget(self.configuration_box)
        self.procedure = _table(("Field", "Requested", "Negotiated", "Status"))
        self.procedure_box = _group("Procedure enable complete", self.procedure)
        right.addWidget(self.procedure_box)
        self.issues = W.QListWidget()
        right.addWidget(_group("Compatibility", self.issues))
        right.setSizes([150, 400, 320, 150])
        splitter.setSizes([600, 700])
        self.refresh()

    def set_requested(self, packet, peer_data=0, t_pm=T_PM_DEFAULT_US):
        """The host CsInitiatorConfigPacket / CsReflectorConfigPacket to compare against, or None."""
        self.requested = packet
        self.requested_peer_data = peer_data
        self.requested_t_pm = t_pm
        self.refresh()

    def set_mode(self, mode):
        """Show only the configuration and procedure rows the mode combination uses."""
        if mode != self.mode:
            self.mode = mode
            self.refresh()

    def add_packet(self, packet):
        if self.reports.add(packet):
            self.refresh()

    def set_fae_table(self, packet, *, link_number=0, timestamp=None):
        """Show the latest successfully read remote FAE table."""
        try:
            table = FaeTable.from_packet(packet)
        except ValueError as error:
            self.fae_box.setTitle(f"Remote FAE table · {error}")
            return False
        self.fae_table = table
        self.fae_link_number = link_number
        self.fae_report_time = timestamp
        self.draw_fae()
        return True

    def clear(self):
        """Forget the reports of a link that is gone; the requested configuration stays."""
        self.reports.clear()
        self.fae_table = None
        self.fae_report_time = None
        self.draw_fae()
        self.refresh()

    def replay(self, entries):
        """Rebuild the tab from a capture's ``(packet, direction)`` stream, with a single redraw.

        Received reports fill the tables the way a live link does, including the
        clearing at each link teardown, so a capture of several links ends on
        the last one.  The host's own configuration commands restore what that
        session requested; a hostless capture has none and compares nothing.
        """
        self.reports.clear()
        self.fae_table = None
        self.fae_report_time = None
        self.requested, self.requested_peer_data, self.requested_t_pm = None, 0, T_PM_DEFAULT_US
        link_number = 0
        for packet, direction in entries:
            if direction == "sent":
                if isinstance(packet, (CsInitiatorConfigPacket, CsReflectorConfigPacket)):
                    self.requested = packet
                elif isinstance(packet, PeerDataPacket):
                    self.requested_peer_data = packet.peer_data
                elif isinstance(packet, TpmPacket):
                    self.requested_t_pm = packet.t_pm_us
            elif direction == "received":
                if isinstance(packet, ClientStatePacket) and packet.state == ClientState.LINK_CONNECTED:
                    link_number += 1
                elif isinstance(packet, ClientStatePacket) and packet.state in (ClientState.LINK_LOST,
                                                                                ClientState.LINK_DISCONNECTED):
                    self.reports.clear()
                    self.fae_table = None
                    self.fae_report_time = None
                elif isinstance(packet, CsFaeTablePacket):
                    self.set_fae_table(packet, link_number=link_number)
                else:
                    self.reports.add(packet)
        self.draw_fae()
        self.refresh()

    def issue_list(self):
        configuration, procedure = self.reports.current()
        return check_compatibility(self.reports.capabilities, requested=self.requested,
                                   configuration=configuration, procedure=procedure,
                                   peer_data=self.requested_peer_data, t_pm=self.requested_t_pm)

    def refresh(self):
        self.draw_capabilities()
        connection = self.reports.connection
        self.draw_rows(self.connection, compare_connection(self.requested, connection) if connection else [])
        self.connection_box.setTitle("Connection parameters" + ("" if connection else " · not received"))
        configuration, procedure = self.reports.current()
        mode = self.mode if self.mode is not None else configuration.mode if configuration else None
        hidden = {MODE_ROWS[key] for key in unused_fields(mode) if key in MODE_ROWS}
        self.draw_rows(self.configuration, [row for row in compare_configuration(
            self.requested, configuration, self.requested_peer_data, self.requested_t_pm)
            if row.field not in hidden]
                       if configuration else [])
        self.draw_rows(self.procedure, [row for row in compare_procedure(self.requested, procedure, connection)
                                        if row.field not in hidden] if procedure else [])
        self.configuration_box.setTitle("Configuration complete" +
                                        (f" · ID {configuration.id}" if configuration else " · not received"))
        self.procedure_box.setTitle("Procedure enable complete" +
                                    (f" · ID {procedure.config_id}" if procedure else " · not received"))
        issues = self.issue_list()
        set_list(self.issues, [(text, TINTS[OUTSIDE]) for text in issues] or
                 [("No unsupported settings found" if self.reports.capabilities else "Waiting for capabilities reports", None)])
        received = [source_label(self.reports.capabilities[s]) for s in SOURCES if s in self.reports.capabilities]
        failures = sum(text.startswith(RUN_FAILS) for text in issues)
        self.status_text = (f"Capabilities: {', '.join(received) or 'none'} · " +
                            (f"{failures} run failure{'s' if failures != 1 else ''} · " if failures else "") +
                            f"{len(issues)} compatibility issue{'s' if len(issues) != 1 else ''} · "
                            f"requested configuration {'set' if self.requested is not None else 'not set'}")
        self.status_message.emit(self.status_text)

    def draw_capabilities(self):
        columns = {source: capability_rows(self.reports.capabilities[source])
                   for source in SOURCES if source in self.reports.capabilities}
        for column, source in enumerate(SOURCES, start=1):
            caps = self.reports.capabilities.get(source)
            self.capabilities.horizontalHeaderItem(column).setText(source_label(caps) if caps else source.name.title())
        labels = next(iter(columns.values()), [])
        self.capabilities.setRowCount(len(labels))
        for row, capability in enumerate(labels):
            set_cell(self.capabilities, row, 0, capability.label)
            for column, source in enumerate(SOURCES, start=1):
                entry = columns[source][row] if source in columns else None
                # Optional features are only highlighted when present; problems are listed under Compatibility.
                set_cell(self.capabilities, row, column, entry.text if entry else "—",
                         TINTS[OK] if entry is not None and entry.supported else None)

    def draw_fae(self):
        table = self.fae_table
        self.fae.setRowCount(len(FAE_CHANNELS) if table is not None else 0)
        if table is None:
            self.fae_box.setTitle("Remote FAE table · not received")
            return
        for row, (channel, raw, ppm) in enumerate(zip(FAE_CHANNELS, table.entries, table.ppm())):
            set_cell(self.fae, row, 0, str(channel))
            set_cell(self.fae, row, 1, str(raw))
            set_cell(self.fae, row, 2, f"{ppm:+.5f}")
        when = f" · {self.fae_report_time}" if self.fae_report_time is not None else ""
        self.fae_box.setTitle(f"Remote FAE table · link {self.fae_link_number} · {table.ppm_per_lsb:g} ppm/LSB{when}")

    @staticmethod
    def draw_rows(table, rows):
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            for column, text in enumerate((row.field, row.requested, row.negotiated, STATUS_TEXT.get(row.status, ""))):
                set_cell(table, index, column, text, TINTS[row.status] if row.status in TINTS and column else None)
