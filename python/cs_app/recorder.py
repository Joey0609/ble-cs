"""One HDF5 file per run, with a worker-owned file and lossless raw replay."""
from __future__ import annotations
from dataclasses import fields
from datetime import datetime, timezone
import io
from pathlib import Path
import queue
import threading
import time
import h5py
import numpy as np
from .protocol.frame import Frame
from .protocol.packets import (decode_packet, CsSubeventResultPacket, CsReflectorSubeventResultPacket,
                                LogMessagePacket, CommandResponsePacket, ClientStatePacket, RasDataLostPacket,
                                CsFaeTablePacket, RadioTestStatsPacket, CsProceduresCompletePacket, CsPeerDataPacket,
                                ConnectionParametersPacket,
                                LOG_CONSOLE_LEVEL_DEFAULT, LOG_PROTOCOL_LEVEL_DEFAULT, T_PM_DEFAULT_US)
from .fae import FAE_CHANNELS
from .session_history import HostMessage, HOST_LEVELS, normalize_host_level

STR = h5py.string_dtype("utf-8")
BYTES = h5py.vlen_dtype(np.dtype("u1"))
BASE = [("rx_index", "<u8"), ("t_host", "<f8")]


def values(packet):
    return {f.name: getattr(packet, f.name) for f in fields(packet) if f.name not in ("steps", "tones")}


def dtype_for(data):
    result = []
    for key, value in data.items():
        if isinstance(value, str):
            result.append((key, STR))
        elif isinstance(value, float):
            result.append((key, "<f8"))
        elif isinstance(value, bytes):
            result.append((key, "u1", (len(value),)))
        elif isinstance(value, (tuple, list)):
            result.append((key, "<i8", (len(value),)))
        else:
            result.append((key, "<i8"))
    return np.dtype(result)


def append(file, path, data, dtype=None):
    if path not in file:
        file.create_dataset(path, (0,), maxshape=(None,), chunks=True, dtype=dtype or dtype_for(data))
    ds = file[path]
    row = np.zeros(1, dtype=ds.dtype)
    for key, value in data.items():
        row[key][0] = np.frombuffer(value, dtype="u1") if isinstance(value, bytes) and ds.dtype[key].subdtype else value
    index = len(ds)
    ds.resize((index + 1,))
    ds[index] = row[0]
    return index


