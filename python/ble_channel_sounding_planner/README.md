# `ble_channel_sounding_planner` — standalone CS timing and channel planner

Desktop application (PyQt6 + PyQtGraph) that predicts a BLE Channel Sounding procedure
offline: step structures, subevent packing, events, procedure limits and an example
CSA #3a/#3b/#3c hop sequence. It is the planner of the `ble-channel-sounding` Configuration tab
("CS Timing Explorer") as a window of its own, without a device connection.

`ble_channel_sounding_planner` is independent of `ble_channel_sounding`: neither package imports the other
(`tests/test_cs_planner.py` enforces this). It reads and writes the same planner
JSON schema (version 1), including `host_settings`, so files such as `../cs-plan.json`
work in both. The reflector-data, preferred-T_PM and client-log settings are
intentionally not exposed here; `peer_data`, `t_pm` or `log` keys in a file from
`ble-channel-sounding` are ignored and removed when the file is saved. Those settings remain
firmware-owned for standalone exports, so an export made here runs with the
controller's own T_PM even when the plan asked `ble-channel-sounding` for 20 or 40 µs.

## Running

From the `python` directory:

```sh
python -m ble_channel_sounding_planner                      # default scenario
python -m ble_channel_sounding_planner ../cs-plan.json      # open a planner file
python -m ble_channel_sounding_planner cs_generated_config.c  # open the plan embedded in a ble-channel-sounding C export
```

Install the planner independently from the repository root:

```sh
python -m pip install -e ./python/ble_channel_sounding_planner
ble-channel-sounding-planner [file]
```

This project has its own `pyproject.toml`. The host app's PyPI workflow does not
build or publish this planner distribution.

## Window

Same layout and behaviour as the `ble-channel-sounding` planner:

- **Toolbar**: role (Initiator/Reflector config, saved as `configuration.role`), Open…
  (`.json` or exported `.c`), Save… (planner JSON with `host_settings`),
  Export C configuration… (reflector, initiator or both), Export view… (PNG of the
  current view), Fit views, Reset.
- **Settings tabs**: Connection, CS modes, Schedule, Channels (channel map grid, hex
  entry, CSA #3b/#3c), Host (GAP role, TX power, PHY, SNR control, peripheral prefixes,
  Bluetooth name). Values that are never exported (selected interval, T_IP1/T_IP2/T_FCS/T_PM,
  T_SW, T_SW_IPT, subevent and event spacing, and the drawing assumptions) sit on their own
  tab in a panel headed "Example config values selected by the controller". Fields the selected
  modes do not use (sub-mode main runs, RTT sequence and SNR control, PBR timing,
  antenna and IPT settings, the T_SW that IPT does not use, #3c fields with #3b, subevent
  spacing with one subevent, creation context for a reflector) are read-only and held at
  their defaults; see the `ble_channel_sounding` planner README.
- **Tooltips** on every setting wrap at half the window width.
- **Help pane** below the settings: *About this tab* explains the current tab and links to its
  settings; *Setting details* shows the selected or hovered setting's tooltip, what it defines,
  where Core v6.3 defines it and the effect of a change. The texts are in `control_help.py`
  (see the `ble_channel_sounding` planner README).
- **Views**: 1 Connection, 2 Procedures, 3 Events & subevents, 4 Individual step,
  5 Channels. Click a block to drill down; the Procedure/Event/Subevent/Step selectors
  follow. Diagnostics with correction hints appear below the views.

Differences from `ble-channel-sounding`: no FAE view and no import of controller or host
configuration packets (both need a device link). The Bluetooth name, set in the
ble-channel-sounding General view, is on the Host tab here. Reflector data and runtime log
levels are omitted so firmware defaults or board-specific overrides remain in
control.

## C export

*Export C configuration…* writes `cs_generated_config.c` (or `_initiator.c` and
`_reflector.c` for both roles) implementing
`common/libs/cs_generated_config/cs_generated_config.h`: the setter calls, peripheral
prefixes, Bluetooth name, the configuration CRC the client reports, and the planner
JSON embedded in a comment so the file can be reopened. A central (GAP role) needs 1–8
prefixes. It does not emit `cs_generated_config_log()` or a peer-data setter: both
remain available to firmware defaults or overrides. `export_c.py` encodes the host
configuration packets itself (`struct`/`zlib`) instead of importing `ble_channel_sounding.protocol`,
and `tests/test_cs_planner_export.py` checks the standalone CRC and override omission.

## Layout

| File | Contents |
| --- | --- |
| `view.py` | `PlannerWidget` and its plots |
| `control_help.py` | Tooltips, tab overviews and detailed help entries of the settings |
| `export_c.py` | Planner files (`load_document`, `document`), host packet fields, configuration CRC, `generate` (standard library only) |
| `__main__.py` | Application window |
| `model.py` | `Scenario`, `CsConfiguration`, `CsProcedure`, `Connection`; `validate`, `step_segments`, `build_schedule`, `dumps`/`loads` (standard library only) |
| `channels.py` | Channel map helpers and `ChannelSequencer` (seeded example of Core 6.1 Vol 6 Part H §4.1–4.2) |

`model.py`, `channels.py` and `export_c.py` do not import Qt, so they can be used as a library:

```python
from dataclasses import replace
from ble_channel_sounding_planner import Scenario, build_schedule

s = Scenario(target_steps=20)
print(build_schedule(s).duration)                  # 32636 µs (default A1:B1 antenna)
tight = replace(s, procedure=replace(s.procedure, max_procedure_len=10))
print(build_schedule(tight).stop_reason)           # includes a "Correct:" hint
```

## Scope

The timing model starts with the mandatory controller-selected values T_IP1 = 145 µs,
T_IP2 = 145 µs, T_FCS = 150 µs and T_PM = 40 µs; the controller may negotiate another
supported value. Possible values are T_IP1/T_IP2 = 10, 20, 30, 40, 50, 60, 80 or
145 µs; T_FCS = 15, 20, 30, 40, 50, 60, 80, 100, 120 or 150 µs; and T_PM = 10,
20 or 40 µs. At runtime, these values are selected during the Channel Sounding
Configuration procedure after the Channel Sounding Capabilities Exchange, based on the
local controller's capability bitmask, the peer controller's capability bitmask/constraint,
mandatory or conditional support, and, for IPT, the reflector's T_IP2_IPT capability.
T_SW and T_SW_IPT remain 2 µs as planner assumptions because their values are
device-specific. The formulas and limitations are the same as those described in
`ble_channel_sounding/planner/README.md` ("Timing model and scope"). In short: channel sequences
are a seeded example, not the DRBG-determined sequence; mode cadence is a fixed
illustration within the configured range; ACL activity and event offset are
assumptions. The two copies are maintained separately.

## Tests

```sh
python -m unittest tests.test_cs_planner tests.test_cs_planner_export tests.test_cs_planner_gui -v
```

The GUI tests run offscreen and are skipped when PyQt6 or pyqtgraph is missing.
