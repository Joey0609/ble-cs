"""Bounded, temporary raw-frame history for one client session.

The live Results view deliberately keeps only a small decoded tail.  This
module keeps the complete session in temporary segment files instead.  The
writer is asynchronous, and a temporary SQLite index keeps old metadata on
disk; only the live tail is cached in Python memory.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
import queue
import sqlite3
import struct
import tempfile
import threading
import time
from typing import Any, Iterable, Iterator

from .protocol.frame import Frame
from .protocol.packets import (CsSubeventResultPacket, LogMessagePacket, PacketType,
                              decode_packet)


DEFAULT_HISTORY_MAX_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_HISTORY_SEGMENT_BYTES = 16 * 1024 * 1024
DEFAULT_HISTORY_TAIL_ENTRIES = 200
INDEX_COMMIT_ENTRIES = 128
# index, host time, direction (0 rx/1 tx/2 host), packet type, level flags, payload size
_HEADER = struct.Struct("<QdBHHI")
_HOST_PREFIX = struct.Struct("<H")
HOST_LEVELS = {"err": 1, "wrn": 2, "inf": 3, "dbg": 4,
               "error": 1, "warning": 2, "info": 3, "debug": 4}
HOST_LEVEL_NAMES = {1: "err", 2: "wrn", 3: "inf", 4: "dbg"}


def normalize_host_level(level: str | int) -> str:
    """Normalize host/peer records to the same short levels as client logs."""
    if isinstance(level, int):
        if level not in HOST_LEVEL_NAMES:
            raise ValueError("host log level must be 1 (error) through 4 (debug)")
        return HOST_LEVEL_NAMES[level]
    value = str(level).lower()
    if value not in HOST_LEVELS:
        raise ValueError("host log level must be info, warning, error or debug")
    return HOST_LEVEL_NAMES[HOST_LEVELS[value]]


@dataclass(frozen=True, slots=True)
class HostMessage:
    """A host-side or peer-console message stored beside protocol frames."""

    level: str
    source: str
    text: str


def _wire(packet: Any) -> bytes:
    return packet.to_bytes() if hasattr(packet, "to_bytes") else Frame.from_bytes(packet).to_bytes()


def _packet_type(packet: Any) -> int:
    return int(packet.packet_type if isinstance(packet, Frame) else packet.PACKET_TYPE)


def _procedure_key(packet: Any) -> tuple[int, int, int] | None:
    if not isinstance(packet, CsSubeventResultPacket):
        return None
    return packet.config_id, packet.start_acl_conn_event, packet.procedure_counter


def _kind(packet: Any) -> str:
    if isinstance(packet, CsSubeventResultPacket):
        return "subevent"
    if isinstance(packet, LogMessagePacket):
        return "log"
    if isinstance(packet, Frame):
        return "other"
    if type(packet).__name__ in {"CsCapabilitiesPacket", "CsConfigurationPacket",
                                 "CsProcedureEnableCompletePacket", "ConnectionParametersPacket"}:
        return "report"
    return "other"


def _level(packet: Any, direction: str) -> str:
    """The Session-log level of a frame: "err", "wrn" or "inf" (report_log wording)."""
    from .report_log import describe_received, describe_sent
    try:
        return (describe_sent(packet) if direction == "sent" else describe_received(packet)).level
    except (AttributeError, ValueError):
        return "inf"


@dataclass(frozen=True, slots=True)
class ProcedureSummary:
    """What a procedure looks like from the index alone: its key and report counts.

    Views that browse a whole session need every procedure it holds, which is
    far more than the bounded decoded store keeps.  The index knows the key and
    the reporting role of each subevent record, so a procedure can be listed
    without reading or decoding one payload.
    """

    key: tuple[int, int, int]
    initiator: int
    reflector: int
    first_index: int
    last_index: int


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """One indexed frame in temporary history."""

    index: int
    timestamp: float
    direction: str
    packet_type: int
    kind: str
    procedure_key: tuple[int, int, int] | None
    segment: int
    offset: int
    size: int
    source: str = ""
    level: str = ""


class SessionHistory:
    """Asynchronously write and randomly read a bounded session history.

    ``context`` is written first at time zero.  It is kept in the same raw
    stream as live frames, which makes a saved session self-contained and
    allows old configuration/procedure records to be reconstructed after the
    in-memory ResultStore has evicted them.  The index itself is disk-backed;
    callers should use ``iter_entries`` for streaming access to the full run.
    """

    def __init__(self, context: Iterable[Any] = (), *, max_bytes: int = DEFAULT_HISTORY_MAX_BYTES,
                 segment_bytes: int = DEFAULT_HISTORY_SEGMENT_BYTES, queue_size: int = 4096,
                 temp_dir: str | os.PathLike[str] | None = None):
        if max_bytes <= 0 or segment_bytes <= 0:
            raise ValueError("History limits must be positive")
        self.max_bytes = int(max_bytes)
        self.segment_bytes = int(segment_bytes)
        # The complete index is disk-backed. Only the live tail is kept in
        # Python memory for the running GUI.
        self._tail_entries: deque[HistoryEntry] = deque(maxlen=DEFAULT_HISTORY_TAIL_ENTRIES)
        self._level_counts = {"wrn": 0, "err": 0}
        self._segments: list[tuple[int, Any, int]] = []
        self._segment_files: dict[int, Any] = {}
        self._lock = threading.RLock()
        self._queue: queue.Queue[tuple[str, Any] | None] = queue.Queue(queue_size)
        self._ready = threading.Event()
        self._closed = False
        self._error: Exception | None = None
        self._next_index = 0
        self._next_segment_id = 0
        self._index_pending = 0
        self._total_bytes = 0
        self.truncated = False
        self.first_kept_timestamp: float | None = None
        # Host time of the first record after the context: the session's time zero in views.
        self.origin: float | None = None
        self._seeding = True
        self._temp_dir = temp_dir
        index_handle = tempfile.NamedTemporaryFile(prefix="cs-history-index-", suffix=".sqlite",
                                                    dir=temp_dir, delete=False)
        self._index_path = index_handle.name
        index_handle.close()
        self._index_conn = sqlite3.connect(self._index_path, check_same_thread=False)
        self._index_conn.execute("PRAGMA synchronous = NORMAL")
        self._index_conn.execute(
            """CREATE TABLE entries (
                   entry_index INTEGER PRIMARY KEY,
                   timestamp REAL NOT NULL,
                   direction TEXT NOT NULL,
                   packet_type INTEGER NOT NULL,
                   kind TEXT NOT NULL,
                   procedure_config INTEGER,
                   procedure_acl INTEGER,
                   procedure_counter INTEGER,
                   segment INTEGER NOT NULL,
                   offset INTEGER NOT NULL,
                   size INTEGER NOT NULL,
                   source TEXT NOT NULL,
                   level TEXT NOT NULL
               )"""
        )
        self._index_conn.execute("CREATE INDEX entries_segment ON entries(segment)")
        self._index_conn.commit()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="cs-session-history")
        self._thread.start()
        self._ready.wait()
        self._check()
        for packet in context:
            self.append(packet, timestamp=0.0, direction="received")
        self._seeding = False

    @property
    def error(self) -> Exception | None:
        return self._error

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def empty(self) -> bool:
        with self._lock:
            return self._index_conn.execute("SELECT 1 FROM entries LIMIT 1").fetchone() is None

    @property
    def entries(self) -> list[HistoryEntry]:
        """Return the bounded in-memory tail retained for compatibility/debugging."""
        with self._lock:
            return list(self._tail_entries)

    @property
    def size_bytes(self) -> int:
        with self._lock:
            return self._total_bytes

    @property
    def level_counts(self) -> tuple[int, int]:
        with self._lock:
            return self._level_counts["wrn"], self._level_counts["err"]

    def _check(self) -> None:
        if self._error is not None:
            raise OSError(f"Session history failed: {self._error}") from self._error

    def append(self, packet: Any, *, timestamp: float | None = None,
               direction: str = "received") -> None:
        """Queue one packet for history; the packet is serialized immediately."""
        if direction not in ("received", "sent"):
            raise ValueError("Direction must be received or sent")
        self._check()
        if self._closed:
            raise ValueError("Session history is closed")
        if self.origin is None and not self._seeding:
            self.origin = float(timestamp or 0.0)
        item = (self._next_index, float(timestamp or 0.0), direction, _wire(packet),
                _packet_type(packet), _kind(packet), _procedure_key(packet), _level(packet, direction))
        self._next_index += 1
        try:
            self._queue.put_nowait(("frame", item))
        except queue.Full as error:
            raise OSError("Session history queue full") from error

    def append_host(self, level: str | int, source: str, text: str,
                    timestamp: float | None = None) -> None:
        """Append a host or peer-console message in the session timeline."""
        self._check()
        if self._closed:
            raise ValueError("Session history is closed")
        level_name = normalize_host_level(level)
        source_text = str(source)
        source_bytes = source_text.encode("utf-8")
        text_text = str(text)
        text_bytes = text_text.encode("utf-8")
        if len(source_bytes) > 0xFFFF:
            raise ValueError("host message source is too long")
        payload = _HOST_PREFIX.pack(len(source_bytes)) + source_bytes + text_bytes
        if self.origin is None:
            self.origin = float(timestamp or 0.0)
        item = (self._next_index, float(timestamp or 0.0), level_name,
                source_text, text_text, payload)
        self._next_index += 1
        try:
            self._queue.put_nowait(("host", item))
        except queue.Full as error:
            raise OSError("Session history queue full") from error

    def flush(self, timeout: float = 10.0) -> None:
        """Wait until all packets queued before this call have been written."""
        self._check()
        # A history can be closed by session cleanup while a queued GUI redraw
        # is still waiting to inspect it. Do not enqueue a barrier behind the
        # worker's shutdown sentinel: that barrier can never be acknowledged.
        if not self._thread.is_alive():
            if self._closed:
                return
            self._check()
            raise OSError("Session history writer stopped before flushing")
        done = threading.Event()
        try:
            self._queue.put(("flush", done), timeout=timeout)
        except queue.Full as error:
            raise OSError("Session history queue full") from error
        deadline = time.monotonic() + timeout
        while not done.wait(min(0.1, max(0.0, deadline - time.monotonic()))):
            self._check()
            if not self._thread.is_alive():
                if self._closed:
                    return
                self._check()
                raise OSError("Session history writer stopped before flushing")
            if time.monotonic() >= deadline:
                raise OSError("Session history writer did not flush")
        self._check()

    def _new_segment(self) -> int:
        file = tempfile.TemporaryFile(dir=self._temp_dir)
        segment_id = self._next_segment_id
        self._next_segment_id += 1
        self._segments.append((segment_id, file, 0))
        self._segment_files[segment_id] = file
        return segment_id

    @staticmethod
    def _entry_row(entry: HistoryEntry) -> tuple[Any, ...]:
        procedure_config, procedure_acl, procedure_counter = entry.procedure_key or (None, None, None)
        return (entry.index, entry.timestamp, entry.direction, entry.packet_type, entry.kind,
                procedure_config, procedure_acl, procedure_counter, entry.segment, entry.offset,
                entry.size, entry.source, entry.level)

    @staticmethod
    def _entry_from_row(row) -> HistoryEntry:
        (index, timestamp, direction, packet_type, kind, procedure_config, procedure_acl,
         procedure_counter, segment, offset, size, source, level) = row
        procedure_key = None if procedure_config is None else (procedure_config, procedure_acl, procedure_counter)
        return HistoryEntry(index, timestamp, direction, packet_type, kind, procedure_key,
                            segment, offset, size, source, level)

    def _add_entry(self, entry: HistoryEntry) -> None:
        self._index_conn.execute(
            """INSERT INTO entries (
                   entry_index, timestamp, direction, packet_type, kind,
                   procedure_config, procedure_acl, procedure_counter,
                   segment, offset, size, source, level
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            self._entry_row(entry),
        )
        self._tail_entries.append(entry)
        self._index_pending += 1
        if self._index_pending >= INDEX_COMMIT_ENTRIES:
            self._index_conn.commit()
            self._index_pending = 0

    def _iter_index_rows(self, *, after: int | None = None, batch_size: int = 256) -> Iterator[tuple[Any, ...]]:
        """Stream index rows without materializing the complete session index."""
        last_index = -1 if after is None else after
        while True:
            with self._lock:
                rows = self._index_conn.execute(
                    """SELECT entry_index, timestamp, direction, packet_type, kind,
                              procedure_config, procedure_acl, procedure_counter,
                              segment, offset, size, source, level
                         FROM entries
                        WHERE entry_index > ?
                        ORDER BY entry_index
                        LIMIT ?""",
                    (last_index, batch_size),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                yield row
            last_index = rows[-1][0]

    def _drop_old_segments(self) -> None:
        while self._segments and self._total_bytes > self.max_bytes:
            segment_id, file, size = self._segments.pop(0)
            file.close()
            self._segment_files.pop(segment_id, None)
            self._total_bytes -= size
            for level, count in self._index_conn.execute(
                    "SELECT level, COUNT(*) FROM entries WHERE segment = ? GROUP BY level", (segment_id,)):
                if level in self._level_counts:
                    self._level_counts[level] -= count
            self._index_conn.execute("DELETE FROM entries WHERE segment = ?", (segment_id,))
            self._tail_entries = deque((entry for entry in self._tail_entries if entry.segment != segment_id),
                                       maxlen=DEFAULT_HISTORY_TAIL_ENTRIES)
            self.truncated = True
            row = self._index_conn.execute("SELECT timestamp FROM entries ORDER BY entry_index LIMIT 1").fetchone()
            self.first_kept_timestamp = None if row is None else row[0]

    def _write(self, item) -> None:
        index, timestamp, direction, wire, packet_type, kind, procedure_key, level = item
        record_size = _HEADER.size + len(wire)
        with self._lock:
            if not self._segments or self._segments[-1][2] + record_size > self.segment_bytes:
                self._new_segment()
            segment, file, used = self._segments[-1]
            offset = used
            file.seek(offset)
            file.write(_HEADER.pack(index, timestamp, 0 if direction == "received" else 1,
                                    packet_type, 0, len(wire)))
            file.write(wire)
            file.flush()
            self._segments[-1] = (segment, file, used + record_size)
            self._total_bytes += record_size
            self._add_entry(HistoryEntry(index, timestamp, direction, packet_type, kind,
                                         procedure_key, segment, offset, record_size, level=level))
            if level in self._level_counts:
                self._level_counts[level] += 1
            if self.truncated and self.first_kept_timestamp is None:
                self.first_kept_timestamp = timestamp
            self._drop_old_segments()

    def _write_host(self, item) -> None:
        index, timestamp, level, source, text, payload = item
        record_size = _HEADER.size + len(payload)
        with self._lock:
            if not self._segments or self._segments[-1][2] + record_size > self.segment_bytes:
                self._new_segment()
            segment, file, used = self._segments[-1]
            offset = used
            file.seek(offset)
            file.write(_HEADER.pack(index, timestamp, 2, 0, HOST_LEVELS[level], len(payload)))
            file.write(payload)
            file.flush()
            self._segments[-1] = (segment, file, used + record_size)
            self._total_bytes += record_size
            self._add_entry(HistoryEntry(index, timestamp, "host", 0,
                                         "peer" if source == "peer" else "host", None,
                                         segment, offset, record_size, source, level))
            if level in self._level_counts:
                self._level_counts[level] += 1
            if self.truncated and self.first_kept_timestamp is None:
                self.first_kept_timestamp = timestamp
            self._drop_old_segments()

    def _worker(self) -> None:
        try:
            with self._lock:
                self._new_segment()
            self._ready.set()
            while True:
                item = self._queue.get()
                if item is None:
                    return
                kind, value = item
                if kind == "frame":
                    self._write(value)
                elif kind == "host":
                    self._write_host(value)
                elif kind == "flush":
                    with self._lock:
                        self._index_conn.commit()
                        self._index_pending = 0
                    value.set()
        except Exception as error:  # disable history; never raise in the caller's run thread
            self._error = error
            self._ready.set()
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item and item[0] == "flush":
                    item[1].set()

    def read_wire(self, entry: HistoryEntry) -> bytes:
        """Read one raw frame by index."""
        self._check()
        with self._lock:
            file = self._segment_files.get(entry.segment)
            if file is None:
                raise KeyError("History entry has been truncated")
            file.seek(entry.offset)
            header = file.read(_HEADER.size)
            if len(header) != _HEADER.size:
                raise OSError("Short history record")
            _, _, _, _, _, size = _HEADER.unpack(header)
            wire = file.read(size)
            if len(wire) != size:
                raise OSError("Short history frame")
            return wire

    def read(self, entry: HistoryEntry) -> Any:
        if entry.kind in ("host", "peer"):
            payload = self.read_wire(entry)
            source_length = _HOST_PREFIX.unpack_from(payload)[0]
            start = _HOST_PREFIX.size
            source = payload[start:start + source_length].decode("utf-8", errors="replace")
            text = payload[start + source_length:].decode("utf-8", errors="replace")
            return HostMessage(entry.level or "inf", source, text)
        return decode_packet(Frame.from_bytes(self.read_wire(entry)))

    def snapshot(self, *, flush: bool = True, limit: int | None = None) -> tuple[HistoryEntry, ...]:
        if flush:
            self.flush()
        with self._lock:
            if limit == 0:
                return ()
            if limit is None:
                rows = self._index_conn.execute(
                    """SELECT entry_index, timestamp, direction, packet_type, kind,
                              procedure_config, procedure_acl, procedure_counter,
                              segment, offset, size, source, level
                         FROM entries ORDER BY entry_index"""
                ).fetchall()
            else:
                rows = self._index_conn.execute(
                    """SELECT entry_index, timestamp, direction, packet_type, kind,
                              procedure_config, procedure_acl, procedure_counter,
                              segment, offset, size, source, level
                         FROM entries ORDER BY entry_index DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
                rows.reverse()
            return tuple(self._entry_from_row(row) for row in rows)

    @staticmethod
    def _filter_clause(types=(), low: int | None = None, high: int | None = None):
        types = tuple(types)
        params: list[Any] = []
        if types:
            placeholders = ", ".join("?" for _ in types)
            type_clause = f"kind IN ({placeholders})"
            params.extend(types)
        else:
            type_clause = "0"
        clauses = [f"({type_clause} OR level IN ('err', 'wrn'))"]
        if low is not None:
            clauses.append("(procedure_counter IS NULL OR procedure_counter >= ?)")
            params.append(low)
        if high is not None:
            clauses.append("(procedure_counter IS NULL OR procedure_counter <= ?)")
            params.append(high)
        return " WHERE " + " AND ".join(clauses), params

    def entry_count(self, *, types=(), low: int | None = None, high: int | None = None) -> int:
        """Count matching records using the on-disk index."""
        self.flush()
        where, params = self._filter_clause(types, low, high)
        with self._lock:
            return self._index_conn.execute("SELECT COUNT(*) FROM entries" + where, params).fetchone()[0]

    def entries_from(self, position: int, count: int, *, types=(), low: int | None = None,
                     high: int | None = None) -> tuple[HistoryEntry, ...]:
        """Return up to ``count`` filtered records starting at ``position``.

        A browsing view walks every row of a session to lay it out, so reading
        one row per query would scan the index once per row.  A window costs
        one scan for the whole window instead.
        """
        if position < 0 or count <= 0:
            return ()
        where, params = self._filter_clause(types, low, high)
        with self._lock:
            rows = self._index_conn.execute(
                """SELECT entry_index, timestamp, direction, packet_type, kind,
                          procedure_config, procedure_acl, procedure_counter,
                          segment, offset, size, source, level
                     FROM entries""" + where + " ORDER BY entry_index LIMIT ? OFFSET ?",
                [*params, count, position],
            ).fetchall()
        return tuple(self._entry_from_row(row) for row in rows)

    def entry_position(self, entry_index: int, *, types=(), low: int | None = None,
                       high: int | None = None) -> int | None:
        """Return a record's filtered row number without loading the index."""
        where, params = self._filter_clause(types, low, high)
        with self._lock:
            row = self._index_conn.execute(
                "SELECT 1 FROM entries" + where + " AND entry_index = ?", [*params, entry_index]
            ).fetchone()
            if row is None:
                return None
            return self._index_conn.execute(
                "SELECT COUNT(*) FROM entries" + where + " AND entry_index < ?", [*params, entry_index]
            ).fetchone()[0]

    def procedure_summaries(self, *, after: int | None = None, flush: bool = True
                           ) -> tuple[tuple[ProcedureSummary, ...], int, int]:
        """Procedures in the index, in first-appearance order, with their report counts.

        Returns the procedures whose records follow ``after``, the highest
        record index scanned and the lowest one still held.  ``after`` makes
        the call incremental for a growing session: a caller that keeps the
        previous result adds the new counts and drops the procedures the size
        limit has since truncated (those ending before the lowest index).
        """
        if flush:
            self.flush()
        bound = -1 if after is None else int(after)
        initiator = int(PacketType.CS_INITIATOR_SUBEVENT_RESULT)
        reflector = int(PacketType.CS_REFLECTOR_SUBEVENT_RESULT)
        with self._lock:
            rows = self._index_conn.execute(
                """SELECT procedure_config, procedure_acl, procedure_counter,
                          SUM(packet_type = ?), SUM(packet_type = ?),
                          MIN(entry_index), MAX(entry_index)
                     FROM entries
                    WHERE procedure_counter IS NOT NULL AND entry_index > ?
                 GROUP BY procedure_config, procedure_acl, procedure_counter
                 ORDER BY MIN(entry_index)""",
                (initiator, reflector, bound),
            ).fetchall()
            span = self._index_conn.execute(
                "SELECT MIN(entry_index), MAX(entry_index) FROM entries").fetchone()
        lowest = bound + 1 if span is None or span[0] is None else span[0]
        highest = bound if span is None or span[1] is None else max(bound, span[1])
        summaries = tuple(ProcedureSummary((config, acl, counter), int(sent), int(received), first, last)
                          for config, acl, counter, sent, received, first, last in rows)
        return summaries, highest, lowest

    def iter_entries(self, *, flush: bool = True) -> Iterator[HistoryEntry]:
        """Yield the complete index from disk without retaining it in Python memory."""
        if flush:
            self.flush()
        for row in self._iter_index_rows():
            yield self._entry_from_row(row)

    def iter_packets(self):
        for entry in self.iter_entries():
            if entry.kind in ("host", "peer"):
                continue
            yield entry.timestamp, self.read(entry), entry.direction

    def iter_records(self):
        """Yield every frame and host record in original timeline order."""
        for entry in self.iter_entries():
            yield entry.timestamp, self.read(entry), entry.direction

    def save_hdf5(self, path, *, config=None, scenario_json="", metadata=None, log_config=None,
                  description="", cancel=None, write_config=None):
        """Replay this temporary stream into the normal recording format.

        The recorder remains the single HDF5 writer, so saved sessions contain
        the same decoded report tables and raw-frame layout as ordinary runs.
        ``cancel`` is a callable returning true; a cancelled save removes its
        partial output.
        """
        from .recorder import RunRecorder

        recorder = None
        try:
            recorder = RunRecorder(
                path, config=config, scenario_json=scenario_json, metadata=metadata,
                log_config=log_config, source="session", partial=False, clock=lambda: 0.0,
                history_truncated=self.truncated,
                history_first_timestamp=self.first_kept_timestamp,
                description=description, write_config=write_config,
            )
            for timestamp, packet, direction in self.iter_records():
                if cancel is not None and cancel():
                    raise InterruptedError("Session save cancelled")
                if isinstance(packet, HostMessage):
                    recorder.record_host(packet.level, packet.source, packet.text,
                                         received_at=timestamp)
                else:
                    recorder.record(packet, direction="tx" if direction == "sent" else "rx",
                                    received_at=timestamp)
            recorder.close("session saved")
            return path
        except BaseException:
            if recorder is not None:
                try:
                    recorder.close("session save failed", discard=True)
                except Exception:
                    pass
            raise

    def close(self, *, discard: bool = False) -> None:
        if self._closed:
            self._check()
            return
        self._closed = True
        try:
            self.flush()
        finally:
            if self._thread.is_alive():
                try:
                    self._queue.put(None, timeout=10)
                except queue.Full:
                    pass
                self._thread.join(timeout=10)
            with self._lock:
                for _, file, _ in self._segments:
                    file.close()
                self._segments.clear()
                self._segment_files.clear()
                if discard:
                    self._tail_entries.clear()
                self._index_conn.close()
                try:
                    os.unlink(self._index_path)
                except FileNotFoundError:
                    pass
            self._check()

    def __del__(self):
        # ClientSession retains history until the application closes, but
        # tests and short-lived sessions may be collected without an explicit
        # close.  Temporary files must not survive that collection.
        try:
            if not getattr(self, "_closed", True):
                self.close(discard=True)
        except Exception:
            pass