class RunRecorder:
    def __init__(self, path, *, config=None, scenario_json="", metadata=None, context=(),
                 log_config=None,
                 partial=False, clock=time.monotonic, queue_size=4096, source="run",
                 history_truncated=False, history_first_timestamp=None, description="",
                 write_config=None):
        self.path = Path(path)
        self.clock, self.started = clock, clock()
        self.config, self.scenario_json = config, scenario_json
        self.mode = int(getattr(config, "mode", (metadata or {}).get("operation_mode", 3)))
        levels = log_config or {}
        if config is not None and getattr(config, "log", None) is not None:
            levels = {"console": config.log.console_level, "host": config.log.protocol_level}
        self.log_config = (int(levels.get("console", LOG_CONSOLE_LEVEL_DEFAULT)),
                           int(levels.get("host", LOG_PROTOCOL_LEVEL_DEFAULT)))
        self.metadata = dict(metadata or {})
        self.context = tuple(context)
        self.partial = partial
        self.source = str(source)
        self.history_truncated = bool(history_truncated)
        self.history_first_timestamp = history_first_timestamp
        self.description = str(description)
        self.write_config = config is not None if write_config is None else bool(write_config)
        self.queue = queue.Queue(queue_size)
        self.ready = threading.Event()
        self.error = None
        self.closed = False
        self.index = 0
        self.created_file = False
        self.thread = threading.Thread(target=self._worker, daemon=True, name="cs-hdf5-writer")
        self.thread.start()
        self.ready.wait()
        self._check()

    def _check(self):
        if self.error:
            raise OSError(f"Recording failed: {self.error}") from self.error

    def record(self, packet, *, direction="rx", received_at=None):
        """Queue one frame. received_at is a clock() value from the transport's reader thread;
        frames read before the run started are stamped 0."""
        self._check()
        if self.closed:
            raise ValueError("Recording is closed")
        if direction not in ("rx", "tx"):
            raise ValueError("Direction must be rx or tx")
        # Serialize now so queued data is immutable and exactly the recorded frame.
        wire = packet.to_bytes()
        now = self.clock() if received_at is None else received_at
        item = (self.index, max(0., now - self.started), direction, wire)
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            raise OSError("Recording queue full; stop the run to avoid silent data loss")
        self.index += 1

    def record_host(self, level, source, text, *, received_at=None):
        """Queue a host/peer-console message for the `/host_log` table."""
        self._check()
        if self.closed:
            raise ValueError("Recording is closed")
        level_name = normalize_host_level(level)
        now = self.clock() if received_at is None else received_at
        item = ("host", self.index, max(0., now - self.started), level_name,
                str(source), str(text))
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            raise OSError("Recording queue full; stop the run to avoid silent data loss")
        self.index += 1

    def close(self, reason="STOP confirmed", *, discard=False):
        if self.closed:
            self._check()
            return
        self.closed = True
        while self.thread.is_alive():
            try:
                self.queue.put(("close", reason), timeout=.1)
                break
            except queue.Full:
                self._check()
        self.thread.join()
        if discard and self.created_file:
            self.path.unlink(missing_ok=True)
        self._check()

    def _worker(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with h5py.File(self.path, "x") as file:
                self.created_file = True
                file.attrs.update(format_version=1, created=datetime.now(timezone.utc).isoformat(),
                                  app_version="0.1.0", source=self.source, partial=self.partial,
                                  history_truncated=self.history_truncated,
                                  close_reason="unclosed", description=self.description,
                                  description_updated="",
                                  config_crc32=self.config.crc32() if self.config is not None else int(self.metadata.get("config_crc32", 0)),
                                  operation_mode=int(self.config.mode) if self.config is not None else int(self.metadata.get("operation_mode", 3)),
                                  **{k: v for k, v in self.metadata.items() if k not in
                                     ("config_crc32", "operation_mode", "partial", "close_reason", "format_version", "created", "app_version")})
                if self.history_first_timestamp is not None:
                    file.attrs["history_first_timestamp"] = float(self.history_first_timestamp)
                if self.write_config:
                    file.create_dataset("config/operation_mode", data=int(self.config.mode) if self.config is not None else int(self.metadata.get("operation_mode", 3)))
                    file.create_dataset("config/peer_data", data=int(getattr(self.config, "peer_data", 0)))
                    file.create_dataset("config/t_pm", data=int(getattr(self.config, "t_pm", T_PM_DEFAULT_US)))
                    file.create_dataset("config/log", data=np.asarray(self.log_config, dtype="u1"))
                    file["config/log"].attrs.update(console_level=self.log_config[0], host_level=self.log_config[1])
                    if self.config is not None:
                        cfg = self.config.config
                        path = "config/radio_test_config" if type(cfg).__name__ == "RadioTxTestConfigPacket" else "config/cs_config"
                        append(file, path, values(cfg))
                        file[path].attrs["packet_type"] = int(cfg.PACKET_TYPE)
                        if self.config.device_name is not None:
                            file.create_dataset("config/device_name", data=self.config.device_name.text(), dtype=STR)
                    packets = self.config.packets() if self.config is not None else []
                    payloads = file.create_dataset("config/payloads", (len(packets),), dtype=BYTES)
                    for i, packet in enumerate(packets):
                        payloads[i] = np.frombuffer(packet.to_frame().payload, dtype="u1")
                    file.create_dataset("config/peripheral_patterns", data=np.array(
                        self.config.patterns.names() if self.config is not None and self.config.patterns else [], dtype=STR))
                    file.create_dataset("config/planner_scenario", data=self.scenario_json, dtype=STR)
                for group in ("context", "raw", "reports", "results"):
                    file.require_group(group)
                file.create_dataset("raw/frames", (0,), maxshape=(None,), chunks=True,
                                    dtype=np.dtype(BASE + [("direction", "S2"), ("packet_type", "<u2"), ("data", BYTES)]))
                for i, packet in enumerate(self.context):
                    self._typed(file, packet, i, 0., prefix="context/")
                file.flush()
                self.ready.set()
                last_flush = time.monotonic()
                link_number = int(self.metadata.get("link_number", 0))
                while True:
                    try:
                        item = self.queue.get(timeout=max(.01, 1 - (time.monotonic() - last_flush)))
                    except queue.Empty:
                        file.flush()
                        last_flush = time.monotonic()
                        continue
                    if item[0] == "close":
                        file.attrs["close_reason"] = item[1]
                        file.flush()
                        break
                    if item[0] == "host":
                        _, index, timestamp, level, source, text = item
                        append(file, "host_log", dict(rx_index=index, t_host=timestamp,
                                                       level=HOST_LEVELS[level], source=source,
                                                       text=text),
                               np.dtype(BASE + [("level", "u1"), ("source", STR), ("text", STR)]))
                        if time.monotonic() - last_flush >= 1:
                            file.flush()
                            last_flush = time.monotonic()
                        continue
                    index, timestamp, direction, wire = item
                    frame = Frame.from_bytes(wire)
                    packet = decode_packet(frame)
                    append(file, "raw/frames", dict(rx_index=index, t_host=timestamp, direction=direction.encode(),
                                                   packet_type=int(frame.packet_type), data=np.frombuffer(wire, dtype="u1")))
                    if direction == "rx":
                        if isinstance(packet, ClientStatePacket) and packet.state == 4:
                            link_number += 1
                        self._typed(file, packet, index, timestamp, link_number=link_number)
                    if time.monotonic() - last_flush >= 1:
                        file.flush()
                        last_flush = time.monotonic()
        except Exception as error:
            self.error = error
        finally:
            self.ready.set()

    def _typed(self, file, packet, index, timestamp, *, prefix="", link_number=0):
        base = dict(rx_index=index, t_host=timestamp)
        name = type(packet).__name__
        report = {"CsCapabilitiesPacket": "capabilities", "CsConfigurationPacket": "configuration",
                  "CsProcedureEnableCompletePacket": "procedure_enable"}.get(name)
        if report:
            append(file, prefix + ("" if prefix else "reports/") + report, {**base, **values(packet)})
        elif isinstance(packet, RadioTestStatsPacket):
            append(file, "radio_test/stats", {**base, **values(packet)},
                   np.dtype(BASE + [("packets_received", "<u4"), ("crc_errors", "<u4"),
                                    ("rssi_dbm", "i1"), ("channel", "u1")]))
        elif isinstance(packet, CsFaeTablePacket):
            path = prefix + "fae"
            append(file, path, {**base, "link_number": link_number, **values(packet)},
                   np.dtype(BASE + [("link_number", "<u4"), ("hci_status", "u1"),
                                    ("lsb_denominator", "u1"), ("entries", "i1", (72,))]))
            file[path].attrs["channels"] = FAE_CHANNELS
        elif isinstance(packet, LogMessagePacket):
            append(file, "log", {**base, "text": packet.message.decode("utf-8", errors="replace")})
        elif isinstance(packet, CsPeerDataPacket):
            append(file, "reports/peer_data", {**base, "peer_data": packet.peer_data})
        elif isinstance(packet, ConnectionParametersPacket):
            append(file, "reports/connection_parameters", {**base, **values(packet)})
        elif isinstance(packet, (CommandResponsePacket, ClientStatePacket, RasDataLostPacket,
                                 CsProceduresCompletePacket)):
            row = dict(kind=name, request_type=-1, status=-1, reason=0, error=0, state=-1,
                       config_crc32=0, ranging_counter=-1, operation_mode=-1, hci_status=0,
                       procedures_completed=-1)
            row.update(values(packet))
            append(file, "events", {**base, **row})
        elif isinstance(packet, CsSubeventResultPacket):
            step_start = len(file["results/steps"]) if "results/steps" in file else 0
            reflector = isinstance(packet, CsReflectorSubeventResultPacket)
            subevent = append(file, "results/subevents", {**base, "role": int(reflector),
                                  "source": "RAS" if reflector and self.mode == 0 else "local HCI",
                              **values(packet), "num_steps": len(packet.steps), "step_start": step_start})
            for step_index, step in enumerate(packet.steps):
                tone_start = len(file["results/tones"]) if "results/tones" in file else 0
                step_row = append(file, "results/steps", {"subevent_row": subevent, "step_index": step_index,
                                  **values(step), "tone_start": tone_start, "num_tones": len(step.tones)})
                for tone in step.tones:
                    append(file, "results/tones", {"step_row": step_row, **values(tone)})


def load(path_or_bytes, *, include_tx=False, times=False, with_direction=False,
         include_host=False):
    """Replay received packets in arrival order (optionally also host commands).

    With ``times``, return (host arrival time, packet) pairs. With
    ``with_direction``, include a third ``sent``/``received`` value.
    """
    source = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, bytes) else path_or_bytes
    with h5py.File(source, "r") as file:
        if file.attrs.get("format_version") != 1:
            raise ValueError("Unsupported recording version")
        packets = [(float(row["t_host"]), decode_packet(Frame.from_bytes(bytes(row["data"]))),
                    "sent" if row["direction"] == b"tx" else "received")
                   for row in file["raw/frames"] if include_tx or row["direction"] == b"rx"]
        if include_host and "host_log" in file:
            packets.extend((float(row["t_host"]), HostMessage(normalize_host_level(int(row["level"])),
                                                               _value_string(row["source"]),
                                                               _value_string(row["text"])), "host")
                           for row in file["host_log"])
        packets.sort(key=lambda item: item[0])
        if not times:
            return [packet for _, packet, _ in packets]
        return packets if with_direction else [(timestamp, packet) for timestamp, packet, _ in packets]


def _value_string(value):
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def read_description(path):
    """Return the saved run/session description, or an empty string."""
    with h5py.File(path, "r") as file:
        value = file.attrs.get("description", "")
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def update_description(path, description):
    """Update a closed recording's description without rewriting its frames."""
    with h5py.File(path, "a") as file:
        file.attrs["description"] = str(description)
        file.attrs["description_updated"] = datetime.now(timezone.utc).isoformat()
