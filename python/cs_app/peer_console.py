"""Line-oriented reader for an optional peer-device console."""

from __future__ import annotations

import re


# A Zephyr or app_log console line: an optional "[00:00:01.234,567]" or "[1.234]" timestamp,
# then the "<err>"/"<wrn>"/"<inf>"/"<dbg>" tag (app_log_console.c prints "[%u.%03u] <lvl> ...").
_LEVEL = re.compile(r"^(\s*(?:\[[^\]]*\]\s*)?)<(err|wrn|inf|dbg)>\s?(.*)$", re.IGNORECASE)
_HEXDUMP = re.compile(
    r"^\s*(?:[0-9a-f]{4,8}:\s*)?(?:[0-9a-f]{2}(?:\s+|$)){4,}(?:\s+.*)?$",
    re.IGNORECASE,
)


class PeerConsoleReader:
    """Split serial bytes into UTF-8 lines and extract firmware log levels."""

    def __init__(self, on_line):
        self.on_line = on_line
        self.buffer = bytearray()
        self.pending = None

    @staticmethod
    def _parse(text, timestamp):
        match = _LEVEL.match(text)
        if match:
            # The device's own timestamp stays in the text; only the level tag is taken out.
            prefix = match.group(1).strip()
            return match.group(2).lower(), f"{prefix} {match.group(3)}" if prefix else match.group(3), timestamp, False
        return "inf", text, timestamp, bool(_HEXDUMP.match(text))

    def _push(self, text, timestamp):
        level, message, line_time, continuation = self._parse(text, timestamp)
        if self.pending is not None and continuation:
            old_level, old_message, old_time = self.pending
            self.pending = old_level, f"{old_message.strip()} {message.strip()}".strip(), old_time
            return
        if self.pending is not None:
            self.on_line(*self.pending)
        self.pending = level, message, line_time

    def feed(self, data, received_at=None):
        self.buffer.extend(data)
        while b"\n" in self.buffer:
            raw, _, remainder = self.buffer.partition(b"\n")
            self.buffer[:] = remainder
            text = raw.rstrip(b"\r").decode("utf-8", errors="replace")
            self._push(text, received_at)

    def flush(self, received_at=None):
        if not self.buffer:
            if self.pending is not None:
                self.on_line(*self.pending)
                self.pending = None
            return
        text = bytes(self.buffer).rstrip(b"\r").decode("utf-8", errors="replace")
        self.buffer.clear()
        self._push(text, received_at)
        if self.pending is not None:
            self.on_line(*self.pending)
            self.pending = None
