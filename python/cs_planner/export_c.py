"""Planner files and hostless C configuration export (standard library only).

Produces hostless C configuration for
``common/libs/cs_generated_config/cs_generated_config.h``. The host configuration
packets and their configuration CRC are encoded here from the protocol layout
(``cs_protocol_packets.h``), so this package does not depend on ``cs_app``.

The standalone planner deliberately leaves the reflector-data, preferred-T_PM
and log-level client settings to the firmware. The connected ``cs-app`` planner
remains the place where those settings are exposed and serialized.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import struct
import zlib

from .model import NEUTRAL_MAIN_MODE_STEPS, dumps, has_sub_mode, loads, validate

MARKER = "CS_PLANNER_SCENARIO_JSON"
ROLE_NAMES = ("initiator", "reflector")  # index = configuration.role / operation mode
# Host settings saved under "host_settings" in planner JSON; firmware defaults
# (common/libs/cs_utils/cs_config.c). The reflector-data, preferred-T_PM and log
# settings are intentionally not part of the standalone planner.
HOST_DEFAULTS = {
    "gap_role": 0,  # central
    "cs_sync_antenna_selection": 0xFE,  # repetitive
    "max_tx_power": 20,
    "phy": 1,  # LE 1M
    "tx_power_delta": -128,  # no recommendation
    "preferred_peer_antenna": 1,
    "snr_control_initiator": 0xFF,  # not used
    "snr_control_reflector": 0xFF,
    "creation_context": 1,  # local and remote
}

STANDALONE_IGNORED_SETTINGS = frozenset(("peer_data", "t_pm", "log"))

# Wire layout of the configuration packets (payload only, little endian).
SET_OPERATION_MODE, SET_CS_INITIATOR_CONFIG, SET_CS_REFLECTOR_CONFIG = 0x0100, 0x0101, 0x0102
REFLECTOR_FIELDS = (
    "gap_role", "config_id", "connection_interval_min", "connection_interval_max", "connection_latency",
    "connection_timeout", "cs_sync_antenna_selection", "max_tx_power", "max_procedure_len",
    "min_procedure_interval", "max_procedure_interval", "max_procedure_count", "min_subevent_len",
    "max_subevent_len", "tone_antenna_config_selection", "phy", "tx_power_delta", "preferred_peer_antenna",
    "snr_control_initiator", "snr_control_reflector")
CREATION_FIELDS = (
    "creation_mode", "creation_min_main_mode_steps", "creation_max_main_mode_steps",
    "creation_main_mode_repetition", "creation_mode_0_steps", "creation_rtt_type", "creation_cs_sync_phy",
    "creation_channel_map", "creation_channel_map_repetition", "creation_channel_selection_type",
    "creation_ch3c_shape", "creation_ch3c_jump", "creation_cs_enhancements_1")
PACKETS = {  # role -> (packet type, fields, payload struct)
    "reflector": (SET_CS_REFLECTOR_CONFIG, REFLECTOR_FIELDS, struct.Struct("<BBHHHHBbHHHHIIBBbBBB")),
    "initiator": (SET_CS_INITIATOR_CONFIG, REFLECTOR_FIELDS + CREATION_FIELDS + ("creation_context",),
                  struct.Struct("<BBHHHHBbHHHHIIBBbBBB7B10s6B")),
}
PATTERNS = struct.Struct("<B8s256s")
DEVICE_NAME = struct.Struct("<B32s")
LOG_CONFIG = struct.Struct("<BB")
T_PM_DEFAULT_US = 10  # cs_protocol: the preference without a SET_T_PM frame
FRAME_HEADER, FRAME_FOOTER = struct.Struct("<HHH"), struct.Struct("<IH")


def standalone_host_settings(host=None):
    """Return standalone settings, dropping app-only runtime overrides.

    Shared planner files may contain ``peer_data``, ``t_pm`` or ``log``.
    They are accepted on load for compatibility but are not displayed, saved,
    exported, or included in the standalone configuration CRC.
    """
    return {key: value for key, value in (host or {}).items()
            if key not in STANDALONE_IGNORED_SETTINGS}


def log_values(value=None):
    """Normalize optional log levels for protocol CRC-vector calculations."""
    value = {"console": 3, "host": 2} if value is None else value
    if isinstance(value, (tuple, list)) and len(value) == 2:
        value = {"console": value[0], "host": value[1]}
    if not isinstance(value, dict):
        raise ValueError("log must contain console and host levels")
    console = value.get("console", value.get("console_level", 3))
    host = value.get("host", value.get("protocol", value.get("protocol_level", 2)))
    if type(console) is not int or type(host) is not int or not 0 <= console <= 4 or not 0 <= host <= 4:
        raise ValueError("log levels must be integers from 0 (off) through 4 (debug)")
    return {"console": console, "host": host}


def load_document(text):
    """Return (scenario, host settings) from planner JSON or an exported C source."""
    if MARKER in text:
        text = text.split(MARKER + "\n", 1)[1].split("\n*/", 1)[0]
    try:
        host = json.loads(text).get("host_settings", {})
    except (ValueError, AttributeError) as error:
        raise ValueError(f"Not a planner file: {error}") from error
    if not isinstance(host, dict):
        raise ValueError("host_settings must be an object")
    return loads(text), {**HOST_DEFAULTS, **standalone_host_settings(host)}


def document(scenario, host=None):
    """Planner JSON: the scenario plus every host-only setting, so a file is a complete configuration."""
    return dumps(scenario, {"host_settings": {**HOST_DEFAULTS, "peripheral_patterns": [],
                                                **standalone_host_settings(host)}})


def validate_patterns(patterns) -> list[str]:
    if not isinstance(patterns, (list, tuple)) or not 1 <= len(patterns) <= 8:
        return ["Supply 1–8 peripheral name prefixes"]
    errors = []
    for i, name in enumerate(patterns):
        try:
            if not isinstance(name, str) or not 1 <= len(name.encode("utf-8")) <= 32 or "\0" in name:
                errors.append(f"Pattern {i + 1} must be 1–32 UTF-8 bytes without NUL")
        except UnicodeEncodeError:
            errors.append(f"Pattern {i + 1} is not UTF-8")
    return errors


def validate_device_name(name) -> list[str]:
    """Errors for a Bluetooth device name; empty means the firmware default."""
    try:
        data = name.encode("utf-8")
    except (AttributeError, UnicodeEncodeError):
        return ["Bluetooth name must be valid UTF-8 text"]
    return [] if len(data) <= 32 and b"\0" not in data else ["Bluetooth name must be 1–32 UTF-8 bytes without NUL"]


# (initiator antennas, reflector antennas) per tone_antenna_config_selection.
TONE_ANTENNA_COUNTS = ((1, 1), (2, 1), (3, 1), (4, 1), (1, 2), (1, 3), (1, 4), (2, 2))


def validate_preferred_peer_antenna(values, role) -> list[str]:
    """The preferred peer antenna mask of config_values(), as cs_*_config_set_procedure() checks it.

    Peer antennas 1–4 (bits 0–3), with at least as many bits as the peer's side of the
    tone antenna configuration: B for an initiator, A for a reflector.
    """
    mask, selection = values["preferred_peer_antenna"], values["tone_antenna_config_selection"]
    if not 1 <= mask <= 0x0F:
        return [f"Preferred peer antenna 0x{mask:02x} must name peer antennas 1–4 (bit mask 1–15)"]
    a, b = TONE_ANTENNA_COUNTS[selection]
    needed, bits = (b if role == "initiator" else a), bin(mask).count("1")
    if bits < needed:
        return [f"Antenna configuration A{a}:B{b} uses {needed} {'reflector' if role == 'initiator' else 'initiator'} "
                f"antennas; preferred peer antenna 0x{mask:02x} names {bits}. Set at least {needed} bits, "
                f"for example {(1 << needed) - 1}"]
    return []


def _decode_config(wire):
    """Fields of a complete initiator/reflector configuration frame (hex), or None for other packets."""
    data = bytes.fromhex(wire)
    _, size, packet_type = FRAME_HEADER.unpack_from(data)
    payload = data[FRAME_HEADER.size:size - FRAME_FOOTER.size]
    for role, (kind, names, layout) in PACKETS.items():
        if kind == packet_type and len(payload) == layout.size:
            return role, dict(zip(names, layout.unpack(payload)))
    return None, {}


def config_values(scenario, host=None, role="initiator") -> dict:
    """Host configuration packet fields, in wire order, that request this scenario.

    Loaded requests keep their min/max ranges until the selected value is edited;
    otherwise min = max. Raises ValueError when a value does not fit its field.
    """
    host = {**HOST_DEFAULTS, **standalone_host_settings(host)}
    a, p, c = scenario.connection, scenario.procedure, scenario.configuration
    values = dict(
        gap_role=host["gap_role"], config_id=c.id,
        connection_interval_min=a.interval_min, connection_interval_max=a.interval_max,
        connection_latency=a.latency, connection_timeout=a.timeout,
        cs_sync_antenna_selection=host["cs_sync_antenna_selection"], max_tx_power=host["max_tx_power"],
        max_procedure_len=p.max_procedure_len,
        min_procedure_interval=p.procedure_interval, max_procedure_interval=p.procedure_interval,
        max_procedure_count=p.procedure_count,
        min_subevent_len=p.subevent_len, max_subevent_len=p.subevent_len,
        tone_antenna_config_selection=p.tone_antenna_config_selection, phy=host["phy"],
        tx_power_delta=host["tx_power_delta"], preferred_peer_antenna=host["preferred_peer_antenna"],
        snr_control_initiator=host["snr_control_initiator"], snr_control_reflector=host["snr_control_reflector"])
    for name, selected in (("procedure_interval", p.procedure_interval), ("subevent_len", p.subevent_len)):
        low, high = host.get("min_" + name, selected), host.get("max_" + name, selected)
        if host.get("_selected_" + name) == selected and low <= selected <= high:
            values["min_" + name], values["max_" + name] = low, high
    if role == "initiator":
        values.update({name: getattr(c, name.removeprefix("creation_")) for name in CREATION_FIELDS},
                      creation_context=host["creation_context"])
        if not has_sub_mode(c.mode):
            # See cs_app bridge.config_packet: the main-mode bounds mean nothing without a
            # sub-mode, so they are not carried from whatever the scenario last held.
            values["creation_min_main_mode_steps"] = NEUTRAL_MAIN_MODE_STEPS
            values["creation_max_main_mode_steps"] = NEUTRAL_MAIN_MODE_STEPS
    elif role != "reflector":
        raise ValueError(f"No CS configuration packet for role {role!r}")
    # cs-app keeps controller-negotiated values that were not edited as originally requested.
    if host.get("_requested_wire") and host.get("_negotiated_wire"):
        requested_role, requested = _decode_config(host["_requested_wire"])
        _, reference = _decode_config(host["_negotiated_wire"])
        if requested_role == role:
            values.update({name: requested[name] for name in values if values[name] == reference.get(name)})
    _payload(role, values)  # field widths
    return values


def _payload(role, values) -> bytes:
    _, names, layout = PACKETS[role]
    try:
        return layout.pack(*(values[name] for name in names))
    except struct.error as error:
        raise ValueError(f"CS {role} configuration field out of range: {error}") from error


def config_crc32(role, values, patterns=(), device_name="", peer_data=0, t_pm=T_PM_DEFAULT_US,
                 log=None, log_config=None) -> int:
    """Compute a configuration CRC, including optional protocol payloads when requested.

    ``generate()`` deliberately calls this without ``peer_data``, a preferred
    T_PM or log levels, so standalone exports leave those settings
    firmware-owned. The optional arguments remain available for shared protocol
    CRC-vector tests.
    """
    if log is not None and log_config is not None:
        raise ValueError("specify either log or log_config, not both")
    levels = log_values(log if log is not None else log_config)
    data = struct.pack("<B", ROLE_NAMES.index(role)) + _payload(role, values)
    if patterns:
        lengths, slots = bytearray(8), bytearray(8 * 32)
        for index, text in enumerate(patterns):
            encoded = text.encode("utf-8")
            lengths[index] = len(encoded)
            slots[index * 32:index * 32 + len(encoded)] = encoded
        data += PATTERNS.pack(len(patterns), bytes(lengths), bytes(slots))
    if device_name:
        encoded = device_name.encode("utf-8")
        data += DEVICE_NAME.pack(len(encoded), encoded.ljust(32, b"\0"))
    if peer_data:
        data += struct.pack("<B", peer_data)
    if t_pm != T_PM_DEFAULT_US:
        data += struct.pack("<B", t_pm)
    if levels != {"console": 3, "host": 2}:
        data += LOG_CONFIG.pack(levels["console"], levels["host"])
    return zlib.crc32(data) & 0xFFFFFFFF


def _value(name, value):
    constants = {
        "cs_sync_antenna_selection": {1: "CS_CONFIG_SYNC_ANTENNA_ONE", 2: "CS_CONFIG_SYNC_ANTENNA_TWO",
                                      3: "CS_CONFIG_SYNC_ANTENNA_THREE", 4: "CS_CONFIG_SYNC_ANTENNA_FOUR",
                                      254: "CS_CONFIG_SYNC_ANTENNA_REPETITIVE", 255: "CS_CONFIG_SYNC_ANTENNA_NO_RECOMMENDATION"},
        "tone_antenna_config_selection": dict(enumerate("CS_CONFIG_TONE_ANTENNA_" + x for x in
                                                        ("A1_B1", "A2_B1", "A3_B1", "A4_B1", "A1_B2", "A1_B3", "A1_B4", "A2_B2"))),
        "phy": {1: "CS_CONFIG_PROCEDURE_PHY_1M", 2: "CS_CONFIG_PROCEDURE_PHY_2M",
                3: "CS_CONFIG_PROCEDURE_PHY_CODED_S8", 4: "CS_CONFIG_PROCEDURE_PHY_CODED_S2"},
        "tx_power_delta": {-128: "CS_CONFIG_TX_POWER_DELTA_NONE"},
        "context": {0: "CS_CONFIG_CREATION_CONTEXT_LOCAL_ONLY", 1: "CS_CONFIG_CREATION_CONTEXT_LOCAL_AND_REMOTE"},
    }
    if name.startswith("snr_control"):
        return "CS_CONFIG_SNR_CONTROL_NOT_USED" if value == 255 else f"CS_CONFIG_SNR_CONTROL_{18 + value * 3}DB"
    if isinstance(value, bytes):
        return "{ " + ", ".join(f"0x{b:02x}" for b in value) + " }"
    return constants.get(name, {}).get(value, str(value))


def _c_string(text):
    # Octal escapes preserve UTF-8 bytes and cannot swallow a following hex digit.
    return '"' + "".join(f"\\{b:03o}" for b in text.encode("utf-8")) + '"'


def generate(scenario, host=None, *, role="reflector", name="cs_generated_config"):
    """Return {role: C source} for "initiator", "reflector" or "both". Writes no files."""
    host = {**HOST_DEFAULTS, **standalone_host_settings(host)}
    errors = validate(scenario)
    if errors:
        raise ValueError("\n".join(errors))
    if role not in ("initiator", "reflector", "both"):
        raise ValueError("Role must be initiator, reflector or both")
    roles = ROLE_NAMES if role == "both" else (role,)
    output = {}
    for selected in roles:
        settings = dict(host)
        if role == "both":
            settings["gap_role"] = 0 if selected == "initiator" else 1
        patterns = settings.get("peripheral_patterns", []) if settings["gap_role"] == 0 else []
        if settings["gap_role"] == 0:
            errors = validate_patterns(patterns)
            if errors:
                raise ValueError("\n".join(errors))
        device_name = settings.get("device_name") or ""
        errors = validate_device_name(device_name)
        if errors:
            raise ValueError("\n".join(errors))
        # The embedded plan re-imports with the operation mode of this file.
        embedded = replace(scenario, configuration=replace(scenario.configuration, role=ROLE_NAMES.index(selected)))
        packet = config_values(scenario, settings, selected)
        errors = validate_preferred_peer_antenna(packet, selected)
        if errors:
            # The generated record would fail cs_*_config_set_procedure() at boot.
            raise ValueError(f"CS {selected}: " + "\n".join(errors))
        crc = config_crc32(selected, packet, patterns, device_name)
        prefix = f"cs_{selected}_config"
        lines = ["/* Generated by cs_planner; " + datetime.now(timezone.utc).isoformat() + " */",
                 "/* Configuration name: " + name.replace("*/", "* /").replace("\n", " ") + " */",
                 f"/* Operation mode: CS {selected}; IPT: " +
                 ("requested" if scenario.configuration.cs_enhancements_1 & 1 else "off") +
                 ("" if selected == "initiator" else " (set by the initiator)") + " */",
                 "/* Reflector data, preferred T_PM and client log levels: left to firmware defaults/overrides. */",
                 '#include <cs_generated_config/cs_generated_config.h>', '#include <cs_utils/cs_config.h>', "",
                 f"const uint32_t cs_generated_config_crc32_{selected} = 0x{crc:08x}U;", "",
                 f"int cs_generated_config_{selected}(struct cs_{selected}_config *config) {{",
                 f"    int err = {prefix}_get_default(config);", "    if (err) return err;"]
        groups = {
            "connection": {x.removeprefix("connection_"): packet[x] for x in
                           ("connection_interval_min", "connection_interval_max", "connection_latency", "connection_timeout")},
            "default_settings": {x: packet[x] for x in ("cs_sync_antenna_selection", "max_tx_power")},
            "procedure": {x: v for x, v in packet.items()
                          if not x.startswith(("connection_", "creation_")) and x not in
                          ("gap_role", "config_id", "cs_sync_antenna_selection", "max_tx_power")},
        }
        if selected == "initiator":
            groups["creation"] = {x.removeprefix("creation_"): v for x, v in packet.items() if x.startswith("creation_")}
        for group, values in groups.items():
            lines.append(f"    const struct cs_config_{group} {group} = {{")
            lines += [f"        .{key} = {_value(key, value)}," for key, value in values.items()]
            lines += ["    };", f"    err = {prefix}_set_{group}(config, &{group});", "    if (err) return err;"]
        lines += [f"    err = {prefix}_set_config_id(config, {packet['config_id']});", "    if (err) return err;"]
        if selected == "initiator":
            lines += [f"    err = {prefix}_set_channel_map(config, creation.channel_map);", "    if (err) return err;",
                      f"    err = {prefix}_set_creation_context(config, creation.context);", "    if (err) return err;"]
            if packet["creation_cs_enhancements_1"] & 1:
                lines += [f"    err = {prefix}_enable_ipt(config);", "    if (err) return err;"]
        lines += ["    return 0;", "}", "", "int cs_generated_config_patterns(const char *const **patterns, size_t *count) {",
                  "    if (!patterns || !count) return -22;"]
        if patterns:
            lines += ["    static const char *const names[] = { " + ", ".join(map(_c_string, patterns)) + " };",
                      "    *patterns = names;", f"    *count = {len(patterns)};"]
        else:
            lines += ["    *patterns = 0;", "    *count = 0;"]
        lines += ["    return 0;", "}", "", "const char *cs_generated_config_device_name(void) {",
                  f"    return {_c_string(device_name) if device_name else 'NULL'};", "}", "", "/* " + MARKER,
                  document(embedded, settings).replace("*/", "\\u002a/"), "*/", ""]
        output[selected] = "\n".join(lines)
    return output
