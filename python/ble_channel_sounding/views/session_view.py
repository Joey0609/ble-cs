"""Session tab: the timeline of whatever session is open (implementation_plan.md §7.8).

The session is the live or last run (its temporary history file, §7.1) or an
opened capture. Its timeline holds every record in order: frames sent to the
client, frames received from it, and local logs (host messages and peer
console lines, §7.6/§7.7). The panel below it shows the selected record
parsed. Results keeps only the analysis views.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import math
from types import SimpleNamespace

from PyQt6 import QtCore, QtGui, QtWidgets as W

from ..protocol.frame import Frame
from ..protocol.packets import CsSubeventResultPacket, LogMessagePacket, PacketType
from ..report_log import describe_received, describe_sent
from ..results import (MAX_PACKETS, STEP_FLAG_FREQ_OFFSET_VALID, STEP_FLAG_PCT_VALID, STEP_FLAG_RSSI_VALID,
                       STEP_FLAG_TIME_DIFFERENCE_VALID, centi_ppm, describe)
from ..session_history import HostMessage, ProcedureSummary
from .cells import fill_table, make_table

HISTORY_COLORS = {"wrn": "#b7791f", "err": "#d64545"}
PROCEDURE_STATUS = {0: "complete", 1: "incomplete", 0x0F: "aborted"}
PROCEDURE_ABORT = {0: "—", 1: "requested", 2: "too few channels", 3: "chmap instant passed", 0x0F: "unspecified"}
SUBEVENT_ABORT = {0: "—", 1: "requested", 2: "no CS_SYNC", 3: "scheduling conflict", 0x0F: "unspecified"}
QUALITY = {0: "high", 1: "medium", 2: "low", 3: "n/a"}
KIND_LABELS = (("subevent", "Subevents"), ("report", "Reports"), ("log", "Client log"),
               ("host", "Host"), ("peer", "Peer"), ("other", "Other"))
# Records read per index query while browsing, and the rows kept from those windows.
DISK_WINDOW_ROWS = 512
DISK_CACHE_ROWS = 4 * DISK_WINDOW_ROWS


def record_level(packet, direction: str) -> str:
    """Session-log level of a record: "err", "wrn" or "inf"."""
    if isinstance(packet, HostMessage):
        return packet.level
    try:
        return (describe_sent(packet) if direction == "sent" else describe_received(packet)).level
    except (AttributeError, ValueError):
        return "inf"


def _flags(flags: int) -> str:
    names = ((STEP_FLAG_RSSI_VALID, "RSSI"), (STEP_FLAG_FREQ_OFFSET_VALID, "FO"),
             (STEP_FLAG_TIME_DIFFERENCE_VALID, "TD"), (STEP_FLAG_PCT_VALID, "PCT"))
    return " ".join(name for bit, name in names if flags & bit) or "—"


def _role(packet) -> str:
    return "Reflector" if packet.__class__.__name__.startswith("CsReflector") else "Initiator"


class MemoryHistory:
    """History-source adapter for captures and the bounded live ResultStore."""

    def __init__(self, packets):
        self.entries = []
        for fallback_index, entry in enumerate(packets):
            if isinstance(entry, tuple):
                timestamp, packet, *direction = entry
                direction = direction[0] if direction else "received"
                index = fallback_index
            else:
                timestamp, packet, direction = entry.timestamp, entry.packet, entry.direction
                # ResultStore entries keep their monotonically increasing
                # index even after the bounded deque drops its head. Keep it
                # here for stable detail/history references.
                index = getattr(entry, "index", fallback_index)
            if isinstance(packet, HostMessage):
                direction = "host"
            self.entries.append(SimpleNamespace(index=index, timestamp=timestamp, direction=direction,
                                                packet_type=getattr(packet, "packet_type", getattr(packet, "PACKET_TYPE", 0)),
                                                kind=self.kind(packet), source=getattr(packet, "source", ""),
                                                level=record_level(packet, direction),
                                                procedure_key=self.procedure_key(packet), packet=packet))
        times = [entry.timestamp for entry in self.entries if entry.timestamp is not None]
        self.origin = min(times) if times else None
        self.truncated = False
        self.first_kept_timestamp = self.origin
        self.level_counts = (sum(entry.level == "wrn" for entry in self.entries),
                             sum(entry.level == "err" for entry in self.entries))

    @property
    def empty(self):
        return not self.entries

    @staticmethod
    def kind(packet):
        if isinstance(packet, HostMessage):
            return "peer" if packet.source == "peer" else "host"
        if isinstance(packet, CsSubeventResultPacket):
            return "subevent"
        if isinstance(packet, LogMessagePacket):
            return "log"
        if type(packet).__name__ in ("CsCapabilitiesPacket", "CsConfigurationPacket",
                                     "CsProcedureEnableCompletePacket", "ConnectionParametersPacket"):
            return "report"
        return "other"

    @staticmethod
    def procedure_key(packet):
        return ((packet.config_id, packet.start_acl_conn_event, packet.procedure_counter)
                if isinstance(packet, CsSubeventResultPacket) else None)

    def procedure_summaries(self, *, after=None, flush=True):
        """Procedures in this capture, in first-appearance order, as SessionHistory reports them."""
        bound = -1 if after is None else int(after)
        counts = OrderedDict()
        lowest = highest = None
        for entry in self.entries:
            index = entry.index
            lowest = index if lowest is None else min(lowest, index)
            highest = index if highest is None else max(highest, index)
            if entry.procedure_key is None or index <= bound:
                continue
            initiator, reflector, first, last = counts.get(entry.procedure_key, (0, 0, index, index))
            counts[entry.procedure_key] = (
                initiator + (entry.packet_type == PacketType.CS_INITIATOR_SUBEVENT_RESULT),
                reflector + (entry.packet_type == PacketType.CS_REFLECTOR_SUBEVENT_RESULT),
                min(first, index), max(last, index))
        summaries = tuple(ProcedureSummary(key, *value) for key, value in counts.items())
        return summaries, bound if highest is None else max(bound, highest), bound + 1 if lowest is None else lowest

    def snapshot(self, *, flush=True, limit=None):
        if limit is None:
            return tuple(self.entries)
        return tuple(self.entries[-limit:]) if limit > 0 else ()

    @staticmethod
    def read(entry):
        return entry.packet


class HistoryModel(QtCore.QAbstractItemModel):
    """Lazy tree model: root rows are indexed records, children are step summaries.

    A QModelIndex here carries only numbers: a record row has internal id 0,
    and a step row carries its record's row plus one.  PyQt keeps no reference
    to a Python object handed to createIndex(), and a stopped session reads its
    records through a bounded cache over the on-disk index, so an index holding
    a HistoryEntry would outlive the entry and crash the view when Qt read it
    back.  Rows are resolved through _entry_at() instead.
    """

    HEADERS = ("Time", "Direction", "Type", "Procedure", "Summary")
    search_progress = QtCore.pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = None
        self.rows = []
        self._search = ""
        self._types = set()
        self._low = None
        self._high = None
        self._live = False
        self._generation = 0
        self._search_entries = None
        self._search_position = 0
        self._decoded = OrderedDict()
        self._row_count = 0
        self._disk_mode = False
        self._row_entries = OrderedDict()

    def _set_rows(self, rows):
        self.rows = rows
        self._row_count = len(rows)
        self._row_entries.clear()

    def _disk_entry(self, row):
        entry = self._row_entries.get(row)
        if entry is not None:
            return entry
        # The tree lays out every row of a browsed session, so reading one row
        # per query would scan the index once per row.  Read the window the row
        # falls in and keep the last few windows.
        start = row - row % DISK_WINDOW_ROWS
        window = self.source.entries_from(start, DISK_WINDOW_ROWS, types=self._types,
                                          low=self._low, high=self._high)
        for offset, entry in enumerate(window):
            self._row_entries[start + offset] = entry
        while len(self._row_entries) > DISK_CACHE_ROWS:
            self._row_entries.popitem(last=False)
        return self._row_entries.get(row)

    def _entry_at(self, row):
        """The record in one row, or None once that row is gone."""
        if row is None or row < 0:
            return None
        if self._disk_mode:
            return self._disk_entry(row) if row < self._row_count else None
        return self.rows[row] if row < len(self.rows) else None

    def _record_index(self, row, column=0):
        """A record (root) index, or an invalid index for a row that is gone."""
        return self.createIndex(row, column) if self._entry_at(row) is not None else QtCore.QModelIndex()

    @staticmethod
    def _procedure_text(key):
        return "" if key is None else f"Procedure {key[2]} · config {key[0]} · ACL {key[1]}"

    @staticmethod
    def _summary(packet, direction):
        if isinstance(packet, HostMessage):
            return f"{packet.source}: {packet.text}", ()
        children = ()
        if isinstance(packet, CsSubeventResultPacket):
            children = tuple(f"Step {index} · mode {step.mode} · channel {step.channel} · {len(step.tones)} tones"
                             for index, step in enumerate(packet.steps))
        try:
            line = describe_sent(packet) if direction == "sent" else describe_received(packet)
            return line.text, children
        except (AttributeError, ValueError):
            if isinstance(packet, Frame):
                return f"Unknown frame 0x{packet.packet_type:04x}", ()
            return type(packet).__name__.removesuffix("Packet"), children

    def refresh(self, source, *, types, search="", low=None, high=None, live=False):
        self._generation += 1
        generation = self._generation
        self.beginResetModel()
        self.source, self._search, self._types = source, search.lower(), set(types)
        self._low, self._high, self._live = low, high, live
        self._decoded.clear()
        self._row_entries.clear()
        self._disk_mode = False
        self._row_count = 0
        rows = []
        if source is not None:
            if not self._search and not live and hasattr(source, "entry_count"):
                self._disk_mode = True
                self._row_count = source.entry_count(types=self._types, low=low, high=high)
                self.endResetModel()
                self._search_entries = None
                self.search_progress.emit(0, 0)
                return
            limit = MAX_PACKETS if live and not self._search else None
            try:
                entries = source.snapshot(flush=not live, limit=limit)
            except TypeError:
                entries = source.snapshot(flush=not live)
                if limit is not None:
                    entries = entries[-limit:]
            if self._search:
                self._set_rows([])
                self._search_entries = tuple(entries)
                self._search_position = 0
                self.endResetModel()
                self.search_progress.emit(0, len(self._search_entries))
                QtCore.QTimer.singleShot(0, lambda: self._search_chunk(generation))
                return
            for entry in entries:
                if self._allowed(entry):
                    rows.append(entry)
        if live:
            rows = rows[-MAX_PACKETS:]
        self._set_rows(rows)
        self.endResetModel()
        self._search_entries = None
        self.search_progress.emit(0, 0)

    def _row_for(self, entry):
        if not self._allowed(entry):
            return None
        try:
            packet = self.source.read(entry)
        except (KeyError, OSError, ValueError):
            return None
        summary, children = self._summary(packet, entry.direction)
        values = self._values(entry, summary)
        if self._search and self._search not in " ".join(values).lower() and \
                not any(self._search in child.lower() for child in children):
            return None
        return entry

    def _allowed(self, entry):
        # Warnings and errors are never hidden by the type filter.
        if entry.kind not in self._types and getattr(entry, "level", "") not in ("err", "wrn"):
            return False
        key = entry.procedure_key
        if key is not None and ((self._low is not None and key[2] < self._low) or
                                (self._high is not None and key[2] > self._high)):
            return False
        return True

    def _values(self, entry, summary):
        time_text = "—"  # unknown, or a context record seeded before the session started
        origin = getattr(self.source, "origin", None)
        if entry.timestamp is not None and (origin is None or entry.timestamp >= origin):
            time_text = f"{entry.timestamp - (origin if origin is not None else entry.timestamp):.3f} s"
        if entry.kind in ("host", "peer"):
            direction = entry.kind.title()
        else:
            direction = "Sent" if entry.direction == "sent" else "Received"
        kind = dict(KIND_LABELS).get(entry.kind, entry.kind.title()).removesuffix("s")
        level = getattr(entry, "level", "")
        return (time_text, direction, f"{kind} · {level}" if level in ("err", "wrn") else kind,
                self._procedure_text(entry.procedure_key), summary)

    def _decoded_entry(self, entry):
        key = entry.index
        if key in self._decoded:
            row = self._decoded.pop(key)
            self._decoded[key] = row
            return row
        try:
            packet = self.source.read(entry)
            summary, children = self._summary(packet, entry.direction)
            row = SimpleNamespace(values=self._values(entry, summary), children=children, packet=packet)
        except (KeyError, OSError, ValueError):
            row = SimpleNamespace(values=("—", "", "", self._procedure_text(entry.procedure_key),
                                          "History entry unavailable"), children=(), packet=None)
        self._decoded[key] = row
        while len(self._decoded) > MAX_PACKETS:
            self._decoded.popitem(last=False)
        return row

    def _search_chunk(self, generation):
        if generation != self._generation or self._search_entries is None:
            return
        end = min(self._search_position + 100, len(self._search_entries))
        for entry in self._search_entries[self._search_position:end]:
            row = self._row_for(entry)
            if row is not None:
                self.rows.append(row)
        self._search_position = end
        self.beginResetModel()
        if self._live:
            self.rows = self.rows[-MAX_PACKETS:]
        self._row_count = len(self.rows)
        self.endResetModel()
        self.search_progress.emit(end, len(self._search_entries))
        if end < len(self._search_entries):
            QtCore.QTimer.singleShot(0, lambda: self._search_chunk(generation))
        else:
            self._search_entries = None

    def rowCount(self, parent=QtCore.QModelIndex()):
        try:
            if not parent.isValid():
                return self._row_count if self._disk_mode else len(self.rows)
            if self._live or parent.internalId() or parent.column() != 0:
                return 0
            entry = self._entry_at(parent.row())
        except RuntimeError:
            return 0
        return 0 if entry is None else len(self._decoded_entry(entry).children)

    def hasChildren(self, parent=QtCore.QModelIndex()):
        """Whether a row has step children, answered from the index alone.

        The tree asks this for every row it lays out, and a browsed session
        lays out all of them.  Only subevent records have step children, and
        the index knows which records those are, so the payload stays unread
        until the row is expanded.
        """
        try:
            if not parent.isValid():
                return bool(self._row_count if self._disk_mode else self.rows)
            if self._live or parent.internalId() or parent.column() != 0:
                return False
            entry = self._entry_at(parent.row())
        except RuntimeError:
            return False
        return entry is not None and entry.kind == "subevent"

    def columnCount(self, parent=QtCore.QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if role == QtCore.Qt.ItemDataRole.DisplayRole and orientation == QtCore.Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def index(self, row, column, parent=QtCore.QModelIndex()):
        try:
            if not self.hasIndex(row, column, parent):
                return QtCore.QModelIndex()
            if not parent.isValid():
                return self._record_index(row, column)
            if self._live or parent.internalId() or parent.column() != 0:
                return QtCore.QModelIndex()
            parent_row = parent.row()
        except RuntimeError:
            return QtCore.QModelIndex()
        return self.createIndex(row, column, parent_row + 1)

    def parent(self, index):
        try:
            if not index.isValid() or self._live or not index.internalId():
                return QtCore.QModelIndex()
            parent_row = index.internalId() - 1
        except RuntimeError:
            return QtCore.QModelIndex()
        # A view can ask for the parent of an index from the old model
        # contents while a reset is being processed.  That row is no longer
        # necessarily filled after a filter or live-tail refresh.
        return self._record_index(parent_row)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        try:
            if not index.isValid():
                return None
            parent_row = index.internalId() - 1  # -1 for a record row
            row, column = index.row(), index.column()
        except RuntimeError:
            return None
        entry = self._entry_at(row if parent_row < 0 else parent_row)
        if entry is None:
            return None
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            color = HISTORY_COLORS.get(getattr(entry, "level", ""))
            return QtGui.QBrush(QtGui.QColor(color)) if color else None
        if role != QtCore.Qt.ItemDataRole.DisplayRole:
            return None
        if parent_row < 0:
            values = self._decoded_entry(entry).values
        else:
            children = self._decoded_entry(entry).children
            if row >= len(children):
                return None
            values = ("", "", "", self._procedure_text(entry.procedure_key), children[row])
        return values[column]

    def flags(self, index):
        try:
            valid = index.isValid()
        except RuntimeError:
            valid = False
        return QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable \
            if valid else QtCore.Qt.ItemFlag.NoItemFlags

    def entry_for(self, index):
        try:
            if not index.isValid():
                return None
            parent_row = index.internalId() - 1  # -1 for a record row
            row = index.row()
        except RuntimeError:
            return None
        return self._entry_at(row if parent_row < 0 else parent_row)

    def index_for_entry(self, entry_index):
        """Return the current parent-row index for a stable history index."""
        if entry_index is None:
            return QtCore.QModelIndex()
        if self._disk_mode:
            row = self.source.entry_position(entry_index, types=self._types, low=self._low, high=self._high)
            return self.index(row, 0) if row is not None else QtCore.QModelIndex()
        row = next((row for row, entry in enumerate(self.rows)
                    if getattr(entry, "index", None) == entry_index), None)
        return self.index(row, 0) if row is not None else QtCore.QModelIndex()


def _add_fields(parent, value):
    """Nested dict/list values as child items; long lists stay collapsed."""
    items = value.items() if isinstance(value, dict) else enumerate(value)
    for name, child_value in items:
        if isinstance(child_value, (dict, list)):
            child = W.QTreeWidgetItem((str(name), f"{len(child_value)} items" if isinstance(child_value, list) else ""))
            _add_fields(child, child_value)
        else:
            child = W.QTreeWidgetItem((str(name), str(child_value)))
            child.setToolTip(1, child.text(1)[:2000])
        parent.addChild(child)


class SessionView(W.QWidget):
    """Timeline of the open session and a parsed view of the selected record.

    ``owner`` is the Results widget that holds the open session: its temporary
    history, a loaded capture or, before either, the bounded live store.
    """

    save_session_requested = QtCore.pyqtSignal(str, str)

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.running = False
        layout = W.QVBoxLayout(self)
        layout.setSpacing(6)

        header = W.QHBoxLayout()
        self.source_label = W.QLabel()
        self.source_label.setStyleSheet("font-weight: 600;")
        header.addWidget(self.source_label)
        self.truncation_label = W.QLabel()
        self.truncation_label.setStyleSheet("color: #b7791f;")
        self.truncation_label.setVisible(False)
        header.addWidget(self.truncation_label)
        header.addStretch(1)
        self.counts_label = W.QLabel()
        header.addWidget(self.counts_label)
        self.save_session_button = W.QPushButton("Save session…")
        self.save_session_button.clicked.connect(self.save_session)
        header.addWidget(self.save_session_button)
        layout.addLayout(header)
        self.description_label = W.QLabel()
        self.description_label.setWordWrap(False)
        self.description_label.setStyleSheet("background: #fff8dc; padding: 4px 8px;")
        self.description_label.setVisible(False)
        layout.addWidget(self.description_label)

        filters = W.QHBoxLayout()
        self.search = W.QLineEdit()
        self.search.setPlaceholderText("Search session…")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 1)
        self.types = {}
        for key, label in KIND_LABELS:
            check = W.QCheckBox(label)
            check.setChecked(True)
            check.setToolTip("Applies to the whole session; warnings and errors are always shown")
            self.types[key] = check
            filters.addWidget(check)
        filters.addWidget(W.QLabel("Procedure"))
        self.procedure_from = W.QLineEdit()
        self.procedure_from.setPlaceholderText("from")
        self.procedure_from.setMaximumWidth(70)
        self.procedure_to = W.QLineEdit()
        self.procedure_to.setPlaceholderText("to")
        self.procedure_to.setMaximumWidth(70)
        filters.addWidget(self.procedure_from)
        filters.addWidget(W.QLabel("–"))
        filters.addWidget(self.procedure_to)
        self._filter_controls = (self.search, *self.types.values(), self.procedure_from, self.procedure_to)
        self.search_status = W.QLabel()
        filters.addWidget(self.search_status)
        self.pause = W.QPushButton("Pause", checkable=True)
        self.pause.setToolTip("Stop following the live session; records keep being collected")
        self.pause.toggled.connect(lambda paused: None if paused else self.draw(force=True))
        filters.addWidget(self.pause)
        layout.addLayout(filters)

        self.tree = W.QTreeView()
        self.model = HistoryModel(self.tree)
        self.tree.setModel(self.model)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.header().setStretchLastSection(True)
        self.record = W.QTreeWidget()
        self.record.setHeaderLabels(("Field", "Value"))
        # This is a materialized copy of the selected history row.  It stays
        # visible after the live tail evicts the source row.
        self.selected_entry = make_table(("Time", "Direction", "Type", "Procedure", "Summary", "State"))
        self.procedure_table = make_table(("Field", "Value"))
        self.steps_table = make_table(("Role", "Report", "Step", "Mode", "Ch", "MHz", "Flags", "AA q", "Bit err",
                                       "RSSI", "Ant", "NADM", "Freq offset (ppm)", "Time diff", "PCT1", "PCT2",
                                       "Perm", "Tones (path: I Q |A| ∠φ quality ext)"))
        self.subevent_table = make_table(("Role", "Report", "Config", "ACL event", "Counter", "Freq comp (ppm)",
                                          "Ref power (dBm)", "Procedure", "Subevent", "Procedure abort",
                                          "Subevent abort", "Paths", "Steps", "Abort step"))
        self.detail = W.QTabWidget()
        self.detail.addTab(self.selected_entry, "Selected entry")
        self.detail.addTab(self.record, "Record")
        self.detail.addTab(self.procedure_table, "Procedure")
        self.detail.addTab(self.subevent_table, "Subevents")
        self.detail.addTab(self.steps_table, "Steps")
        splitter = W.QSplitter(QtCore.Qt.Orientation.Vertical)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.detail)
        splitter.setSizes([500, 240])
        layout.addWidget(splitter, 1)

        self.search.textChanged.connect(self.redraw)
        for check in self.types.values():
            check.toggled.connect(self.redraw)
        self.procedure_from.textChanged.connect(self.redraw)
        self.procedure_to.textChanged.connect(self.redraw)
        self.tree.selectionModel().currentChanged.connect(self.record_selected)
        self.model.modelReset.connect(self._restore_selection)
        self.model.search_progress.connect(self.show_search_progress)
        self._refreshing_model = False
        # Stable history index of the record copied into the detail pane: the
        # row the timeline must keep highlighted across model resets.
        self._selected_index = None
        self._syncing_selection = False
        self._set_browsing_controls()
        self.set_description("")
        self.draw()

    # Source ------------------------------------------------------------------

    def source(self):
        history = self.owner.session_history
        if history is not None and (getattr(history, "closed", False) or
                                    getattr(history, "error", None) is not None):
            # The session may disable/close its writer while a redraw is
            # already queued. Keep the view usable from the bounded store
            # instead of asking a dead writer to flush again.
            if self.owner.session_history is history:
                self.owner.session_history = None
                self.owner.live_history = False
            history = None
        return history if history is not None else MemoryHistory(self.owner.store.packets)

    def set_running(self, running):
        running = bool(running)
        changed = running != self.running
        self.running = running
        if running and changed and not self._recording_playback():
            self._clear_filters()
        self._set_browsing_controls()
        if changed:
            self.draw(force=True)

    def _set_browsing_controls(self):
        """Enable browsing controls for stopped sessions and recording playback.

        A row is always selectable, live tail included: clicking one reads it
        out of the records the view already holds (§7.9).  Searching and
        filtering are what would have to read the whole session, so they stay
        disabled while the tail runs.
        """
        browsing = not self._live_tail()
        for widget in self._filter_controls:
            widget.setEnabled(browsing)
        self.pause.setEnabled(self.running)
        if not self.running and self.pause.isChecked():
            blocked = self.pause.blockSignals(True)
            self.pause.setChecked(False)
            self.pause.blockSignals(blocked)

    @contextmanager
    def _silent_selection(self):
        """Move the highlight without telling record_selected(), and repaint the rows it leaves.

        The view repaints the row a highlight leaves and the one it lands on
        from the selection model's ``selectionChanged``/``currentChanged``, so
        blocking those signals leaves the old row painted as selected: only one
        row is ever selected, but several look it.
        """
        selection_model = self.tree.selectionModel()
        blocked = selection_model.blockSignals(True)
        try:
            yield selection_model
        finally:
            selection_model.blockSignals(blocked)
            self.tree.viewport().update()

    def _clear_history_selection(self):
        """Clear the timeline highlight without clearing the copied detail row."""
        with self._silent_selection() as selection_model:
            selection_model.clearSelection()
            selection_model.setCurrentIndex(QtCore.QModelIndex(),
                                            QtCore.QItemSelectionModel.SelectionFlag.Clear)

    def _visible_row(self, index):
        """True while a row is inside the viewport; an empty rect means it is not laid out."""
        rect = self.tree.visualRect(index)
        return not rect.isEmpty() and self.tree.viewport().rect().intersects(rect)

    def _select_row(self, index, *, scroll=True):
        """Highlight a row without asking record_selected() to show it again."""
        with self._silent_selection():
            self.tree.setCurrentIndex(index)
        if scroll and not self._visible_row(index):
            # Only a model reset moves the copied row out of view; an ordinary
            # click must leave the timeline where the user scrolled it.
            self.tree.scrollTo(index, W.QAbstractItemView.ScrollHint.PositionAtCenter)

    def _restore_selection(self):
        """Put the highlight back on the copied row after a model reset.

        A chunked search resets the model outside draw(), which drops the
        current index; the detail pane keeps its record, so the row it was
        copied from is highlighted again as soon as the search lists it.
        """
        if self._refreshing_model or self._selected_index is None:
            return
        restored = self.model.index_for_entry(self._selected_index)
        if restored.isValid():
            # A live tail keeps following the newest records, so putting the
            # highlight back there must not pull the view off them.
            self._select_row(restored, scroll=not self._live_tail())

    def _sync_detail(self):
        """Show the record the timeline highlights.

        A selection that lands while the model is being refreshed reaches the
        view with the selection signals blocked.  Without this the detail pane
        would keep the previous record while another row stays highlighted.
        """
        if self._syncing_selection:
            return
        current = self.tree.currentIndex()
        entry = self.model.entry_for(current)
        if entry is None or getattr(entry, "index", None) == self._selected_index:
            return
        self._syncing_selection = True
        try:
            self.record_selected(current, None)
        finally:
            self._syncing_selection = False

    def _clear_filters(self):
        """Return a live session to its unfiltered tail before it starts."""
        widgets = self._filter_controls
        blocked = [widget.blockSignals(True) for widget in widgets]
        try:
            self.search.clear()
            for check in self.types.values():
                check.setChecked(True)
            self.procedure_from.clear()
            self.procedure_to.clear()
            self.search_status.clear()
        finally:
            for widget, previous in zip(widgets, blocked):
                widget.blockSignals(previous)

    def redraw(self, *_):
        """A filter changed: redraw even while paused."""
        self.draw(force=True)

    def draw(self, *, force=False):
        """Refresh the timeline; a paused live view keeps its rows until Pause is released."""
        if self.pause.isChecked() and self.running and not force:
            self.update_header()
            return
        source = self.source()
        selected_entry_index = self._selected_index
        restored = QtCore.QModelIndex()
        with self._silent_selection():
            self._refreshing_model = True
            try:
                try:
                    self.model.refresh(source, types=(key for key, check in self.types.items() if check.isChecked()),
                                       search=self.search.text().strip().lower(),
                                       low=self._number(self.procedure_from.text()),
                                       high=self._number(self.procedure_to.text()), live=self._live_tail())
                except OSError:
                    # A writer failure can race this redraw between source() and
                    # snapshot(). Detach it and retain recent in-memory records.
                    if source is not self.owner.session_history:
                        raise
                    self.owner.session_history = None
                    self.owner.live_history = False
                    self.model.refresh(self.source(),
                                       types=(key for key, check in self.types.items() if check.isChecked()),
                                       search=self.search.text().strip().lower(),
                                       low=self._number(self.procedure_from.text()),
                                       high=self._number(self.procedure_to.text()), live=self._live_tail())
                # Keep selection changes caused by this reset out of
                # record_selected(). The clicked row is restored by its stable
                # history index, not by its transient model row.
                self.tree.clearSelection()
                self.tree.setCurrentIndex(QtCore.QModelIndex())
                restored = self.model.index_for_entry(selected_entry_index)
                if restored.isValid():
                    self.tree.setCurrentIndex(restored)
            finally:
                self._refreshing_model = False

        if self._live_tail():
            # A clicked row keeps its highlight while it is still in the tail,
            # but the tail goes on following the newest records; Pause is what
            # stops it.
            if not self.pause.isChecked():
                self.tree.scrollToBottom()
        elif restored.isValid():
            if not self._visible_row(restored):
                self.tree.scrollTo(restored, W.QAbstractItemView.ScrollHint.PositionAtCenter)
        elif not self.pause.isChecked():
            self.tree.scrollToBottom()
        self._sync_detail()
        self.update_header()

    def _recording_playback(self):
        return bool(getattr(self.owner, "recording_playback", False))

    def _live_tail(self):
        return bool(getattr(self.owner, "online_mode", False)) and not self._recording_playback()

    def update_header(self):
        owner, source = self.owner, self.source()
        if owner.live_history:
            text = ("Recording playback" if self.running else "Last playback") \
                if self._recording_playback() else ("Live session" if self._live_tail() else "Last session")
        elif owner.session_history is not None:
            text = f"Capture: {owner.capture_path.name}" if owner.capture_path is not None else "Capture"
        else:
            text = "No session yet: recent records"
        self.source_label.setText(text)
        truncated = bool(getattr(source, "truncated", False))
        self.truncation_label.setVisible(truncated)
        if truncated:
            origin = getattr(source, "origin", None) or 0.0
            first = getattr(source, "first_kept_timestamp", None)
            start = "" if first is None else f" at {first - origin:.3f} s"
            limit = getattr(source, "max_bytes", 0)
            size = f"{limit / 2**30:.1f} GB" if limit >= 2**30 else f"{limit / 2**20:.1f} MB"
            self.truncation_label.setText(f"· kept history starts{start}; older records were dropped at the "
                                          f"{size} limit" if limit else
                                          f"· kept history starts{start}; older records were dropped")
        counts = getattr(source, "level_counts", None)
        if counts is None:
            levels = [getattr(entry, "level", "") for entry in source.entries]
            counts = (levels.count("wrn"), levels.count("err"))
        self.counts_label.setText(f"{counts[0]} warnings · {counts[1]} errors")
        # Only the live session's history is saved; a capture already is a file.
        self.save_session_button.setEnabled(bool(owner.live_history) and not owner.session_history.empty)

    @staticmethod
    def _number(text):
        try:
            return int(text.strip()) if text.strip() else None
        except ValueError:
            return None

    def show_search_progress(self, done, total):
        self.search_status.setText(f"Searching {done:,}/{total:,}…" if total else "")

    def set_description(self, text):
        text = str(text or "")
        self.description_label.setVisible(bool(text))
        self.description_label.setText(" ".join(text.splitlines()))
        self.description_label.setToolTip(text)

    # Save session --------------------------------------------------------------

    def save_session(self):
        history = self.owner.session_history
        if not self.owner.live_history or history.empty:
            return
        recording = self.owner.session_recording()
        if recording is not None:
            answer = W.QMessageBox.question(
                self, "Save session", f"Recording was on for this whole session: {recording.name} already "
                "holds it.\n\nOpen that recording instead of saving another file?",
                W.QMessageBox.StandardButton.Open | W.QMessageBox.StandardButton.Save |
                W.QMessageBox.StandardButton.Cancel)
            if answer == W.QMessageBox.StandardButton.Open:
                self.owner.open_capture_path(recording)
                return
            if answer != W.QMessageBox.StandardButton.Save:
                return
        dialog = W.QDialog(self)
        dialog.setWindowTitle("Save session")
        form = W.QFormLayout(dialog)
        path = W.QLineEdit(self.owner.default_session_path())
        browse = W.QPushButton("Browse…")
        path_row = W.QHBoxLayout()
        path_row.addWidget(path, 1)
        path_row.addWidget(browse)
        form.addRow("File", path_row)
        description = W.QPlainTextEdit(self.owner.description_text)
        description.setPlaceholderText("Optional session description")
        description.setMinimumHeight(90)
        form.addRow("Description", description)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Save |
                                     W.QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)
        browse.clicked.connect(lambda: self._choose_path(path))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() == W.QDialog.DialogCode.Accepted and path.text().strip():
            self.save_session_requested.emit(path.text().strip(), description.toPlainText())

    def _choose_path(self, target):
        path, _ = W.QFileDialog.getSaveFileName(self, "Save session", target.text(),
                                                "HDF5 recordings (*.h5 *.hdf5)")
        if path:
            target.setText(path)

    # Record detail -------------------------------------------------------------

    def record_selected(self, current, _previous):
        """Show the selected record parsed; a subevent also fills Procedure, Subevents and Steps.

        The procedure detail comes from the decoded store, which is keyed by the
        procedure key, so it costs a lookup and a live run can have it too.  A
        browsed session whose procedure has already fallen out of that store
        rebuilds it from the indexed entries instead.
        """
        if self._refreshing_model:
            return
        live = self._live_tail()
        entry = self.model.entry_for(current)
        source = self.model.source
        if entry is None or source is None:
            # A model reset can deliver the invalid current index after the
            # reset has finished. The detail panel already contains the last
            # copied record, so there is nothing to restore here.
            return
        try:
            packet = source.read(entry)
        except (KeyError, OSError, ValueError):
            return
        self.show_record(entry, packet)
        self._selected_index = getattr(entry, "index", None)
        if live:
            # A live click must not read the whole session (§7.9), but it does
            # not have to: the analysis store the run is already filling is
            # keyed by the same procedure key, so the reports of the clicked
            # procedure cost one lookup.  A procedure the bounded store has
            # dropped leaves the three tabs empty until the session is replayed.
            if entry.kind == "subevent":
                self.draw_procedure_detail(self.store_reports(entry.procedure_key))
            return

        if entry.procedure_key is not None and hasattr(self.owner, "select_procedure_key"):
            self.owner.select_procedure_key(entry.procedure_key)
        if entry.kind == "subevent":
            reports = self.store_reports(entry.procedure_key)
            if not reports:
                # An older replay procedure that select_procedure_key() could
                # not restore is rebuilt from the indexed entries instead.
                entries = source.iter_entries() if hasattr(source, "iter_entries") else source.snapshot()
                for candidate in entries:
                    if candidate.procedure_key != entry.procedure_key or candidate.kind != "subevent":
                        continue
                    try:
                        report = source.read(candidate)
                    except (KeyError, OSError, ValueError):
                        continue
                    reports.append((_role(report), len(reports), report))
            self.draw_procedure_detail(reports)

        # Results may rebuild its bounded analysis store while an old replay
        # procedure is being selected, which resets the history model. Restore
        # the clicked row without emitting a second selection event.
        restored = self.model.index_for_entry(self._selected_index)
        if restored.isValid():
            self._select_row(restored)
        # A row the user reached while those signals were blocked is shown now,
        # so the highlight and the detail pane never name different records.
        self._sync_detail()

    def show_record(self, entry, packet, *, details=True):
        decoded = self.model._decoded_entry(entry)
        fill_table(self.selected_entry, [decoded.values + ("Selected",)])
        if not details:
            return
        self.record.clear()
        fill_table(self.procedure_table, [])
        fill_table(self.steps_table, [])
        fill_table(self.subevent_table, [])
        if isinstance(packet, HostMessage):
            title, values = f"{packet.source.title()} message", {"level": packet.level, "source": packet.source,
                                                                 "text": packet.text}
        elif isinstance(packet, Frame):
            title, values = f"Unknown frame 0x{packet.packet_type:04x}", {
                "packet_type": f"0x{packet.packet_type:04x}", "payload": packet.payload.hex()}
        else:
            title, values = type(packet).__name__.removesuffix("Packet"), describe(packet)
            if isinstance(packet, LogMessagePacket):
                values = {"text": packet.message.decode("utf-8", errors="replace").rstrip()}
        item = W.QTreeWidgetItem((title, decoded.values[1]))
        _add_fields(item, values)
        self.record.addTopLevelItem(item)
        item.setExpanded(True)
        self.record.resizeColumnToContents(0)
        # Show the parsed packet immediately after a selection.  The stable
        # selection snapshot remains available in its own tab, but making it
        # the default hides the record/procedure detail that was just filled.
        self.detail.setCurrentWidget(self.record)

    def store_reports(self, key):
        """Both roles' reports of one procedure from the decoded store, initiator first.

        The store is bounded and keyed by the same (config, ACL event, counter)
        triple as the history index, so this is a lookup rather than a scan of
        the session: it is what lets a live click fill the procedure detail.
        """
        store = getattr(self.owner, "store", None)
        procedure = store.procedures.get(key) if store is not None and key is not None else None
        if procedure is None:
            return []
        return [(_role(report), index, report)
                for index, report in enumerate((*procedure.initiator, *procedure.reflector))]

    def draw_procedure_detail(self, reports):
        """Fill the Procedure, Subevents and Steps tabs from one procedure's reports."""
        self.draw_procedure(reports)
        self.draw_steps(reports)
        self.draw_subevents(reports)

    def draw_procedure(self, reports):
        if not reports:
            fill_table(self.procedure_table, [])
            return
        first = reports[0][2]
        roles = ", ".join(dict.fromkeys(role for role, _, _ in reports))
        statuses = ", ".join(str(status) for status in dict.fromkeys(
            PROCEDURE_STATUS.get(report.procedure_done_status, report.procedure_done_status)
            for _, _, report in reports))
        rows = (("Config", first.config_id),
                ("ACL event", first.start_acl_conn_event),
                ("Counter", first.procedure_counter),
                ("Roles", roles),
                ("Subevents", len(reports)),
                ("Steps", sum(len(report.steps) for _, _, report in reports)),
                ("Status", statuses))
        fill_table(self.procedure_table, rows)

    def draw_steps(self, reports):
        rows = []
        for role, index, report in reports:
            for ordinal, step in enumerate(report.steps):
                offset = centi_ppm(step.measured_freq_offset) if step.flags & STEP_FLAG_FREQ_OFFSET_VALID else None
                pct = step.flags & STEP_FLAG_PCT_VALID
                tones = "  ".join(
                    f"{'ext' if n >= report.num_antenna_paths else t.antenna_path}: {t.i} {t.q} "
                    f"|{math.hypot(t.i, t.q):.0f}| ∠{math.degrees(math.atan2(t.q, t.i)):+.0f}° "
                    f"{QUALITY.get(t.quality, t.quality)} {t.extension}"
                    for n, t in enumerate(step.tones))
                rows.append((role, index, ordinal, step.mode, step.channel, 2402 + step.channel, _flags(step.flags),
                             step.aa_quality, step.bit_errors,
                             step.rssi if step.flags & STEP_FLAG_RSSI_VALID else "—",
                             step.antenna, "—" if step.nadm == 0xFF else step.nadm,
                             "—" if offset is None else f"{offset:+.2f}",
                             step.time_difference if step.flags & STEP_FLAG_TIME_DIFFERENCE_VALID else "—",
                             f"{step.pct1_i} {step.pct1_q}" if pct else "—",
                             f"{step.pct2_i} {step.pct2_q}" if pct else "—",
                             step.antenna_permutation_index if step.mode in (2, 3) else "—", tones))
        fill_table(self.steps_table, rows)

    def draw_subevents(self, reports):
        rows = []
        for role, index, r in reports:
            comp = centi_ppm(r.frequency_compensation)
            rows.append((role, index, r.config_id, r.start_acl_conn_event, r.procedure_counter,
                         "n/a" if comp is None else f"{comp:+.2f}",
                         "n/a" if r.reference_power_level == 0x7F else r.reference_power_level,
                         PROCEDURE_STATUS.get(r.procedure_done_status, r.procedure_done_status),
                         PROCEDURE_STATUS.get(r.subevent_done_status, r.subevent_done_status),
                         PROCEDURE_ABORT.get(r.procedure_abort_reason, r.procedure_abort_reason),
                         SUBEVENT_ABORT.get(r.subevent_abort_reason, r.subevent_abort_reason),
                         r.num_antenna_paths, len(r.steps), "—" if r.abort_step == 0xFF else r.abort_step))
        fill_table(self.subevent_table, rows)

    def clear_detail(self):
        self._selected_index = None
        fill_table(self.selected_entry, [])
        self.record.clear()
        fill_table(self.procedure_table, [])
        fill_table(self.steps_table, [])
        fill_table(self.subevent_table, [])
