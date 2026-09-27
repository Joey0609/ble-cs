"""Configuration comparison for the host UI; no transport or wire definitions."""
from dataclasses import asdict
from .protocol.config import ClientConfig


def sync_state(host: ClientConfig | None, valid: bool, crc: int) -> str:
    if host is None:
        return "no host configuration"
    if not valid:
        return "client empty"
    return "in sync" if host.crc32() == crc else "modified / mismatch"


def field_diff(host: ClientConfig, client: ClientConfig) -> dict:
    def flatten(config):
        result = {"mode": int(config.mode), **asdict(config.config)}
        result["patterns"] = None if config.patterns is None else config.patterns.names()
        result["device_name"] = config.device_name.text() if config.device_name else None
        result["peer_data"] = config.peer_data
        result["t_pm"] = config.t_pm
        result["log"] = None if config.log is None else {
            "console": config.log.console_level,
            "host": config.log.protocol_level,
        }
        return result
    a, b = flatten(host), flatten(client)
    return {key: (a.get(key), b.get(key)) for key in sorted(a.keys() | b.keys()) if a.get(key) != b.get(key)}
