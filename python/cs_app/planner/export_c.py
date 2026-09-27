"""Generate hostless CS configuration source without modifying firmware files."""
from __future__ import annotations
from dataclasses import fields, replace
from datetime import datetime, timezone
import json
from ..protocol.config import ClientConfig
from ..protocol.packets import OperationMode, PeripheralPatternsPacket, DeviceNamePacket, T_PM_DEFAULT_US
from ..log_config import normalize_log, log_packet, LEVEL_LABELS
from ..validation import validate_patterns, validate_preferred_peer_antenna
from .bridge import config_packet, HOST_DEFAULTS
from .model import dumps, loads, uses_pbr, validate

MARKER = "CS_PLANNER_SCENARIO_JSON"


def load_document(text):
    """Return scenario and host settings from planner JSON or an exported source."""
    if MARKER in text:
        text = text.split(MARKER + "\n", 1)[1].split("\n*/", 1)[0]
    data = json.loads(text)
    host = data.pop("host_settings", {})
    return loads(json.dumps(data)), {**HOST_DEFAULTS, **host}


def document(scenario, host=None):
    """Planner JSON: the scenario (operation mode in configuration.role, IPT in
    configuration.cs_enhancements_1) plus every host-only setting, so a file is a complete configuration."""
    data = json.loads(dumps(scenario))
    data["host_settings"] = {**HOST_DEFAULTS, "peripheral_patterns": [], **(host or {})}
    return json.dumps(data, indent=2) + "\n"


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


