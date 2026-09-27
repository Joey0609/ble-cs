"""Shared host-side representation of the two client log consumers."""

from __future__ import annotations

from .protocol.packets import (
    LOG_CONSOLE_LEVEL_DEFAULT,
    LOG_PROTOCOL_LEVEL_DEFAULT,
    LogConfigPacket,
    LogLevel,
)

LEVEL_LABELS = {
    int(LogLevel.OFF): "Off",
    int(LogLevel.ERROR): "Error",
    int(LogLevel.WARNING): "Warning",
    int(LogLevel.INFO): "Info",
    int(LogLevel.DEBUG): "Debug",
}
DEFAULT_LOG = {
    "console": int(LOG_CONSOLE_LEVEL_DEFAULT),
    "host": int(LOG_PROTOCOL_LEVEL_DEFAULT),
}


def normalize_log(value=None) -> dict[str, int]:
    """Return ``{"console": level, "host": level}`` from plan/UI/wire forms."""
    if value is None:
        return dict(DEFAULT_LOG)
    if isinstance(value, LogConfigPacket):
        return {"console": value.console_level, "host": value.protocol_level}
    if isinstance(value, (tuple, list)) and len(value) == 2:
        value = {"console": value[0], "host": value[1]}
    if not isinstance(value, dict):
        raise ValueError("log must contain console and host levels")
    console = value.get("console", value.get("console_level", DEFAULT_LOG["console"]))
    host = value.get("host", value.get("protocol", value.get("protocol_level", DEFAULT_LOG["host"])))
    if type(console) is not int or type(host) is not int or not 0 <= console <= int(LogLevel.DEBUG) \
            or not 0 <= host <= int(LogLevel.DEBUG):
        raise ValueError("log levels must be integers from 0 (off) through 4 (debug)")
    return {"console": console, "host": host}


def is_default_log(value=None) -> bool:
    levels = normalize_log(value)
    return levels == DEFAULT_LOG


def log_packet(value=None) -> LogConfigPacket | None:
    """Return the optional wire packet; defaults are represented by omission."""
    levels = normalize_log(value)
    if levels == DEFAULT_LOG:
        return None
    return LogConfigPacket(levels["console"], levels["host"])