def generate(scenario, host=None, *, role="reflector", name="cs_generated_config"):
    """Return source text by role. Does not create C files or firmware headers."""
    host = {**HOST_DEFAULTS, **(host or {})}
    errors = validate(scenario)
    if errors:
        raise ValueError("\n".join(errors))
    if role not in ("initiator", "reflector", "both"):
        raise ValueError("Role must be initiator, reflector or both")
    roles = ("initiator", "reflector") if role == "both" else (role,)
    output = {}
    initiator_only = host.get("peer_data", 0) == 1
    for selected in roles:
        settings = dict(host)
        if role == "both":
            settings["gap_role"] = 0 if selected == "initiator" else 1
        if selected == "reflector":
            # SET_PEER_DATA and SET_T_PM are CS initiator settings; a reflector image has neither.
            settings["peer_data"] = 0
            settings["t_pm"] = T_PM_DEFAULT_US
        patterns = settings.get("peripheral_patterns", []) if settings["gap_role"] == 0 else []
        if settings["gap_role"] == 0:
            errors = validate_patterns(patterns)
            if errors:
                raise ValueError("\n".join(errors))
        mode = OperationMode.CS_INITIATOR if selected == "initiator" else OperationMode.CS_REFLECTOR
        # The embedded plan re-imports with the operation mode of this file.
        embedded = replace(scenario, configuration=replace(scenario.configuration, role=int(mode)))
        packet = config_packet(scenario, settings, mode)
        errors = validate_preferred_peer_antenna(packet)
        if errors:
            # The generated record would fail cs_*_config_set_procedure() at boot.
            raise ValueError(f"CS {selected}: " + "\n".join(errors))
        device_name = DeviceNamePacket.from_name(settings["device_name"]) if settings.get("device_name") else None
        preferred_t_pm = settings.get("t_pm", T_PM_DEFAULT_US) if uses_pbr(scenario.configuration.mode) else T_PM_DEFAULT_US
        config = ClientConfig(mode, packet, PeripheralPatternsPacket.from_patterns(patterns) if patterns else None,
                              device_name, settings.get("peer_data", 0), log=log_packet(settings.get("log")),
                              t_pm=preferred_t_pm)
        levels = normalize_log(settings.get("log"))
        prefix = f"cs_{selected}_config"
        lines = ["/* Generated by cs-app 0.1.0; " + datetime.now(timezone.utc).isoformat() + " */",
                 "/* Configuration name: " + name.replace("*/", "* /").replace("\n", " ") + " */",
                 f"/* Operation mode: CS {selected}; IPT: " +
                 ("requested" if scenario.configuration.cs_enhancements_1 & 1 else "off") +
                 ("" if selected == "initiator" else " (set by the initiator)") + " */",
                 "/* Reflector data: " + ("none (initiator only)" if config.peer_data else
                                          "not requested: the initiator runs without RAS; this image's RAS "
                                          "responder stays unsubscribed" if selected == "reflector" and initiator_only
                                          else "RAS real-time") + " */",
                 "/* Preferred T_PM: " + (f"{config.t_pm} us" if config.t_pm != T_PM_DEFAULT_US else
                                          "not set; the controller keeps its own preference") +
                 ("" if selected == "initiator" else " (set by the initiator)") + " */",
                 "/* Client log: console " + LEVEL_LABELS[levels["console"]].lower() + ", host " +
                 LEVEL_LABELS[levels["host"]].lower() +
                 (" (host protocol level has no effect in a reflector image)" if selected == "reflector" else "") + " */",
                 '#include <cs_generated_config/cs_generated_config.h>', '#include <cs_utils/cs_config.h>', "",
                 f"const uint32_t cs_generated_config_crc32_{selected} = 0x{config.crc32():08x}U;", "",
                 f"int cs_generated_config_{selected}(struct cs_{selected}_config *config) {{",
                 f"    int err = {prefix}_get_default(config);", "    if (err) return err;"]
        groups = {
            "connection": {x.removeprefix("connection_"): getattr(packet, x) for x in
                           ("connection_interval_min", "connection_interval_max", "connection_latency", "connection_timeout")},
            "default_settings": {x: getattr(packet, x) for x in ("cs_sync_antenna_selection", "max_tx_power")},
            "procedure": {f.name: getattr(packet, f.name) for f in fields(packet)
                          if not f.name.startswith(("connection_", "creation_")) and f.name not in
                          ("gap_role", "config_id", "cs_sync_antenna_selection", "max_tx_power")},
        }
        if selected == "initiator":
            groups["creation"] = {f.name.removeprefix("creation_"): getattr(packet, f.name)
                                  for f in fields(packet) if f.name.startswith("creation_")}
        for group, values in groups.items():
            typename = "default_settings" if group == "default_settings" else group
            lines.append(f"    const struct cs_config_{typename} {group} = {{")
            lines += [f"        .{key} = {_value(key, value)}," for key, value in values.items()]
            lines += ["    };", f"    err = {prefix}_set_{group}(config, &{group});", "    if (err) return err;"]
        lines += [f"    err = {prefix}_set_config_id(config, {packet.config_id});", "    if (err) return err;"]
        if selected == "initiator":
            lines += [f"    err = {prefix}_set_channel_map(config, creation.channel_map);", "    if (err) return err;",
                      f"    err = {prefix}_set_creation_context(config, creation.context);", "    if (err) return err;"]
            if packet.creation_cs_enhancements_1 & 1:
                lines += [f"    err = {prefix}_enable_ipt(config);", "    if (err) return err;"]
            if config.peer_data == 1:
                lines += [f"    err = {prefix}_set_peer_data(config, CS_CONFIG_PEER_DATA_NONE);", "    if (err) return err;"]
            if config.t_pm != T_PM_DEFAULT_US:
                lines += [f"    err = {prefix}_set_t_pm(config, CS_CONFIG_T_PM_{config.t_pm}_US);", "    if (err) return err;"]
        lines += ["    return 0;", "}", "", "int cs_generated_config_patterns(const char *const **patterns, size_t *count) {",
                  "    if (!patterns || !count) return -22;"]
        if patterns:
            # Octal escapes preserve UTF-8 bytes and cannot swallow a following hex digit.
            literals = [ '"' + ''.join(f"\\{b:03o}" for b in text.encode("utf-8")) + '"' for text in patterns]
            lines += ["    static const char *const names[] = { " + ", ".join(literals) + " };",
                      "    *patterns = names;", f"    *count = {len(patterns)};"]
        else:
            lines += ["    *patterns = 0;", "    *count = 0;"]
        literal = ('"' + ''.join(f"\\{b:03o}" for b in device_name.text().encode("utf-8")) + '"') if device_name else "NULL"
        lines += ["    return 0;", "}", "", "int cs_generated_config_log(struct app_log_config *config) {",
                  "    if (!config) return -22;",
                  f"    config->console_level = {('APP_LOG_LEVEL_OFF', 'APP_LOG_LEVEL_ERR', 'APP_LOG_LEVEL_WRN', 'APP_LOG_LEVEL_INF', 'APP_LOG_LEVEL_DBG')[levels['console']]};",
                  f"    config->protocol_level = {('APP_LOG_LEVEL_OFF', 'APP_LOG_LEVEL_ERR', 'APP_LOG_LEVEL_WRN', 'APP_LOG_LEVEL_INF', 'APP_LOG_LEVEL_DBG')[levels['host']]};",
                  "    return 0;", "}", "", "const char *cs_generated_config_device_name(void) {",
                  f"    return {literal};", "}", "", "/* " + MARKER,
                  document(embedded, settings).replace("*/", "\\u002a/"), "*/", ""]
        output[selected] = "\n".join(lines)
    return output
