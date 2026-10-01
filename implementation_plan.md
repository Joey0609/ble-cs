# Implementation plan

This is the only implementation plan in the repository. It replaces `update_plan.md` and
`cs_roles_update_plan.md` (removed 2026-09-17). Everything those two files planned and completed
is in the code, and the design they described now lives in the READMEs:

| Topic | Where it is documented |
| --- | --- |
| Wire format, messages, configuration CRC, command rules, sequences, peer discovery | `common/libs/cs_protocol/README.md` |
| Host link threads, session end, native tests | `common/libs/host_link/README.md` |
| cs_utils configuration records, setters, IPT | `common/libs/cs_utils/README.md` |
| Client builds, STOP and interruption rules | `cs_client/README.md` |
| Hostless applications, peer selection, default procedure timing | `cs_hostless_initiator/README.md`, `cs_hostless_reflector/README.md`, `cs_reflector_tag/README.md` |
| Python application, views, sync rules, HDF5/MAT format | `python/README.md`, `python/ble_channel_sounding/README.md`, `python/ble_channel_sounding/planner/README.md` |
| Measurement theory, including IPT | `docs/*.tex` |

`update_plan.md` remains in git history. `cs_roles_update_plan.md` was never committed.

Progress: `[x]` done, `[ ]` open.

## 0. Where things stand (checked 2026-09-23)

- Protocol version `0x000B` is used by both C and Python (`CONNECTION_PARAMETERS`, §1.3;
  `0x0009` added `SET_T_PM`; `0x0008` added `SET_LOG_CONFIG`, §2.4), with
  `CS_PROCEDURES_COMPLETE` for runs that end on their own (`0x0006`) and reflector data
  (`§1.3`). The Python logging and peer-data protocol work is complete, so `ble-channel-sounding` can
  connect to the current `cs_client` firmware. Hostless mode remains supported.
- Firmware: `host_link`, `cs_roles` (role thread, link layer, streamed subevents, STOP/RAS/
  completion rules), both `cs_client` builds, `cs_hostless_initiator` (reports on a report-only
  USB CDC ACM port), `cs_hostless_reflector` and `cs_reflector_tag` are committed and build.
  (`cs_reflector_tag` was fixed on 2026-09-18: library paths from before the move to the repository
  root, and a missing `<zephyr/logging/log_ctrl.h>` include. It runs on `cs_roles` since
  2026-09-20, §3.1, so every application shares the same link and role state machine.)
- Python: `ble_channel_sounding` is complete against the simulator, including the hostless CS mode that
  receives reports from a hostless initiator. Planner timing defaults, peer data, runtime
  logging, Radio Test views, session-history/save/description support, host/peer diagnostics,
  simulator command parity and the mode-3 performance check are implemented with tests and
  documentation. The items found by the plan check of 2026-09-19 (§9 items 1, 4 and 7),
  History in the Session tab (§7.8) and the T_PM setting (§9 item 5, 2026-09-20) are done.
  The ACL connection parameters the client reports are shown in the Controller tab and the
  Connection illustration (§12, §9 item 9, 2026-09-20). The session-actions toolbar's toggle,
  teardown and naming are done on the Python side (§7.8, §9 item 10, 2026-09-22), and the firmware
  half in `host_link` (§10 item 9, 2026-09-24). The negotiated ATT MTU travels in the connection
  report and shows in the Controller tab (§12.4, §9 item 12, §10 item 8, 2026-09-22), and the
  planner draws the RAS real-time transfer from it in the two ACL-scale views (§13, §9 item 11,
  2026-09-22). No code work is open; everything open is hardware verification (§9 item 6,
  §10 items 6 and 9).
- Radio test mode views: the Python configuration and RX-results views are implemented. The
  configuration is grouped by test/RF/traffic/sweep/FEM settings, disables fields that do not
  apply to the selected test while preserving their serialized values, validates edits, and
  round-trips JSON presets (including log levels). RX results retain 5,000 reports, expose live
  plots and capture loading, and lock capture replacement/clearing while a run is active.
- IPT can be requested from the planner and exported (`cs_enhancements_1`). Both initiator images
  and the Tag enable `CONFIG_BT_CTLR_EXTENDED_FEAT_SET`. The firmware and Python planner/export/
  analysis support initiator-only IPT runs; hardware verification remains open (§1.9, §10).
- Logging: `app_log` (§2) is in the firmware. Every application and library logs through it,
  with console and protocol levels from `SET_LOG_CONFIG` or the planner export. The Python
  side (general toolbar, `LogConfigPacket`, export, simulator, recorder and hostless display)
  is complete (§9 item 2).
- Hardware: the hostless initiator README records hardware observations for its default
  procedure interval. The §8.4 step 1 timing tests ran on 2026-09-19
  (`cs_hostless_initiator` ↔ `cs_reflector_tag`): T_PM 10, 20 and 40 µs all reach configuration
  complete through the controller's preferred T_PM (§8.5). Nothing else in §3.3 has been worked
  through.
- Hardware gate (2026-09-23): `cs_client` is not flashed. Every remaining check that needs a
  host link is therefore blocked on one flash — §10 item 4's `SET_T_PM` half, §10 item 8's ATT
  MTU, §10 item 9's teardown, §9 item 6, and §3.3's `cs_client` role pairs, discovery and
  failure cases, antenna mismatch and radio-test build. What the flashed hostless initiator and
  Tag can answer today is §1.9 step 9 (IPT), §2.7 step 7 (logging), §3.3's Tag bugs, RAS
  procedure interval, STOP paths, finite count and stack high-water marks, and §8.4 step 3.

## 1. Reflector data with IPT: RAS or initiator only

### 1.1 Goal

With IPT, the reflector sends each tone back already rotated by the phase it measured. The
initiator's own PCT therefore carries the full two-way phase, and a phase-slope distance needs no
reflector data (`docs/Bluetooth_CS_Inline_Phase_Transfer.tex`, "What the initiator must still be
given"). The user chooses per configuration:

| Reflector data | Setup | What the host gets |
| --- | --- | --- |
| **RAS real-time** (default, and the only choice without IPT) | As today | Initiator and reflector subevents. With IPT, reflector amplitude and quality weight the analysis; Mode 1/3 steps carry the reflector's timing |
| **None (initiator only)**, IPT only | No RAS discovery or subscription | Initiator subevents only. Phase-slope PBR only; no reflector amplitude weighting, no reflector RTT timing, no Mode-3 cross-check |

Without RAS, the procedure interval no longer needs ACL events for the RAS notifications, so it
can drop to 1. For the hostless defaults that means 17.5 ms per procedure instead of 52.5 ms.

Decisions:
- The choice is stored with the configuration, like the IPT request. It is not asked for at
  runtime: the hostless initiator has no user interface.
- IPT is only a request. In initiator-only mode, the initiator checks the peer's IPT capability
  and the created configuration. If either lacks IPT, the run fails with a clear reason. It
  does **not** fall back to RAS, because the configured procedure interval may be too short
  for RAS traffic.
- Reflector images do not change. Their RAS responder sends nothing while no initiator
  subscribes, so one Tag image works with both settings.
- RREQ stays compiled into initiator images; the choice is made at runtime. A build without
  RREQ is not planned.

### 1.2 cs_utils (`common/libs/cs_utils/cs_config.h/.c`)

- `enum cs_config_peer_data { CS_CONFIG_PEER_DATA_RAS_REALTIME = 0, CS_CONFIG_PEER_DATA_NONE = 1 }`.
- `struct cs_initiator_config`: rename `reserved` to `uint8_t peer_data`. The record stays 59
  bytes, and existing zeroed records keep meaning RAS real-time. `cs_initiator_config_get_default()`
  sets RAS.
- `cs_initiator_config_set_peer_data(config, peer_data)`: `-EINVAL` for NULL or an unknown value.
- `cs_initiator_config_check_peer_data(config)`: `-EINVAL` when `NONE` is set without the IPT bit
  in `creation.cs_enhancements_1`. It is a separate check, not part of the setter, because
  `set_creation` and `disable_ipt` can clear the IPT bit afterwards. `host_link` validation and
  `cs_role_start_initiator()` both call it.
- `cs_config` print function: print the reflector data setting.

### 1.3 Protocol (introduced in `0x0007`; current combined version `0x0008`)

| Type | Value | Direction | Fields | Size |
| --- | --- | --- | --- | --- |
| `SET_PEER_DATA` | 0x0110 | Host → client | `peer_data: u8` | 13 |
| `CS_PEER_DATA` | 0x000F | Client → host | `peer_data: u8` | 13 |

- `SET_PEER_DATA` is optional configuration, like `SET_DEVICE_NAME`. Its absence means RAS
  real-time, so only `NONE` is accepted (`VALUE_OUT_OF_RANGE` otherwise). Each configuration
  therefore has one byte representation. It is valid only in the CS initiator mode
  (`MODE_MISMATCH`).
- `APPLY_CONFIG` rejects `NONE` without the IPT bit in the staged initiator configuration
  (`VALUE_OUT_OF_RANGE`, `-EINVAL`).
- CRC order: operation mode, configuration, patterns (if any), device name (if any), peer data
  (if any). Configurations without it keep their CRC. `GET_CONFIG` replays it last.
- `CS_PEER_DATA` is sent by the initiator role (`cs_client` and the hostless initiator) at CS
  configuration complete, before the first subevent. The hostless initiator also resends it with
  its cached link records when the host opens the port. It is needed because a hostless host has
  no applied configuration, and the controller's configuration report does not carry this setting.
- New reason `CS_PROTOCOL_REASON_PEER_IPT_UNSUPPORTED` (0x14), used in `CLIENT_STATE(ERROR)`.
- Extend the shared CRC vector (C `tests/host_link/test_config_store.c`, Python
  `tests/test_protocol.py`) with a configuration that includes `SET_PEER_DATA`.

### 1.4 cs_roles (`cs_role_initiator.c`, `cs_role_core.c`, `cs_role.h`)

Setup with `CS_CONFIG_PEER_DATA_NONE`:

```
encryption → remote capabilities → FAE → config create → config complete → CS security → enable
             └ no cs_ipt_reflector_supported     └ negotiated cs_enhancements_1 without IPT
               → ERROR(PEER_IPT, -ENOTSUP)          → ERROR(PEER_IPT, -ENOTSUP)
```

- `cs_role_start_initiator()` returns `-EINVAL` when `cs_initiator_config_check_peer_data()` fails.
- No `bt_gatt_dm` discovery, no `bt_ras_rreq_*` calls, no `RAS_READY` state. Check that `cs_client`
  and Python do not require `RAS_READY` before `RUNNING`.
- New failure stage `CS_ROLE_FAILURE_PEER_IPT`. With `auto_restart`, this failure does not restart
  the link: reconnecting to the same peer would fail forever.
- Local subevents stream as today. The local step buffer is not filled, since no RAS parser needs it.
- STOP: no `STOP_RAS` stage. `STOPPED(HOST)` follows the disable event, and `cs_role_stop()` never
  returns `-ETIMEDOUT`.
- Finite `max_procedure_count`: `STOPPED(COMPLETE)` and procedures-complete follow the disable
  event directly.
- `ras_data_lost` is never raised. Link-loss and role-change cleanup already track RREQ per
  resource, so nothing is freed that was not allocated.

### 1.5 Applications

- `host_link_config.c`: `SET_PEER_DATA` payload → `cs_initiator_config_set_peer_data()`; validation
  per §1.3. `host_link_config_store`: stage, commit, CRC and `GET_CONFIG` replay of the new payload.
- `host_link_reports`: `host_link_report_peer_data()`.
- `cs_client` (`cs_session.c`): send `CS_PEER_DATA` on the configuration callback; map
  `CS_ROLE_FAILURE_PEER_IPT` → `PEER_IPT_UNSUPPORTED`.
- `cs_generated_config`: no header change; the generated initiator function calls the new setter.
- `cs_hostless_initiator`: log the reflector data setting and CRC at boot. Send and cache
  `CS_PEER_DATA`. On `PEER_IPT` failure, log an error and halt radio activity until reset. Leave
  RAS counters out of the stats line when RAS is off. The fallback defaults stay RAS, Mode 2,
  no IPT.
- `cs_client` reflector role, `cs_hostless_reflector`, `cs_reflector_tag`: no change.

### 1.6 Python (`python/ble_channel_sounding`)

- **Planner** (`planner/bridge.py`, `planner/model.py`, `views/cs_view.py`):
  - `host_settings.peer_data` (0 RAS real-time, 1 none) in `HOST_DEFAULTS`, saved in plan files.
  - Control *CS modes → Reflector data* ("RAS real-time" / "None (initiator only)"), directly
    after *Inline PCT transfer (IPT)*, with a tooltip. It is enabled only when IPT is requested and
    the operation mode is CS initiator. Turning IPT off resets it to RAS.
- **Validation** (`model.validate`, schedule notes):
  - Error: `NONE` without IPT.
  - Note, Mode 3 with `NONE`: RTT has no reflector timing and there is no independent check of
    the IPT phase.
  - Note, `NONE`: the procedure interval can be 1 ACL event.
  - Note, RAS with `min_procedure_interval` 1: RAS real-time data needs ACL events between
    procedures (see `cs_hostless_initiator/README.md`).
- **Protocol** (`protocol/packets.py`, `protocol/config.py`): `PeerDataPacket` (`SET_PEER_DATA`),
  `CsPeerDataPacket`, reason name, `PROTOCOL_VERSION = 0x0008`. `ClientConfig` carries the
  optional payload in `packets()`, `from_packets()`, `payloads()` and `crc32()` per §1.3.
- **C export** (`planner/export_c.py`): `cs_initiator_config_set_peer_data(config,
  CS_CONFIG_PEER_DATA_NONE)` after `enable_ipt` when selected. The header comment says
  "Reflector data: none (initiator only)", and the exported CRC includes the payload. A "both"
  export notes in the reflector file that the initiator runs without RAS.
- **Simulator**: firmware rules for `SET_PEER_DATA` and `APPLY_CONFIG`. With `NONE`: no reflector
  subevents, no `RAS_DATA_LOST`, and `CS_PEER_DATA` is sent. A simulated peer without IPT support
  ends in `CLIENT_STATE(ERROR, PEER_IPT_UNSUPPORTED)`.
- **Session and app**: show the reason. In hostless mode, take the setting from `CS_PEER_DATA`.
  In hosted mode, take it from the applied configuration (the host's synced configuration, or
  the `GET_CONFIG` reply): `cs_client` sends `CS_PEER_DATA` only at configuration complete,
  once per link, so a host that reconnects to a client with an established link gets none.
- **Connecting to a running client** (decided 2026-09-18, applies to every mode): a hosted client
  on USB CDC stops its operation when the host is no longer detected (DTR low), as `host_link`
  already does; the link and the applied configuration stay. So a host finds a running client
  only on a port without DTR (hardware UART). When `CONNECT_RESPONSE` reports `RUNNING`, the
  host requests `GET_CONFIG` and warns the user that it attached to a run it did not start,
  naming any difference from its own configuration. It does not stop the run on its own.
  The hostless initiator has no host session and is not affected.
- **Results** (`results.py`, estimates):
  - A procedure is complete with initiator subevents only when reflector data is `NONE`, taken
    from the applied configuration or `CS_PEER_DATA`.
  - IPT-aware PBR: the initiator PCT alone carries the two-way phase. Without reflector steps,
    use initiator quality and unit amplitude. With RAS, use the reflector's real part as
    amplitude and flag a non-zero Q as a protocol violation.
  - RTT without reflector timing is shown as unavailable; no nominal turnaround is substituted.
  - Check `correction_phase` and `tone_pair_delay_us` against the IPT report (the reflector
    rotates in its own tone slot), and change them if the corrections differ under IPT.
- **Recording**: `/config` stores `peer_data`; `CS_PEER_DATA` reports go to
  `/reports/peer_data`, and MAT conversion includes it.
- **Controller view** (`controller.py`): with `NONE`, "Reflector: IPT not supported" is marked
  as a run failure, not a warning. `compare_configuration` gets a *Reflector data* row.
- **Radio test mode views** (`views/radio_test_view.py`, `views/radio_results_view.py`):
  implemented. The configuration form presents Test, Channel, Timing and FEM tabs with
  unit-aware labels and tooltips; active fields follow the selected test type while
  inactive values remain intact for exact preset/configuration round trips. Inline validation
  feedback is shown while editing, and presets preserve both packet values and client log
  levels. The RX results view keeps the last 5,000 reports, plots RSSI/rates/CRC/drops/channel
  data, loads HDF5 captures, and prevents capture replacement or clearing during a run.

### 1.7 Tests

- C native: `tests/host_link/test_config_store.c` covers staging, CRC vector with and without the
  payload, `GET_CONFIG` replay, rejection of RAS value, wrong mode, and `NONE` without IPT. The
  cs_utils setter and check get the same cases.
- `test_role_sm.c` (§3.1) gets initiator-only cases: no RAS calls, both `PEER_IPT` failure points,
  no restart after `PEER_IPT`, STOP and finite count without the RAS wait.
- Python: `test_protocol.py` (sizes, CRC vector, round trips); planner model tests (validation
  and notes); planner GUI tests (control enabling, IPT-off reset, save/open); `test_export_c.py`
  (setter call, CRC, compile against the real headers); `test_session.py` and simulator
  (initiator-only run, `PEER_IPT_UNSUPPORTED`); results tests (initiator-only procedures, IPT
  PBR with and without reflector amplitude, RTT unavailable); radio view tests (grouped controls,
  active-field rules, invalid-edit feedback, and run-time capture locking); `test_recorder.py`;
  controller checks.
- Builds: both `cs_client` builds, `cs_hostless_initiator` with and without an initiator-only
  export, without compiler warnings.

### 1.8 Documentation

Update `common/libs/cs_utils/README.md` (IPT section), `common/libs/cs_protocol/README.md`
(messages, CRC order, rules, version), `common/libs/host_link/README.md`, `cs_client/README.md`,
`cs_hostless_initiator/README.md` (reflector data, procedure interval, `PEER_IPT` halt),
`python/ble_channel_sounding/planner/README.md` (JSON key, control, validation) and `python/README.md`.

### 1.9 Steps

1. [x] cs_utils: `peer_data` field, setter, check, print (§1.2), with native tests
   (`tests/cs_utils/run.sh`, which builds `cs_config.c` against the real Zephyr Bluetooth
   headers; it needs `ZEPHYR_BASE`).
2. [x] Protocol peer-data extension (introduced in `0x0007`, current combined version `0x0008`)
   and shared CRC vector (§1.3): the shared initiator
   configuration with `creation_cs_enhancements_1` = 1, the two patterns and `SET_PEER_DATA(1)`
   → `0x8252106B` (`CONFIG_CRC_VECTOR_PEER_DATA`, C and Python).
3. [x] `host_link` store, config conversion and report (§1.5), with native tests. `APPLY_CONFIG`
   rejects none without IPT in the store (`host_link_config_check_apply`, natively tested);
   `host_link_config_set_to_initiator()` applies the same rule through
   `cs_initiator_config_check_peer_data()`. The `GET_CONFIG` replay with `SET_PEER_DATA` is
   natively tested in `tests/host_link/test_commands.c` (§3.1, 2026-09-18).
4. [x] `cs_roles` initiator-only setup, STOP and completion (§1.4). The `test_role_sm.c` cases of
   §1.7 are in `test_initiator_only()` (2026-09-18).
5. [x] `cs_client` and `cs_hostless_initiator` (§1.5); builds.
6. [x] Planner control, validation, bridge, C export (§1.6), with tests. The schedule notes and
   the *both* export note were added on 2026-09-19 (§9 item 1).
7. [x] Simulator, session, results, recording, controller view (§1.6), with tests. IPT PBR with
   RAS, the initiator quality in initiator-only PBR and the results/recorder/export tests were
   added on 2026-09-19 (§9 item 1).
8. [x] Documentation (§1.8).
9. [ ] Hardware:
   - [ ] The Tag (`nrf54l15tag/nrf54l15/cpuapp`) and `cs_hostless_reflector` on
     `nrf54lm20dk/nrf54lm20b/cpuapp` report `cs_ipt_reflector_supported`.
     - [x] Tag, 2026-09-23: `/reports/capabilities` in
       `recordings/session_hostless_cs_23_Sep_2026_13_15_26.h5` carries two rows, and the remote
       one (2 antennas) has `cs_ipt_reflector_supported` 1.
     - [ ] `cs_hostless_reflector` on `nrf54lm20dk` still to check.
   - [x] Hostless initiator (IPT, `NONE`, Mode 2) ↔ Tag: no aborted procedures; achieved update
     rate **16.68 procedures/s** (2026-09-23,
     `recordings/session_hostless_cs_23_Sep_2026_14_00_47.h5`). 1065 procedures over 63.9 s,
     74 steps in every subevent, 71706 steps, `procedure_done_status` and
     `subevent_done_status` 0 throughout, no aborted or partial subevents, and no
     `RAS_DATA_LOST` at all (there is no RAS with `peer_data` `NONE`).
     - **Procedure interval 1 is reachable** (2026-09-23, user's finding,
       `session_hostless_cs_23_Sep_2026_18_08_18.h5`): `procedure_interval` 1 at a 18.75 ms
       connection interval gives **53.40 procedures/s**, one procedure per ACL event, 74 steps
       in every subevent and no aborted or partial subevents. The user reports that
       `max_main_mode_steps` above 1 is what forces the extra ACL allocation, and that the
       other combinations tried failed; the working configuration has
       `min_main_mode_steps` and `max_main_mode_steps` both 1, `max_procedure_len` 17,
       connection interval 15 (18.75 ms) and `CONFIG_BT_CTLR_SDC_CS_EVENT_LEN_DEFAULT` 14000.
       Four values changed together from the last interval-2 run, so which one is decisive is
       not isolated. `max_main_mode_steps` is the weaker candidate: a temporary `APP_LOG_INF`
       of the raw `bt_conn_le_cs_config` in `config_cb()` (2026-09-23) shows Zephyr itself
       reporting `main steps 0-0` whatever the request, which matches Zephyr's own note that
       those fields bound main-mode steps only before a sub-mode step and so do not apply to a
       mode-2 configuration without one. Every other field in that callback matches
       `/reports/configuration`, so the record is faithful and there is no wiring fault. The
       controller Kconfigs are not involved either: with
       `CONFIG_BT_CTLR_SDC_MAX_CONN_EVENT_LEN_DEFAULT` and
       `CONFIG_BT_CTLR_SDC_CS_EVENT_LEN_DEFAULT` back at their 7500 and 5000 us defaults, the
       run still gives `procedure_interval` 1, 74 steps and 53.40 procedures/s
       (`session_hostless_cs_23_Sep_2026_18_26_07.h5`), so both overrides were removed again.
       That also disproves the budget model used earlier in the day: 7500 + 10625 us inside an
       18750 us interval works, so `MAX_CONN_EVENT_LEN` is a ceiling the ACL event may grow to,
       not time carved out of every interval. What is left as the lever is `max_main_mode_steps`
       1 (from 4), `max_procedure_len` 17 (from 20 or 30), or the 18.75 ms connection interval
       (from 20 ms). Isolate by restoring `max_main_mode_steps` 4 with everything else
       unchanged.
     - `max_procedure_len` caps `subevent_len` outright: 13 gives a reported `subevent_len` of
       8125 (13 x 625) against a requested 12000, and 17 gives 10625. Truncating buys no rate
       at all - 60 steps at 53.37/s against 74 at 53.40/s - so set it to cover the steps and
       take the rate from the connection interval. About 135.5 us of capacity per step
       (8000 us gave 59 steps, 8125 gave 60), so 74 steps need about 10.2 ms: 17 clears it,
       16 does not.
     - Superseded, kept for the record: the earlier reading of these runs was that interval 1
       was unreachable. It answered `procedure_interval` 2 and `event_interval` 2 across every
       combination tried before `max_main_mode_steps` was brought down to 1. Tested on
       2026-09-23 across connection intervals of 62.5, 30 and 20 ms, subevent reservations of
       20000, 12000, 8000 and 3000 us, `max_procedure_len` 40, 30, 20, 16 and 6, ACL event
       reservations (`CONFIG_BT_CTLR_SDC_MAX_CONN_EVENT_LEN_DEFAULT`) of 7500 and 2500 us, and
       both `peer_data` RAS and `NONE` — including at 18 percent occupancy, where there was
       nothing to be short of. Nothing in this repository overrides the request: the export
       wins over the hostless app's `APP_PROCEDURE_INTERVAL_*` defaults (`main.c` returns early
       when `cs_generated_config_initiator()` succeeds), `cs_initiator_config_set_procedure()`
       is a plain struct copy, and `apply_procedure()` passes the values straight to
       `bt_le_cs_set_procedure_parameters()`. The RAS explanation (§13, `model.py`: RAS
       real-time needs ACL events between procedures) is not the cause either — the interval
       stays 2 with no RAS traffic whatsoever.
     - Best rate measured: **25.03 procedures/s** (39.9 ms period, 74 steps, no aborts) at a
       20 ms connection interval with the ACL event reservation cut to 2500 us
       (`session_hostless_cs_23_Sep_2026_14_16_17.h5`). The same 20 ms failed at the default
       7500 us reservation, where 7.5 + 12 ms does not fit in 20 ms. Truncating the procedure
       buys no rate at all: 21 steps gave 16.75/s against 74 steps at 16.68/s at 30 ms, because
       the skipped ACL event absorbs the slack either way. Always run the full step count and
       set the rate from the connection interval.
     - The update rate is therefore set by the **connection interval**, not the procedure
       interval: the period is `procedure_interval x connection_interval`, so 2 x 62.5 ms gave
       125 ms and 2 x 30 ms gives 60 ms. The generated initiator config pins the connection
       interval at 24 (30 ms) for this reason.
     - Subevent reservation sizing: the full 74-step mode-2 procedure needs **9.66 ms**
       (2 mode-0 steps at 222 us and 72 mode-2 at 128 us, each step's segments plus the
       `T_FCS` gap that follows it). A `min/max_subevent_len` of 8000 us silently truncated the
       procedure to 59 steps with no error anywhere — only `num_steps` in the recording showed
       it. 12000 us restores 74. Mode 3 at 74 steps needs about 14.8 ms, so that run needs a
       larger reservation again.
   - [ ] Same positions, three runs: IPT + `NONE`, IPT + RAS, no IPT + RAS. Compare distances and
     spread in `ble-channel-sounding`.
   - [ ] A reflector without IPT support ends in `PEER_IPT_UNSUPPORTED` with no reconnect loop.
   - [ ] Mode 3 with `NONE`: PBR works; RTT is shown as unavailable.
   - [ ] The Tag's unsubscribed RAS responder does not affect procedures.

## 2. Logging library with runtime-selected consumers

### 2.1 Where log messages went before §2

The routing since §2 is in `common/libs/app_log/README.md`.

| Producer | API | Consumer |
| --- | --- | --- |
| Libraries and applications (`host_link.c`, `cs_role_*.c`, `cs_client/src/*`, both hostless apps, `cs_reflector_tag`) | Zephyr `LOG_INF/WRN/ERR` (deferred mode) | Zephyr log backend, fixed at build time: the debug UART (`cs_client`: uart20, 921600 baud; hostless apps on the DK: board console UART) or RTT (`cs_reflector_tag`, `cs_hostless_reflector` on the Tag). Read in a terminal or RTT viewer; `ble-channel-sounding` never sees it |
| Client state changes, refused/failed commands, parse errors, overruns (`host_link.c`, `host_link_reports.c`, `cs_session.c`, `client_state.c`) | `HOST_LINK_LOG_INF/WRN/ERR` (`host_link_reports.h`): Zephyr `LOG_*` **and** `host_link_report_logf()` | Debug UART as above, plus a `LOG_MESSAGE` frame with a `<inf>`/`<wrn>`/`<err>` prefix. In `ble-channel-sounding`: *Session log* view (`report_log.py`, category "client log", level from the prefix), Results *Log* tab, HDF5 `/log` and MAT. Dropped without a host session |
| Queue-full drop notices (`host_link.c`, `cs_role_core.c`, `cs_role_events.c`, `cs_client/src/peer_discovery.c`) | `printk` | Console only, bypassing the log subsystem |
| Record dumps (`cs_capabilities_print()`, `cs_*_config_print()`, `cs_fae_table_print()`, `cs_step_print()`, `cs_subevent_header_print()`) | Caller buffer | Whatever the caller logs it to (`cs_reflector_tag`: `LOG_INF("%s")`; test apps) |
| `cs_hostless_initiator` | Zephyr `LOG_*` only | Debug UART only. Its USB CDC port carries reports but no `LOG_MESSAGE` |
| Zephyr/NCS subsystems (Bluetooth host, SDC, USB) | Zephyr `LOG_*` | Zephyr log backend |

Problems: which consumer receives a message is decided per call site and at build time.
A hostless build cannot send its log to the host. The host cannot silence debug output or ask
for more detail. `printk` notices never reach the host.

### 2.2 Goal

A shared library, `common/libs/app_log/`, that every application and library in this repository
logs through. Its consumers are:
- **console**: `printk`, reaching the UART or RTT console.
- **protocol**: `LOG_MESSAGE` frames through `host_link`.

Which consumers are enabled, and at which level, is part of the **applied configuration**,
changed at runtime without rebuilding:
- Hosted client: set by the host with the configuration and applied at `APPLY_CONFIG`.
- Hostless applications: read from the planner export at boot.

Kconfig only sizes the library (buffer, message length, thread stack). It never selects consumers.

Decisions:
- Levels use Zephyr numbering: 0 off, 1 error, 2 warning, 3 info, 4 debug. Each consumer has its own
  threshold.
- Defaults, used until a configuration is applied and whenever none is held: console info,
  protocol warning. With protocol at warning, the host keeps receiving abnormal situations. State
  changes need no duplicate text: `report_log.py` already describes `CLIENT_STATE` frames.
- The log configuration follows the existing configuration rules: it counts in the CRC, is
  returned by `GET_CONFIG`, and changes only with the Bluetooth link down. Changing levels
  during a run is not supported, by decision (2026-09-18): the levels are set before the run
  and are part of the session record, so they must not change on the fly.
- Zephyr/NCS subsystem logging stays on the Zephyr log backend, controlled at build time. Routing
  it into `app_log` (a Zephyr log backend that forwards to the consumers) is not planned.

### 2.3 Firmware library (`common/libs/app_log/`)

| File | Responsibility |
| --- | --- |
| `app_log.h` | `APP_LOG_ERR/WRN/INF/DBG(fmt, ...)` with a per-file module name (`APP_LOG_MODULE(name)`); `struct app_log_config { uint8_t console_level; uint8_t protocol_level; }`; `app_log_configure()`, `app_log_config_get()`, `app_log_defaults()`; `app_log_sink_register(enum app_log_sink, write_fn)` |
| `app_log.c` | Level check per consumer before formatting (no work when every consumer filters the message out). Formats `<lvl> module: text` into a fixed record, then enqueues it. A log thread writes each record to the enabled consumers. Full queue: drop and count, and report the count as one warning once room returns (replaces the `printk` notices) |
| `app_log_console.c` | Console consumer: `printk` of the record, with a timestamp |

- `host_link` registers the protocol consumer (`host_link_report_log()`), so `app_log` does
  not depend on `host_link`. Without a registered consumer or host session, protocol records are
  discarded without cost.
- Safe from Bluetooth callbacks and work items: callers only format and enqueue, never block.
  ISR context is not supported (`__ASSERT`).
- Kconfig: `CONFIG_APP_LOG` (buffer entries, `CONFIG_APP_LOG_MESSAGE_MAX` replacing
  `CONFIG_APP_HOST_LINK_LOG_MESSAGE_MAX`, thread stack and priority). Applications no longer
  need `CONFIG_LOG` for their own messages; they keep it only for subsystem logs.
- Migration: replace `LOG_*`, `HOST_LINK_LOG_*` and the `printk` notices in `common/libs`,
  `cs_client`, both hostless apps and `cs_reflector_tag`. Then remove `HOST_LINK_LOG_*` and
  `host_link_report_logf()`, and drop the `LOG_MODULE_*` templates of `APP_HOST_LINK` and
  `APP_CS_ROLES`. `tests/*` apps are not changed.

### 2.4 Configuration

- **Record**: `struct app_log_config` is part of the configuration set in
  `host_link_types.h` (`host_link_config_set`), not of the CS records, because it also applies to
  the radio test mode.
- **Protocol**: `SET_LOG_CONFIG` (0x0111, host → client, `console_level: u8`, `protocol_level: u8`,
  14 bytes). It is optional configuration in every operation mode, and its absence means the
  defaults. A payload equal to the defaults is rejected (`VALUE_OUT_OF_RANGE`), as are levels
  above 4, so each configuration has one byte representation. CRC order: mode, configuration,
  patterns, device name, peer data (§1.3), log configuration. `GET_CONFIG` replays it last.
  `APPLY_CONFIG` calls `app_log_configure()`. It ships in the same protocol version as §1.3
  when both are implemented together, otherwise in the next one.
- **Hostless**: `cs_generated_config_log(struct app_log_config *)` in `cs_generated_config.h`. The
  weak default fills the defaults and returns `-ENOENT`. The hostless apps and `cs_reflector_tag`
  call it before starting Bluetooth. `cs_hostless_initiator` registers the protocol consumer on
  its report-only USB CDC port, so its log can reach `ble-channel-sounding` in hostless mode. The reflector
  images have no protocol link and ignore `protocol_level`.
- **Radio test build**: same `SET_LOG_CONFIG` handling. There is no hostless radio test, so it needs
  no export.

### 2.5 Python (`python/ble_channel_sounding`)

- **General toolbar**: *Console* and *Host* level selectors (Off, Error,
  Warning, Info, Debug), used in every operation mode. Saved in plan files
  (`host_settings.log`) and radio test presets.
- **Protocol**: `LogConfigPacket`; `ClientConfig` sends it only when it differs from the
  defaults, and includes it in `payloads()`/`crc32()` and `from_packets()`. The sync dialog shows
  it in the field diff.
- **C export**: `cs_generated_config_log()` with the selected levels; the header comment names
  them. A reflector export notes that `protocol_level` has no effect there.
- **Simulator**: applies the rules above and emits `LOG_MESSAGE` frames only at or above
  `protocol_level`.
- **Consumers**: *Session log*, Results *Log* tab and HDF5 `/log` stay the consumers of
  `LOG_MESSAGE`. `/config` records the log configuration of the run. In hostless mode, the
  hostless initiator's `LOG_MESSAGE` frames appear in the same places.

### 2.6 Tests and documentation

- Native `tests/app_log/`: per-consumer thresholds, no formatting when every consumer filters
  the message out, prefix and module format, truncation at `CONFIG_APP_LOG_MESSAGE_MAX`, full
  queue drop count and its single warning, a missing protocol consumer.
- `tests/host_link/test_config_store.c`: `SET_LOG_CONFIG` staging, CRC vector with the payload,
  `GET_CONFIG` replay, rejection of defaults and out-of-range levels.
- Python: `test_protocol.py` (size, CRC vector), `test_session.py`/simulator (level filtering,
  apply), general-toolbar GUI test, `test_export_c.py` (compiles with `cs_generated_config_log()`),
  `test_recorder.py` (`/config` log configuration).
- Builds: every application with and without an export; no compiler warnings.
- Documentation: new `common/libs/app_log/README.md` (the §2.1 table updated to the new routing);
  `cs_protocol`, `host_link`, `cs_client`, hostless and Tag READMEs; `python/ble_channel_sounding/README.md`.

### 2.7 Steps

Decided while implementing the firmware (2026-09-18):
- `host_link` registers the protocol consumer when a host session opens and removes it when the
  session ends, so without a session protocol messages are not formatted. The report-only
  transport registers it for good.
- A `LOG_MESSAGE` lost for transmit room counts as a dropped report but is not announced: the
  announcement would itself be a log message. The other report losses are logged as warnings.
- `host_link_report_log()` is removed with `host_link_report_logf()`: the consumer in
  `host_link.c` encodes the frame itself.
- Records come from a slab and pass through a FIFO, so callers format straight into the record,
  with no message-sized buffer on their stack. `app_log_flush()` drains the queue from the calling
  thread: the Tag calls it before rebooting, and the native tests use it.
- `cs_hostless_initiator` logs its per-subevent line at debug, not info: it runs in Bluetooth
  context on every subevent. The 10 s counters stay at info.
- `cs_reflector_tag` logs its configuration dump one line per message and sets
  `CONFIG_APP_LOG_QUEUE_DEPTH=32` for it: the whole dump is longer than a message.
- A planner export with invalid levels logs a warning and keeps the defaults. Unlike an
  invalid CS configuration, it does not halt the application.

1. [x] `app_log` library, console consumer, native tests (§2.3; `tests/app_log/run.sh`).
2. `host_link`: protocol consumer registration, `SET_LOG_CONFIG` staging/CRC/replay/apply;
   protocol C and Python; shared CRC vector (§2.4).
   - [x] C, protocol version `0x0008` (2026-09-18, firmware only on request; the C and Python
     protocol steps did not finish together). Shared vector: the initiator configuration and
     two patterns of `0xB61D36F1` with `SET_LOG_CONFIG(4, 3)` → `0x7EA17539`
     (`CONFIG_CRC_VECTOR_LOG_CONFIG`). The radio test build takes the same path.
   - [x] Python: `LogConfigPacket`, version `0x0008`, the same vector in `test_protocol.py`
     (§9 item 2).
3. [x] Migrate `common/libs`, `cs_client` (both builds), hostless apps and `cs_reflector_tag`;
   remove `HOST_LINK_LOG_*` and the `printk` notices (§2.3).
4. [x] `cs_generated_config_log()` weak default and its use in the hostless apps and the Tag (§2.4).
5. [x] Python general toolbar, `ClientConfig`, C export, simulator, recorder (§2.5), with tests.
6. Documentation (§2.6).
   - [x] Firmware: new `common/libs/app_log/README.md`; `cs_protocol`, `host_link`, `cs_client`,
     both hostless and Tag READMEs.
   - [x] `python/ble_channel_sounding/README.md`.
7. [ ] Hardware:
   - [ ] Debug level on both consumers during a running initiator (mode 3, 4 paths): no
     procedure aborts, no RAS data lost; record the drop count.
   - [ ] Console over RTT on the Tag with no viewer attached does not block.
   - [x] Hostless initiator log appears in `ble-channel-sounding` hostless mode at the exported level
     (2026-09-23). It did not before: `cs_generated_config_log()` in
     `configs/cs_generated_config_initiator.c` set `protocol_level` to `APP_LOG_LEVEL_WRN`, while
     `log_counters()` in `cs_hostless_initiator/src/main.c` logs the periodic counters at INF, so
     the host saw no `LOG_MESSAGE` at all and `ble-channel-sounding` wrote no `/log` table
     (`session_hostless_cs_23_Sep_2026_13_15_26.h5`). With `protocol_level` INF the counters,
     state changes and the configuration line arrive and `/log` fills
     (`session_hostless_cs_23_Sep_2026_13_33_17.h5`, 24 rows). The per-subevent line at
     `main.c` stays DBG and is still dropped, which is what keeps the link usable. The file is
     the planner's C export, so the level reverts on the next export unless the `ble-channel-sounding` host
     log level is Info.

## 3. Open items carried over from the previous plans

### 3.1 Firmware

- [x] **Unique Tag names from the Bluetooth address.** `cs_reflector_tag/src/main.c` removes the
  spaces from the base name (`CONFIG_BT_DEVICE_NAME="CSTag"` or the planner export) and appends
  the identity address as 12 upper-case hex digits, MSB first (`CSTagC3A1B2D4E5F6`, 17 bytes).
  The base may be at most 10 bytes without spaces so the name fits the 22-byte advertising
  field: a build check covers Kconfig, boot stops with `TEST FAIL` for a longer export name. The
  hostless initiator's default prefix pattern is `CSTag`.
- Task watchdog on the host link thread: moved to future work (§11, 2026-09-18).
- [x] **Native command-rule tests for `host_link.c`** with stub handlers: every status path of the
  command rules (`NOT_CONNECTED`, `BUSY`, `LINK_ACTIVE`, `MODE_MISMATCH`, `MISSING_CONFIG`,
  `CONFIG_MISMATCH`, `INVALID_FRAME`, `VERSION`), staging/apply semantics, `GET_CONFIG` replay and
  the `START` CRC mismatch. Done 2026-09-18: `tests/host_link/test_commands.c` includes
  `host_link.c` with the transport, `app_log` and the handlers stubbed (kernel and atomic
  substitutes in `tests/host_link/include/`); the fixture is shared with `test_config_store.c`
  through `config_fixture.h`. It also covers `UNSUPPORTED`, `MISSING_PATTERNS`, the applied log
  levels, session end and report counting.
- [x] **`tests/cs_roles/test_role_sm.c`** (native, kernel and Bluetooth calls stubbed): initiator
  and reflector setup order; each failure stage → `ERROR` and cleanup; setup timeout; STOP with
  and without the last RAS data; finite count → `COMPLETE`; peer disable on the reflector →
  `PEER`; link lost during STOP releases the waiter; a role change frees the other RAS role.
  Done 2026-09-18, with the initiator-only cases of §1.7. It includes `cs_role_core.c`, runs the
  role thread's handler and deadline check on a test clock, and delivers completions through the
  real Bluetooth callbacks; the link layer and the event thread are stubbed. The Bluetooth, NCS
  RAS/GATT DM and `app_log` stubs (`bt_stubs.c`) log each command for the setup-order checks.
- [x] **`tests/cs_roles/test_events.c`** (native): control events are never dropped; RAS-lost
  events merge beyond `CONFIG_APP_CS_ROLES_EVENT_RESERVE`; the two-pass subevent length equals
  the bytes written in pass 2. Done 2026-09-18. "Never dropped" is tested as its mechanism: the
  role thread posts with `K_FOREVER`, Bluetooth context and the event thread never wait, and the
  reserve still takes the control events of Bluetooth context. The event loop body moved into
  `deliver_queued()` so the test can drain the queue as the event thread does.
- [x] **Streamed vs. record-built subevent frames**: a native comparison for all step types and
  1–4 antenna paths. It needs the Zephyr Bluetooth headers on the host. Done 2026-09-18:
  `tests/cs_roles/test_stream.c`, both roles, all seven RTT types, 282 subevents, byte-identical
  valid frames. The three `cs_roles` tests build against the real Zephyr and NCS headers
  (`tests/cs_roles/flags.sh`: `ZEPHYR_BASE`, `CONFIG_LITTLE_ENDIAN`, Kconfig defaults), so
  `tests/cs_roles/run.sh` now needs `ZEPHYR_BASE`.

- [x] **Decision (2026-09-20): `cs_reflector_tag` is kept and ported onto `cs_roles`**, not
  retired for `cs_hostless_reflector -b nrf54l15tag/nrf54l15/cpuapp`. The application keeps what
  is the Tag's own — the unique name from the identity address, the antenna checks against the
  controller, the `TEST_*` fallback configuration and its boot dump, the two/four-path subevent
  and procedure counters, the RTT console — and `CONFIG_APP_CS_ROLES_REFLECTOR` takes over the
  link and role state: the role thread, the event queue and its reserve, the STOP/RAS/completion
  rules and the `auto_restart` restart of a lost or failed link, all covered natively by
  `tests/cs_roles/`. `src/main.c` went from 467 to 328 lines; its own connection, CS and RAS
  callbacks, the event `k_msgq` and the advertising code are gone. Consequences:
  - `cs_roles` advertises with extended advertising (`CONFIG_BT_EXT_ADV`, required by
    `libs.cmake` for a peripheral), so a scanner that does not receive extended advertising
    reports no longer finds the Tag. That is `tests/cs_initiator_test` only; `cs_client` and
    `cs_hostless_initiator` both set `CONFIG_BT_EXT_ADV`. The 22-byte name cap of the legacy
    payload is kept as a name cap.
  - The `recycled` restart and the cold reboot of a single failed advertising restart are
    replaced by the `cs_roles` restart every `CONFIG_APP_CS_ROLES_LINK_RESTART_DELAY_MS`; the
    Tag still has no button, so `main.c` counts consecutive `ERROR(CONNECT)` states and
    cold-reboots after five.
  - The peripheral no longer requests ACL connection parameters:
    `cs_role_link_params.connection` is used only when `cs_roles` creates the connection as
    the GAP central (`cs_role_link.c`), so the record's connection section is inert on the Tag,
    as it already is on `cs_hostless_reflector`. The initiator's parameters apply.
  - The counter line moved to a delayable work item on
    `CONFIG_CS_REFLECTOR_TAG_STATS_INTERVAL_S` (default 5), the interval of the former
    `k_msgq_get()` timeout.
  Both §3.3 Tag observations (RAS buffer allocation failures about 23 s in, and the Tag never
  advertising again afterwards) were against the standalone image and are repeated on this one.
- [x] **Tag Kconfig settings the other applications share** (2026-09-20). `prj.conf` now sets
  `CONFIG_BT_BONDABLE=n` (the Tag has no settings store, and CS security needs no stored bond,
  as the other applications state), `CONFIG_BT_TRANSMIT_POWER_CONTROL=y`,
  `CONFIG_BT_CTLR_PHY_2M=y` (`TEST_PHY` is 2M) and `CONFIG_BT_ATT_PREPARE_COUNT=3`, the
  hostless reflector's value. `CONFIG_BT_RAS`, `CONFIG_BT_RAS_RRSP` and `CONFIG_BT_GATT_CLIENT`
  are dropped: the first two are selected by `APP_CS_ROLES_REFLECTOR`, and the RAS responder
  discovers nothing.
- [x] **Planner export discovery in the Tag** (2026-09-20): `cs_reflector_tag/CMakeLists.txt`
  has the hostless applications' `config/cs_generated_config.c` lookup, with `config/.gitkeep`
  as in both of them, and `-DCS_CONFIG_SOURCE` still takes precedence. Both paths were built.

### 3.2 Decision: large reports

- Moved to future work (§11, 2026-09-18).

### 3.3 Hardware verification

Observed 2026-09-18 (`cs_hostless_initiator` ↔ `cs_reflector_tag`, normal images, default
configuration), open. Both are against the standalone Tag image; repeat them on the `cs_roles`
Tag (§3.1, 2026-09-20), which restarts the link itself:
- [ ] The RAS buffer failure persists on the `cs_roles` Tag image. Tag RTT log of 2026-09-23
  (`cs_reflector_tag` ↔ hostless initiator, no planner configuration, `TEST_*` values,
  negotiated antenna configuration 0 at 1 path, procedures every 125 ms): 87 procedures are
  delivered, then `ras_rrsp: Failed to allocate buffer for procedure N` from 88 onward, once per
  procedure with no recovery, while the Tag's own CS procedures keep completing
  (`94 complete, 0 aborted`). Originally seen on the standalone image at about 23 s, where the
  link then ended with supervision timeout (0x08).
  - It is intermittent, not a limit reached at a fixed count. The second session in the same
    capture, after the reboot and on the same images and pair, ran 652 procedures over 85 s at
    the same 125 ms cadence with no `ras_rrsp` message at all. So a session either latches into
    the failure and never leaves it, or never enters it.
  - A steady per-procedure loss rate is ruled out by those two sessions alone. Latching at
    procedure 88 implies about 1 in 88; 652 clean procedures at the same one buffer then has
    a vanishing probability under that rate. The trigger is a rare conditional event, not
    attrition, so the fault is a buffer lost at some specific moment rather than a slow leak.
  - With `CONFIG_BT_RAS_RRSP_RD_BUFFERS_PER_CONN=4` on the Tag (2026-09-23, diagnostic in
    `cs_reflector_tag/prj.conf`): one session ran 1492 procedures over 190 s with no `ras_rrsp`
    message. That is 2.3x the longest clean one-buffer session, but it is still one session, and
    a one-buffer session already ran clean, so it does not yet separate "four buffers absorbed
    the loss" from "this session never triggered". Repeated connect/disconnect cycles are what
    separate them: each cycle is one trial, and the one-buffer rate to beat is 1 latched session
    in 2. Note also that with four buffers a single lost buffer is silent, so absence of the
    message no longer means absence of the fault.
  - Mechanism: `CONFIG_BT_RAS_RRSP_RD_BUFFERS_PER_CONN` is 1 in all three reflector images
    (`cs_reflector_tag`, `cs_hostless_reflector`, `cs_client`); the NCS Kconfig allows 1–10.
    With one buffer, procedure N+1 can be staged only after N is sent and freed, and
    `ras_rd_buffer.c` drops the whole procedure when the allocation fails.
  - What the log shows is not slow drain: within the bad session 87 procedures succeed and then
    every later one fails, and the good session never fails at the same rate. Steady back
    pressure would fail intermittently in both. A buffer that is lost once and never freed fits
    both halves, and with one buffer there is no headroom to absorb it. Next: the initiator's
    log of the same run, to see whether the RREQ side stopped fetching before or after the
    first failure, and what the trigger was.
  - This is the same mechanism as the minimum-RAS-procedure-interval item below; treat them
    together, and try `RD_BUFFERS_PER_CONN` above 1 as part of it.
  - A second, separate loss mode (2026-09-23, from the initiator side in `ble-channel-sounding`): sporadic
    `RAS_DATA_LOST` at a low steady rate, with recovery every time. Two recordings at
    `RD_BUFFERS_PER_CONN=4` and no Tag allocation failure at all:
    `session_hostless_cs_23_Sep_2026_13_15_26.h5` lost about 19 of 1708 procedures (1.1%,
    21 `RasDataLostPacket`, 1707 local subevents against 1688 from the reflector), and
    `session_hostless_cs_23_Sep_2026_13_33_17.h5` 5 of 913 (0.55%, 936 against 931). It accrues
    steadily rather than in bursts and reflector data keeps arriving to the end, so it is not
    the latch above: the latch loses everything after one point, this loses a fraction
    throughout. Four buffers do not remove it, which means it is not reflector buffer
    exhaustion. Unexplained; needs the reflector's view of the same procedures to say which end
    drops them.
- [x] The Tag no longer stops advertising for good (user's observation and the same log,
  2026-09-23): it comes back and runs again. The standalone image released its connection
  reference itself and waited for `recycled`; the suspect was NCS `bt_ras_rrsp_free()`, which
  drains the RAS work queue from the disconnected callback while a notification may still wait
  for transmit buffers, so the connection was never recycled. The move to `cs_roles` (§3.1,
  2026-09-20), which restarts the link itself, is what removed it.
  - Closed 2026-09-24. The open question here was a Tag that showed a boot banner about 1 s
    after an allocation failure, with no `<err>`, fatal handler output or `State link lost`
    before it, and the reasoning below could not account for it. It was not a fault: these were
    manual resets and reflashes, and the banner with nothing after it was a reflash into a build
    that had lost its board configuration and took the `check_antennas()` early return (§15.5,
    §15.6). The missing lines were dropped by `LOG_BACKEND_RTT_MODE_DROP` with the viewer
    detached across the flash, not by `CONFIG_LOG_MODE_DEFERRED` on a reset. The Tag has not
    reset on its own since (user, 2026-09-24).
    The earlier reasoning, kept because it stays true: `LINK_FAILURES_BEFORE_REBOOT` in
    `cs_reflector_tag/src/main.c` needs three `CS_ROLE_FAILURE_CONNECT` states in a row, so the
    application's own reboot path cannot produce a reboot from RUNNING; and
    `CONFIG_RESET_ON_FATAL_ERROR` is not set in the Tag build, so a caught fault halts with a
    dump rather than resetting. Should an unexplained reset appear again, the boot reset-cause
    line in §10 item 11 is what settles it in one line.
- [ ] The Tag stays up but cannot be reconnected after a disconnection, without an error or
  the five-failure reboot (user, 2026-09-24). The move to `cs_roles` did not remove the suspect
  above: with `CONFIG_BT_RAS_RRSP_AUTO_ALLOC_INSTANCE=y`, NCS still frees the instance with
  `bt_ras_rrsp_free()` from its own disconnected callback, on the system work queue, and that
  callback sorts before `cs_role_link_callbacks` (`zephyr.map`). A stalled
  `k_work_queue_drain()` there means `cs_roles` never gets DISCONNECTED: no `State link lost`, no
  restart, no ERROR for `main.c` to count, and the connection object is never released. The
  counter line, also on the system work queue, stops with it. Fix (2026-09-24): the Tag sets
  `AUTO_ALLOC_INSTANCE=n`, as `cs_client` does, so `cs_roles` allocates at START and frees in
  `cs_role_reflector_release()` on the role thread. Built, not verified on hardware. To verify:
  repeated disconnect/reconnect cycles, with `State link lost` and `State advertising` after
  each. `cs_hostless_reflector` follows the Tag since 2026-09-27 (`AUTO_ALLOC_INSTANCE=n`,
  `RD_BUFFERS_PER_CONN=4`, and the Tag's `TEST_*` procedure parameters with A1:B1 as its
  fallback); `tests/cs_reflector_test` still uses the automatic instance.

Roles and timing:
- [ ] `cs_client` initiator ↔ `cs_hostless_reflector`, then `cs_client` reflector ↔
  `cs_hostless_initiator`, then `cs_hostless_initiator` ↔ `cs_reflector_tag`.
- [ ] Short procedure intervals with RAS: find and document the minimum procedure interval per
  configuration size (the RAS procedure buffer holds one procedure).
- [ ] CS event against the ACL interval. `cs_client` initiator ↔ Tag refused a 37000 us subevent
  in a 37.5 ms interval (procedure interval 2, `max_procedure_len` 66 and 80) with
  `CS_CONFIG_FAILED`, HCI 0x20 at procedure enable, after the configuration and CS security
  succeeded; the Tag logged the configuration and no procedure enable
  (`recordings/session_cs_initiator_24_Sep_2026_17_07_48.h5`, `..._25_Sep_2026_07_50_45.h5`).
  Every run that worked left at least 1 ms of the interval (10625 in 18750, 14000 in 25000,
  16000 in 30000 us), so the planner now requires the CS event, capped at `max_procedure_len`,
  to be `CS_EVENT_LEAD_US` (1000 us: `Offset_Min` 500 us plus the SDC's about 0.5 ms set-up)
  shorter than the interval (`validate()`, both planners, 2026-09-25). Not isolated: those runs
  also changed the procedure length and interval. To verify: the refused configuration with
  only the subevent at 36500 us starts; 37000 us is refused.
- [ ] STOP during RAS notifications; link loss during STOP; the STOP timeout path
  (`RAS_DATA_LOST` + OK/`_STOP_TIMEOUT`).
- [ ] Finite `max_procedure_count`: initiator `CS_PROCEDURES_COMPLETE` and
  `CLIENT_STATE(STOPPED, TEST_COMPLETE)` after the last RAS data; the reflector reports the
  peer's disable as `STOPPED(PEER)`.
- [ ] Stack high-water marks with `CONFIG_THREAD_ANALYZER`; resize the role, event, host link and
  system work queue stacks.

Discovery and failures (`cs_client`):
- [ ] Two peers with identical names; 32-byte configured name; unnamed peers.
- [ ] Cancel while connecting; encryption failure; host loss.
- [ ] Scan congestion with many nearby advertisers and long names; retry after a failure.

Antennas:
- [ ] Single-antenna `cs_client` with a multi-antenna peer (4 paths); selections beyond the local
  antennas are rejected at `SET_*_CONFIG`.

Radio test build:
- [ ] RX and RX sweep `RADIO_TEST_STATS` (baseline, periodic, final) against a known transmitter.
- [ ] uart30 as the DK's second virtual COM port, with hardware flow control at 921600 baud.

Host application:
- [ ] `ble-channel-sounding` end to end against `cs_client` (connect, sync, apply, start/stop, recording, MAT
  conversion) and in hostless mode against `cs_hostless_initiator`.

## 4. Planner help views

Today each planner setting explains itself only through a one-line tooltip (`CS_CONTROL_HELP`,
`SCHEDULE_CONTROL_HELP` in `python/ble_channel_sounding/views/cs_view.py` and `python/ble_channel_sounding_planner/view.py`).

- [x] **Help view per settings tab.** Next to the settings forms (Connection, CS modes, Schedule,
  Channels, Host), add a help view that gives the general definitions for that tab: what the
  group of settings controls and how the fields relate (for Connection: connection interval,
  peripheral latency, supervision timeout and how they bound CS procedure timing).
- [x] **Detailed help per setting.** A second view with a longer version of each tooltip, filled
  from the same key as the tooltip, in three parts:
  - What it defines: "This setting defines <parameter> in <HCI command / LL procedure>."
  - Where the standard defines it: the Core Specification volume, part and section (and the
    HCI parameter name).
  - Effect of a change: what else changes in the plan (step, subevent or procedure duration,
    steps per subevent, timeouts, validation notes) and which other controls it enables or holds.
  Selecting a control, or hovering it, shows its entry. Keep the text in one place so the tooltip
  stays the short form of the detailed entry.
- [x] Apply to both `ble_channel_sounding` and the standalone `ble_channel_sounding_planner`; GUI tests that every control has a
  tooltip and a detailed entry; describe the views in `python/ble_channel_sounding/planner/README.md` and
  `python/ble_channel_sounding_planner/README.md`.

## 5. Planner: separate client settings from example values

Today the settings tabs mix values sent to the client with values that only shape the prediction
(for example "Illustrative main run" sits in CS modes, "Preview instances" in Schedule, "Example
seed" in Channels). A user cannot tell from the layout what reaches the client.

### 5.1 Decisions (2026-09-17)

- **No separate tab.** Every value that is not sent to the client (bridge) or exported to C stays
  on its own tab, in a panel headed **"Example config values selected by the controller"** below
  that tab's sent settings. (A *Visual only* tab was tried and rejected.)
- **Negotiated values are among them.** The host cannot send T_IP1, T_IP2, T_FCS, T_PM, the
  selected connection interval or the subevent and event spacing: the HCI CS configuration and
  procedure parameter commands have no fields for them (Zephyr `bt_le_cs_create_config_params`,
  `bt_le_cs_set_procedure_parameters_param`). The controllers choose them from both devices'
  capabilities and report them in the configuration-complete and procedure-enable-complete
  events. They stay editable, so the prediction can explore them, and a report still overwrites
  them.
- **Editable while locked.** The example panels stay editable while a run locks the settings
  (`set_locked`) and in hostless mode (`set_readonly`), because their values never reach the device.
- **Only relevant controls are active.** A control that the selected modes do not use is read-only
  and shows its default (§5.3). Its default is the firmware default where one exists
  (`cs_utils` `cs_config.c`, `HOST_DEFAULTS`, the Zephyr sample values used for creation fields),
  otherwise the Core Specification mandatory-to-support value (§5.4).
- The JSON file layout does not change (keys stay where they are), so old files load unchanged.

### 5.2 Example panels

Confirmed not used by `planner/bridge.py`, `planner/export_c.py` or `ble_channel_sounding_planner/export_c.py`
(`EXAMPLE_FIELDS` in `model.py`).

| Tab | Controls in the panel |
| --- | --- |
| Connection | Selected interval (`connection.interval`), ACL activity example (`connection.activity_us`), CS offset from anchor (`event_offset_us`) |
| CS modes | Illustrative main run (`main_steps`); T_IP1, T_IP2, T_FCS, T_PM (`configuration.t_*_time_us`); T_SW, T_SW_IPT (`t_sw_us`, `t_sw_ipt_us`; declared in each device's capabilities) |
| Schedule | Fresh-step workload (`target_steps`), Subevents / event, Subevent spacing, CS event spacing (`procedure.subevents_per_event`, `subevent_interval`, `event_interval`), Preview instances (`preview_count`) |
| Channels | Example seed (`channel_seed`) |

- Each tooltip says the value is not sent and, for negotiated values, which report sets it.

### 5.3 Relevance rules

The existing `unused_fields` / `unused_host_fields` / `update_mode_controls` mechanism holds unused
fields at their defaults for the mode combination. Extend it so every rule below both disables the
control **and** resets it to the default, on every tab and example panel:

| Condition | Read-only controls | Status |
| --- | --- | --- |
| No sub-mode | Minimum/Maximum main run, Illustrative main run | Done |
| No Mode 1 or 3 | RTT sequence, SNR control initiator/reflector | Done |
| No Mode 2 or 3 | T_IP2, T_PM, IPT, Antenna configuration, T_SW, T_SW_IPT, Preferred peer antenna | Done |
| IPT off | T_SW_IPT | Done (`inactive_fields`) |
| IPT requested | T_SW | Done (`inactive_fields`) |
| CSA #3b | #3c shape, #3c jump | Done (`inactive_fields`) |
| Subevents / event = 1 | Subevent spacing (0, as validation requires) | Done (`inactive_fields`) |
| Reflector operation mode | Creation context | Done (`unused_host_fields`, `ble_channel_sounding` only) |
| Peripheral GAP role | Peripheral prefixes | Disabled, text kept in CS setup (kept on purpose: the value is preserved, and it is ignored for a peripheral) |

- The reflector as configuration creator (decided 2026-09-18) moved to future work (§11,
  2026-09-19): the initiator keeps creating the configuration.

### 5.4 Default values

- Controller-selected timing has no firmware default, so `Scenario()` uses the mandatory values:
  T_IP1 145 µs, T_IP2 145 µs, T_FCS 150 µs, T_PM 40 µs. These are confirmed against the
  Bluetooth Core Specification Channel Sounding timing tables and the CS test-suite default
  parameters. T_SW and T_SW_IPT are device-specific (permitted values 0/1/2/4/10 µs), so the
  planners retain today's 2 µs as an explicitly documented prediction assumption.
- Update the tests, notes and README examples whose numbers depend on the old timing defaults.

### 5.5 Steps

1. [x] Confirm the mandatory values (§5.4) and change the `Scenario()` defaults in `ble_channel_sounding` and
   `ble_channel_sounding_planner`.
2. [x] Example panels on each tab (§5.2); update tooltips and tab notes.
3. [x] `set_locked` / `set_readonly` keep the example panels editable.
4. [x] Relevance rules with reset to defaults (§5.3), in `model.py` and the view.
5. [x] Apply 2–4 to the standalone `ble_channel_sounding_planner` too.
6. [x] Tests: GUI tests that look up controls by tab (`test_planner_gui.py`, `test_cs_planner_gui.py`
   tab count), a test that every example key is absent from the bridge packet and C export,
   relevance/reset tests per rule, locked/read-only editability, loading an old plan file.
7. [x] Documentation: `python/ble_channel_sounding/planner/README.md`, `python/ble_channel_sounding_planner/README.md`.

## 6. Configuration-view workspace chrome

- [x] Host the Configuration actions in a movable/detachable `QToolBar` owned by the
  Configuration view; keep the standalone planner toolbar available inline and avoid global
  application docking.
- [x] Make the upper application configuration section collapsible with a compact summary of
  port, baud rate, mode, role, recording state and session state.
- [x] Disable configuration synchronisation and planner reset while a session is started;
  restore both actions after the session stops.

### 6.1 Mode-specific Configuration views (decided 2026-09-19)

The existing Configuration tab remains the mode-specific workspace. It switches between the CS
configuration view and the Radio Test view; it does not gain a separate General tab group.

**General toolbar.** Operation mode is selected in the top general toolbar with exactly three
choices: **CS**, **CS Hostless** and **Radio Test**. Console and host log levels are beside it in
the same toolbar. Selecting a mode changes the configuration view and the Results view as
appropriate.

**CS configuration.** The first CS tab is CS setup. It contains the Bluetooth name, GAP role,
CS role (initiator or reflector), and scanning name prefixes. Prefixes are enabled only for a
central GAP role and are not part of Radio Test. The remaining CS tabs and the planner's timing
visuals keep their existing design.

**Radio Test configuration.** Radio Test uses the same two-column visual language as CS: grouped
settings tabs on the left, the same lower `About this tab` / `Setting details` explanation pane,
and an explanatory operation visual on the right. The settings are grouped into Test, Channel,
Timing and FEM tabs using the same direct form-row style as CS. Inactive values remain serialized
and are disabled rather than discarded. The right-hand preview explains fixed-channel, sweep,
duty-cycle and sleep behavior; live RX measurements remain in Radio RX results.

**Implementation status (2026-09-19): complete.** The toolbar selectors, CS setup tab, mode
switching, Radio Test grouped settings, matching lower help pane, explanatory preview, validation,
preset round trips and radio-results locking are implemented. GUI coverage verifies toolbar
ownership, CS-only field placement, mode transitions, inactive-field retention and Radio Test
help behavior.

**Acceptance criteria.** No General tab is created by the integrated app. Mode and log selectors
are visible in the top toolbar only; CS-only identity/GAP/role/prefix controls stay in CS setup;
Radio Test has the same left-settings/right-visual structure; and existing packets, presets,
CRC behavior, validation and Results behavior remain unchanged.

## 7. Results history view

Commit `4be2741` replaced the Steps, Subevents, Reports and Log tabs of the Results view with one
*History* tab (`python/ble_channel_sounding/views/results_view.py`, `draw_history`).

- [x] Timeline of every packet in the store, sent and received: host commands are added through
  `packet_sent` in `app.py`, and HDF5 captures replay `raw/frames` in both directions
  (`recorder.load(..., with_direction=True)`). Columns: time from the first packet, direction and
  type, procedure, summary.
- [x] Filters: free-text search, type check boxes (Subevents, Reports, Logs, Other) and a
  procedure-counter range. Subevent rows collapse and expand into one summary line per step.
- [x] Empty Results tabs show one shared status text (`EMPTY_RESULTS_STATUS`).
- [x] The tree was rebuilt from the whole store on every redraw and filter change. Replaced by
  the model/view window in §7.2, which also removes this cost.
- [x] The Steps, Subevents, Reports and Log widgets are no longer separate visible tabs; their
  detail is shown for the selected History row.
- [x] Tests: `ResultStore` direction and timestamp, `recorder.load(with_direction=True)`, History
  filtering (search, type, procedure range) and step children in GUI tests.
- [x] Documentation: the Results tab list is documented in `python/ble_channel_sounding/README.md`.

### 7.1 Session history (decided 2026-09-18)

Goal: after STOP, the user can browse the whole session in History, as if every packet were
kept, while memory stays bounded as today (`MAX_PACKETS` = 200 in `results.py`).

A **session** is one run: it starts when START is pressed and ends when the run finishes (STOP
confirmed, procedures complete, or a failure; `run_finished` in `session.py`). These are the same
bounds as a `RunRecorder` recording. The configuration cannot change during a run
(`Session.apply()` refuses while running), so a session has exactly one applied configuration.

**Hostless mode is the exception.** It has no START or STOP: *Connect* takes the place of START
and *Disconnect* the place of STOP. The session starts with Connect, and the confirmation is the
port opening (`Session.connect(hostless=True)` reaching `HOSTLESS CS`). It ends with Disconnect,
or when the port is lost. The records the hostless initiator resends when the port opens (§1.3)
are the first frames of the session. If the port fails to open, the previous session stays in
Results and History. Today `session_started` is emitted, and Results cleared, before
`transport.open()`; in hostless mode the clear moves after a successful open.

- **Always on.** Every frame sent or received during the session is appended to a
  temporary session history file, seeded with the link context records (`session.context`:
  capabilities, CS configuration, procedure enable complete, FAE) as `RunRecorder` is. This does not depend on the *Recording* setting and also runs
  in hostless mode, where the Recording group is disabled. It is separate from the user's
  recordings; *Save session…* keeps it (§7.3).
- **Lifetime.** Pressing START opens a new history file, which receives the START command and
  everything after it. The switch happens when the client confirms START (the START response,
  `run_started("started")` in `session.py`): the previous session's history is discarded, and
  the Results view (`ResultStore`, History and every Results tab) is cleared and shows the new
  session. If START is refused or fails before confirmation (not synced, `BUSY`,
  `CONFIG_MISMATCH`), the new file is discarded and the previous session stays in Results and
  History, as `RunRecorder` discards a run that never started (`recording_discarded`). After a
  session ends, its history stays browsable until the next confirmed START or until the app
  closes. Clearing at `session_started` (`clear_session_reports()`) is kept for a new serial
  connection. A link lost and
  re-established inside a run (auto restart) stays in the same session. The file is created unlinked (`tempfile.TemporaryFile`), so it
  disappears on exit or crash and never needs cleanup.
- **Content.** Raw frames, as in HDF5 `raw/frames`: index, host time, direction, wire bytes.
  A temporary SQLite index stores per-frame metadata (file offset, time, kind, procedure key) on
  disk, allowing random access and filtering by type and procedure without retaining the full
  index in application RAM. Only the live tail is cached in memory. Host messages are records of
  the same history (§7.6).
- **Writer.** A background thread, like `RunRecorder`, fed from `Session` next to
  `recorder.record()`. A write failure disables the history with a status message; it never
  stops the run.
- **Disk bound.** The file is split into segments. Above a size limit (a setting, default 2 GB)
  the oldest segment is dropped, and History says where the kept history starts. Mode 3 with
  4 paths at short intervals reaches hundreds of KB/s, so a long session can hit it.

### 7.2 History view: live tail and full browsing

- **Running**: as today. History follows the newest packets and shows at most the last 200 rows.
- **Not running** (stopped, idle, disconnected, or a capture opened): History browses the whole
  session history. Refined 2026-09-22 (§7.9): after STOP the view leaves live mode and asks for
  *Save session…*, and full browsing happens in replay over the saved file. The scroll bar spans all matching packets. Only a window of at most 200
  decoded rows is held; scrolling or jumping past its edge decodes the next window from the file.
  This replaces `draw_history()` rebuilding a `QTreeWidget` with a `QTreeView` on a lazy model
  (`rowCount` = matching packets, rows decoded on demand, step children decoded when expanded).
- **Filters** apply to the whole history when browsing a stopped session or playing an opened
  recording. Type and procedure range query the disk-backed index and are immediate. Text search decodes
  frames in a cancellable worker and fills matches as they are found, with a progress indication.
  While a true live run is active, these browsing controls are disabled so the view remains an
  unfiltered tail.
- **Same view over captures.** *Open capture…* of an HDF5 recording uses the same model over its
  `raw/frames`, so a loaded recording is browsable in full, not only its last 200 packets.
- **Showing the session again.** Selecting a subevent or procedure row that is no longer in the
  `ResultStore` loads that procedure's frames from the history into the PBR, RTT and step detail,
  so an old procedure can be inspected after STOP. This absorbs the open item above about the
  hidden Steps, Subevents, Reports and Log widgets: they become the detail pane of the selected row.
- On the next START, History returns to the live tail.

### 7.3 Save session (decided 2026-09-18)

- **Action.** *Save session…* in the History tab and next to the recording actions in the
  Recording group. It is enabled whenever the session history is not empty, including while
  running (it saves the frames up to that moment) and in hostless mode. When *Recording* was on
  for the whole session, the recording already holds it, and the action says so and offers to
  open that file instead.
- **Format.** The same HDF5 recording format as `RunRecorder` (`format_version` 1), built by
  replaying the history frames: `raw/frames` in both directions plus the decoded tables, so
  *Open capture…*, `ble-channel-sounding --simulate` and MAT conversion work unchanged. New root attributes:
  `source = "session"` (recordings get `"run"`), `history_truncated` and the host time of the
  first kept frame when segments were dropped (§7.1).
- **Configuration.** `/config` holds the session's configuration, as in a recording. The planner
  JSON is saved beside the file, as for recordings. In hostless mode there is no host configuration:
  `/config` is left out and the negotiated configuration is in `/reports`. This is new for the
  format, since recording is disabled in hostless mode today; readers and MAT conversion must
  accept it.
- **Name and place.** The recording folder, `session_<mode>_<start time>.h5`, in a save dialog.
- **Writing** runs in a background worker with progress and cancel. A cancelled or failed save
  deletes its partial file. The live history keeps being written meanwhile.
- **Warning.** A confirmed START discards the previous session without asking. Closing the app with an
  unsaved, unrecorded session asks *Save session / Discard / Cancel*.

### 7.4 Run description (decided 2026-09-18)

- **Dialog.** When a run with *Recording* on ends (`run_finished`), a non-modal *Run description*
  dialog opens: a multi-line text field, *Save* and *Skip*. Closing it is *Skip*. It does not
  block the Results view. If the app closes while it is open, the typed text is saved.
- **Save session.** The *Save session…* dialog (§7.3) has the same description field, so
  unrecorded runs and hostless sessions can be described too.
- **Edit later.** *Edit description…* for the last recording (Recording group) and for an opened
  capture (Results), prefilled with the stored text.
- **Toolbar (decided 2026-09-20, done).** The Session tab's *Edit description…* button becomes the
  *Describe session* action (pencil icon) of the session-actions toolbar, next to *Record from now*,
  so a running recording can be described where it was started. It is enabled by having something to
  describe — a session, a loaded capture or an existing description — and needs no link. The notes it
  takes prefill the closing *Run description* dialog, as they already outrank the *Recording* field
  when a session is saved.
- **File.** Root attributes `description` (UTF-8 string, empty when none) and
  `description_updated` (UTC ISO time). `RunRecorder` has closed the file when the dialog
  appears, so the description is written by reopening it in append mode (`h5py.File(path, "a")`).
  A write failure is shown and the text stays in the dialog for another try.
- **Replay.** Opening a recording (*Open capture…*, `ble-channel-sounding --simulate`) shows the description
  above the Results tabs, elided to one line with the full text in a tooltip, and in the History
  tab header.
- **MAT.** `h5_to_mat.convert()` writes a top-level `description` variable as a `char` row
  (newlines kept; empty `char` when none), besides `meta.description` from the root attributes.
  `char`, not a MATLAB `string` object: `scipy.io.savemat` writes only `char`, and it works in
  every MATLAB version and in Octave.
- [x] Description field in the Recording group before START, for setup notes written before the
  run.
- [x] Use that field to prefill the end-of-run dialog.

### 7.5 Steps

1. [x] Session history writer: segments, disk-backed index with bounded live tail, context seeding, lifetime from START
   (switch and Results clear at the START confirmation; refused START keeps the previous session;
   hostless: Connect/port open → Disconnect/port lost), disk bound (§7.1), with tests (append/read back, switch at
   confirmation, refused START, segment drop, write failure).
   - [x] The disk bound as a setting (Recording group, *Session history*), and the Session tab
     showing where the kept history starts (2026-09-19).
2. [x] Lazy History model and `QTreeView`: live tail while running, full browsing otherwise,
   200-row decoded window (§7.2), with a GUI test that scrolls a history of more than 200 packets
   after STOP.
3. [x] Filters over the full history: index filters, cancellable text search.
4. [x] HDF5 captures through the same model.
5. [x] Detail pane for the selected row, loading old procedures from the history; remove the
   hidden Steps, Subevents, Reports and Log tabs' separate filling.
6. [x] Performance check: History and writer at mode-3, 4-path report rates in the simulator; no
   dropped frames and no GUI stalls.
7. [x] *Save session…* (§7.3): replay into the recording format, root attributes, background
   worker, cancellation, hostless files without `/config`, and tests that saved sessions reopen
   and preserve both directions.
   - [x] Add the unsaved-session close prompt.
   - [x] Default name and folder, the Recording-group action, the recorded-session notice, the
     planner JSON beside the file, and no saving while a capture is shown (2026-09-19).
8. [x] Run-description storage and editing (§7.4): the Recording-group field, append-mode
   write, *Edit description…* for recordings/captures, replay display, MAT `description`, and
   tests for write/reread and MAT conversion.
   - [x] Add the non-modal end-of-run dialog and the description field in *Save session…*;
     add skip/close-while-open coverage.
9. [x] Documentation: `python/ble_channel_sounding/README.md` covers the Results tabs, session history, disk
   use, Save session, current run-description behavior, and HDF5/MAT metadata (`source`,
   `history_truncated`, `description`, `description_updated`, MAT `description`).
10. [x] Host messages in the session history and in recordings (§7.6, steps there).
11. [x] Peer console input (§7.7, steps there).
12. [x] History in the Session tab (§7.8, steps there).

### 7.6 Host messages in the session history (decided 2026-09-19)

Goal: a saved session or recording shows what the host app said while it happened (a refused
START, a link error, a disabled history, a failed write), next to the frames it was about. Today
these messages go only to the status bar (`show_message` in `app.py`) and the Session log
(`SessionLogView.add_text`, for example `app.py` near the START refusal), and are lost when the
app closes or the log passes 200 lines. The history holds only link frames
(`SessionHistory.append`, `direction` `received`/`sent`).

- **Record.** A third record kind, `host`: index, host time (same clock as the frames), level
  (`info`, `warning`, `error`), source and UTF-8 text. It shares the frame index sequence, so it
  sorts where it happened. On disk it is a segment record with direction code 2 and the text as
  payload; the disk-backed index gets kind `host` and no procedure key. It counts towards the disk
  bound and is dropped with its segment like any frame.
- **What is recorded.**
  - Every `add_text` message, with its level.
  - Every `show_message`. `show_message` gains a `level` argument (default `info`); the callers
    that report failures (session history disabled, save failed, START refused, configuration not
    valid, transport errors) pass `warning` or `error`.
  - `ble_channel_sounding` Python `logging` records at WARNING and above, through a `logging.Handler` installed
    by the app. Source is the logger name. The handler must be thread-safe and must not log
    through `logging` itself (history write failures are reported through `history_error` only).
  - Source is `host` for app messages, the logger name for `logging` records.
- **Which history.** A message goes to the current history, the one Results shows. A refused
  START therefore lands in the previous session, which it is about. With no history open (before
  the first session) the message is kept in memory and shown in the Session tab (§7.8).
- **HDF5.** `/host_log`, a chunked table like the others: `timestamp` (float64, host time),
  `level` (uint8), `source` and `text` (variable-length UTF-8). `RunRecorder` writes it while
  recording (the app feeds it next to the history); `save_hdf5` replays it from the history.
  Optional for readers: files without `/host_log` load as today, so `format_version` stays 1.
  `recorder.load()` returns host records in time order with the frames.
- **MAT.** `h5_to_mat.convert()` writes `host_log` as a struct array with the same fields
  (`text` and `source` as `char` rows), empty when absent.
- **View.** History gets a *Host* type filter. Host rows show time, `host` in the direction
  column, level and text; warnings and errors are coloured as in the Session log and are never
  hidden by the type filter. Opened captures and `ble-channel-sounding --simulate` show them the same way.

Steps:

1. [x] `SessionHistory.append_host(level, source, text, timestamp=None)`, record format, index
   kind, segment drop; tests: round trip, ordering with frames, segment drop, write failure.
2. [x] App wiring: `show_message(level=…)`, `add_text` and the `logging` handler feed the current
   history; tests: refused START lands in the previous session, no history before the first
   session, handler does not recurse on a history error.
3. [x] `/host_log` in `RunRecorder` and `save_hdf5`, `recorder.load()` support, file without
   `/host_log` still loads; tests in `test_recorder.py` and `test_session_history.py`.
4. [x] MAT `host_log` struct array; test in `test_recorder.py`. `char` rows and a 1×0 variable
   when absent since 2026-09-19.
5. [x] History *Host* filter and row rendering, over live history and captures; GUI test.
6. [x] Documentation: `python/ble_channel_sounding/README.md` session history and the HDF5 and MAT format
   sections (`/host_log`, MAT `host_log`).

### 7.7 Peer console input (decided 2026-09-19)

Goal: the console of the other device (a reflector Tag, `cs_hostless_reflector`, or any board
that is not on the host link) is kept in the same session history, so a failing peer is visible
next to the initiator's frames. Example: on 2026-09-19 the Tag logged `TEST FAIL remote CS
capabilities` with HCI `0x2f` and disconnected (reason `0x16`) on every link, and none of it
reached `ble-channel-sounding`.

- **Input.** An optional *Peer console* serial port and baud rate in the top configuration panel, saved with
  the host settings, not part of the client configuration or its CRC. It is opened with the
  session (START confirmation, or hostless Connect) and closed with it, read-only, on its own
  reader thread. A port that fails to open or is lost is a warning host message; it never stops
  the run.
- **Records.** Each console line is a §7.6 host record with source `peer`, host receive time, and
  level parsed from the Zephyr `<inf>`/`<wrn>`/`<err>`/`<dbg>` tag (`info` when there is none).
  Multi-line hexdump continuation lines are joined to the line before. The device's own
  timestamp stays in the text; no clock alignment is attempted.
- **View and files.** As §7.6: History rows with source `peer`, a *Peer* filter next to *Host*,
  `/host_log` and MAT `host_log` with `source = "peer"`. The Session log shows the lines too.
- Out of scope: RTT consoles, and sending anything to the peer.

Steps:

1. [x] Host settings field and peer-console controls (port, baud, off by default), saved in plan
   files; help text.
2. [x] Line reader thread: open/close with the session, level parsing, hexdump joining, loss and
   open failure as warnings; tests with a fake serial port. Level parsing after the
   `app_log`/Zephyr timestamp prefix and warnings instead of errors since 2026-09-19.
3. [x] Feed into the history, recordings and Session log as source `peer`; History *Peer* filter;
   tests for ordering with frames and for the saved `/host_log`.
4. [x] Documentation: `python/ble_channel_sounding/README.md` (Peer console, `source = "peer"`).

### 7.8 History in the Session tab (decided 2026-09-19)

Discussed on 2026-09-19 together with §7.6, but left out when §7.6 and §7.7 were written down.
Today the same stream of records has two views: the *Session* tab (`SessionLogView`, plain text,
last 200 lines, filters apply only to new lines, not saved) and *Results → History* (lazy tree
over the session history file or an opened capture, §7.2). History moves into the Session tab and
replaces `SessionLogView`.

- **Session means whatever is open.** The Session tab shows the live session while one runs or
  after it ends (§7.1 lifetime), and an opened capture (*Open capture…*, `ble-channel-sounding --simulate`) when
  one is loaded, through the same model (§7.2 "Same view over captures"). The tab says which one is
  shown (live session, or the capture's file name).
- **All the data.** The timeline holds every record of the session in order: frames sent (tx),
  frames received, and local logs (§7.6 host records, and §7.7 peer console lines). The
  sent/received/host direction is a column; warnings and errors are coloured and counted as in
  `SessionLogView` today, and never hidden by the type filter (§7.6).
- **Record detail pane.** The panel at the bottom of History shows the selected record parsed:
  the decoded packet fields (today's *Packet* tree), the steps and subevent header for a
  subevent, and the text, level and source for a host or peer record. It replaces the one-line
  text of `SessionLogView` as the way to read a record; the row summary stays one line.
- **Results** keeps the analysis views only: PBR per channel, RTT, Estimates, Controller, FAE. The
  History tab leaves Results.
- Kept from `SessionLogView`: Pause (stop following the live tail, as scrolling up does in §7.2)
  and the per-category filters, now over the whole history. Its Clear button goes: the history is
  cleared by the session lifetime (§7.1), not by hand.
- *Save session…* and *Edit description…* move with History to the Session tab.

- **Results follows the session's configuration** (decided 2026-09-19). A session has one
  configuration; for a CS session its CS modes decide which Results views are shown
  (`ResultsView.set_measurement_mode()`: PBR and RTT tabs, Estimates series, Controller rows).
  Results analyses the open session with its own procedure selector; selecting a replay-history
  procedure updates the PBR, RTT and Estimates views with that procedure and its immediate
  neighbours. Controller remains link-wide and is not changed by procedure selection.
  The selector follows the live procedure during a run; in a replay it offers every procedure the
  session history holds — read from the history index, not from the bounded decoded store — ten
  rows at a time with a scrollbar, and choosing one that is no longer decoded restores it the same
  way a history row does (decided 2026-09-21, done).
- **Capture actions in the toolbar (decided 2026-09-20, done).** *Open capture…* and *Clear* leave
  the Results configuration row for the session-actions toolbar, where they form a record-management
  group with *Record from now* and *Describe session* (folder and eraser icons). They act on the
  results view the Results tab shows — CS analysis or radio RX — need no link, and are disabled only
  while a run owns the views. The Results row keeps the procedure selector and the analysis settings.
- **Connect is the session toggle (decided 2026-09-20, cancel added 2026-09-21, teardown revised
  2026-09-22).** *Connect* opens the serial port and, while the CONNECT handshake is still unanswered,
  becomes *Cancel connection*: the user ends an attempt that will not be answered instead of waiting out
  the 10-second deadline. Once a session is open it becomes *Disconnect* with an icon of its own — a plug
  pulled out of its socket (`unplug`), not the Bluetooth-off glyph of *Disconnect link*. The second press
  ends everything: LINK_DISCONNECT, then CLOSE_SESSION, then the port; no STOP is queued first (next
  bullet). The firmware keeps an established Bluetooth link and the applied configuration across host
  sessions (`session_changed()` in `cs_client/src/cs_session.c`), so the host disconnects the link itself
  rather than the firmware doing it on CLOSE_SESSION. In hostless mode there is no command channel and the
  toggle only closes the port — the hostless *Disconnect* that stands for stopping in §7.1. The hostless
  toggle and its icon are implemented and were verified on hardware (2026-09-22).
- **No STOP in a teardown; *Close session* is dropped (decided 2026-09-22; Python side done).** Read
  against the firmware:
  for a running measurement STOP and CLOSE_SESSION are the same operation. `end_session()` in
  `common/libs/host_link/host_link.c` calls `handlers->interrupt()`, and `cs_role_core.c` dispatches both
  `CS_ROLE_MSG_STOP` and `CS_ROLE_MSG_INTERRUPT` to `handle_stop_request()`, differing only in the reported
  stop reason. STOP is therefore redundant before CLOSE_SESSION, and redundant before LINK_DISCONNECT once
  the firmware's BUSY guard goes (§10 item 9): `link_disconnect()` in `cs_client/src/cs_session.c` already
  calls `cs_role_stop()` itself, and that call is unreachable today only because the generic dispatcher
  refuses the frame while RUNNING. Consequences:
  - The *Close session* toolbar action is removed. The CLOSE_SESSION frame stays, used only by the two
    teardowns below, so the host session stops being a user-visible concept and "session" in the GUI means
    the measurement session of §7.1.
  - *Stop* becomes *Stop session* and *Start* becomes *Start session*: the pair that closes and opens a
    §7.1 session. (*End session* was the alternative name; *Stop session* was chosen for the symmetry.)
  - *Disconnect link* — disconnecting the peer — drops the radio link **and** closes the host session:
    LINK_DISCONNECT, then CLOSE_SESSION, with the serial port left open. A session whose peer is gone has
    nothing left to measure. This reverses the earlier rule that it keeps the host session open.
  - `Session.close()` splits in two — the session close (today's CLOSE_SESSION branch without
    `transport.close()`) and the port close used by the toggle and by the hostless branch. With the port
    open and no session the toolbar shows *Connect* again; pressing it sends CONNECT over the open
    transport instead of reopening the port, and the port selector stays disabled while the transport is
    open. The reconnect re-syncs the configuration the firmware retained, and *Start session* begins a new
    CS procedure.
  - Firmware: `end_session()` must stop the client in every busy state, not only RUNNING (§10 item 9,
    done 2026-09-24; the paragraph below describes the code before it).
    Today it checks `client_state() == RUNNING`, which `cs_session.c` sets only when procedures go live,
    and `cs_role_interrupt()` is gated again on `running`, so CLOSE_SESSION leaves a board that is
    scanning, advertising or still in CS setup doing exactly that with no host attached.

Steps:

1. [x] Move the History widget, its filters, *Save session…* and *Edit description…* from
   `results_view.py` into the Session tab; remove `SessionLogView` and its feed in `app.py`
   (2026-09-19: `views/session_view.py`, owned by `ResultsWidget`, shown as the app's Session tab).
2. [x] Results follows the open session's configuration (above); no History-to-Results link.
3. [x] Record detail pane: parsed view for every record kind (frames in both directions, host,
   peer); warning/error colouring and counts; Pause. Every history entry carries its level
   (`report_log.describe_*`; client `LOG_MESSAGE` levels from the `app_log` prefix).
4. [x] Session tab over an opened capture, with the source shown.
5. [x] Tests: GUI tests for the moved view (live, after STOP, capture), detail pane per record
   kind; the `SessionLogView` tests became Session-view tests (`test_report_log.py`).
6. [x] Documentation: `python/ble_channel_sounding/README.md` (Session tab, Results tab list).
- Also fixed on the way: live session rows all showed "0.000 s" because `SessionHistory` had no
  `origin`; it is now the first record after the context (context rows show "—"). Host messages
  from before the first session are shown from the in-memory store.
- Also fixed (2026-09-21): the highlighted row and the *Selected entry* pane could name different
  records. The selected row is now remembered by its stable history index (`SessionView.
  _selected_index`) instead of being read back from the tree's current index, which a model reset
  clears: a chunked search no longer drops the selection, and clearing the search puts it back.
  Selecting a row no longer re-centres the timeline when the row is already visible — the row used
  to slide out from under the pointer, so the smallest drag during a click moved the highlight to
  another record — and a selection that lands while the model is refreshing (its signals blocked)
  is shown in the detail pane rather than silently swallowed.

### 7.9 Session view cost and selection (decided 2026-09-22)

Measured on 2026-09-22 with headless harnesses over a real `SessionHistory` (offscreen Qt,
synthetic subevent reports). Nothing accumulates in the widget tree: `QApplication.allWidgets()`
stays at 3408 through a 1500-procedure run and through twelve connect/run/disconnect cycles, with
the thread and file-descriptor counts flat, so the views, timers and histories are not leaking.
What grows is the work one redraw does.

- **Browsing must not touch every row.** In the disk-backed Session model every redraw walks all
  root rows — `QTreeView` lays out each top-level row, and `scrollToBottom()` walks them again —
  and each row answered `rowCount()` with one `SessionHistory` row query
  (`SELECT … LIMIT 1 OFFSET ?`) plus a full packet decode, only to learn whether it has step
  children. The cost was quadratic in session length: one `draw()` took 148 ms at 2 000 records,
  1.30 s at 8 000 and 4.30 s at 16 000 (of 4.77 s profiled, 3.56 s in 16 002 SQLite queries).
  Row and child counts come from the index instead: a row's children are known from its kind
  without decoding it, and the browsing model reads a window of rows per query rather than one
  offset query per row (done 2026-09-22: `HistoryModel.hasChildren()`, `DISK_WINDOW_ROWS` windows
  through the new `SessionHistory.entries_from()`; the same redraw is 13 ms at 2 000 records and
  109 ms at 16 000, with 34 index queries instead of 16 002 and no decode outside the shown rows).
- **The live tail keeps only the tail.** A live run needs no whole-session view: the search and
  the filters stay disabled while the tail runs (they already are), and nothing beyond the bounded
  tail is retained or scanned. A row of the tail can be clicked and is shown in the detail pane
  (done 2026-09-22: the timeline is `SingleSelection` throughout, a live click fills *Selected
  entry* and *Record* and keeps its highlight while the tail still holds the row, and the tail goes
  on following the newest records).
- **The procedure detail is a lookup, not a scan (decided 2026-09-23).** The live click left
  *Procedure*, *Subevents* and *Steps* empty because the detail was built by walking every entry of
  the session for the ones sharing the clicked procedure key, which a live run must not do. That
  walk was never needed: `ResultStore.procedures` is keyed by the same (config, ACL event,
  counter) triple as the history index and already holds both roles' decoded reports for the run
  in progress, so the detail of a clicked row costs one dict lookup. The three tabs are filled
  from the store on every click, live tail included; a procedure the bounded store has dropped
  leaves them empty during a live run, and while browsing the indexed-entry scan stays as the
  fallback for an old replay procedure `select_procedure_key()` could not restore. The procedure
  selection and the analysis-view updates stay out of the live path (done 2026-09-23:
  `SessionView.store_reports()` and `draw_procedure_detail()`).
- **After STOP the session is saved, then replayed.** Leaving a run does not turn the temporary
  history into a browsable session in place. The view leaves live mode, and the user is asked to
  save the session (§7.3); after the save the app switches to replay over the saved file, and full
  browsing, search and procedure selection happen there. This keeps §7.2's "not running" browsing
  on a real capture rather than on the temporary segment files (done 2026-09-22:
  `MainWindow.offer_session_save()` after `run_finished`, for a session that is neither recorded
  nor already saved and only for a visible window; `session_saved()` then opens the file with
  `ResultsWidget.open_capture_path()` unless the window is closing or a run is going).
- **Two reports per procedure, by design.** A procedure carries one initiator and one reflector
  report, and only subevent results carry a procedure key — in the decoded store
  (`ResultStore.add`) and in the history index (`session_history._procedure_key`) alike. So
  `Procedure.initiator`/`reflector` cannot grow, even though nothing enforces it: with reports
  forced onto one key, a refresh re-analyses and refills the tables over all of them (90 ms at 200
  reports, 848 ms at 3 000, still linear-growing). If another report is ever bound to a procedure
  key, per-procedure retention has to be revisited first.
- **One highlighted row at a time.** The timeline is `SingleSelection` while browsing and the
  selection model only ever holds one row (verified by clicking rows in turn and reading
  `selectedRows()`), but several rows stay highlighted on screen. `draw()`, `_select_row()` and
  `_clear_history_selection()` move the highlight with the selection model's signals blocked, and
  `selectionChanged`/`currentChanged` are what make the view repaint the rows the highlight left,
  so the old rows keep their painted highlight. Moving the highlight repaints the timeline
  (done 2026-09-22: the three places share `SessionView._silent_selection()`, which repaints the
  viewport when it restores the signals).

## 8. CS phase measurement period (T_PM)

### 8.1 Goal

Scope (decided 2026-09-19, after the §8.4 step 1 runs): the question is whether a longer phase
measurement period gives an averaging gain. Only T_PM (10, 20 or 40 µs per tone; 40 µs
mandatory) can: T_IP1, T_IP2, T_FCS and T_SW are gaps (turnaround, retuning, antenna switch)
and measure nothing, and the mode-0 tone T_FM is fixed at 80 µs by the spec (the only mode-0
control is `mode_0_steps`, 1–3, already in the configuration). The spec leaves how the PCT is
computed over T_PM to the implementation, so whether the SoftDevice Controller averages over
the whole window is settled by the user's experiments once T_PM can be set (decided
2026-09-19: no analysis tool in this plan). The other timings are out of scope; the text below
records how the study got here.

Original goal:

Study how the CS step timings affect performance, including values the reflector does not
report as supported. The host has no parameter for them: the controllers choose T_IP1, T_IP2,
T_FCS and T_PM from the optional times both devices report in their CS capabilities
(`t_ip1_times_supported`, `t_ip2_times_supported`, `t_fcs_times_supported`, `t_pm_times_supported`
bit masks; the mandatory 145/145/150/40 µs are always supported), and use the reflector's
`t_sw_time` for its antenna switch period. The configuration-complete event reports the chosen
T_IP1/T_IP2/T_FCS/T_PM, and the `CsConfiguration` report already carries them.

The means: the initiator's host writes the reflector's capabilities into its own controller with
LE CS Write Cached Remote Supported Capabilities (HCI 0x208b,
`bt_le_cs_write_cached_remote_supported_capabilities()` in Zephyr's `cs.h`; the SoftDevice
Controller implements it). The copy is what the reflector reported, with the timing fields
replaced from the configuration. Only the initiator changes; the reflector firmware stays as it is.

Decisions (2026-09-19):
- Overridden: T_IP1, T_IP2, T_FCS, T_PM and T_SW. Nothing else: mode 3 is a build option
  (`CONFIG_BT_CTLR_SDC_CS_STEP_MODE3`), and the other capability fields stay as reported.
- The former §8, the reflector creating the configuration, does not serve this and moved to §11.
- The initiator reads the remote capabilities as today, then requests the update with the cached
  write. If the controller refuses it, the initiator logs the refusal and continues with the
  exchanged capabilities; the configuration-complete report shows the timings in use. The write is
  never used instead of the exchange.
- Found 2026-09-19 (SDC header, Core 6.3 Vol 4 Part E 7.8.137 [v2]): the write answers Command
  Disallowed (0x0C) once an LL_CS_CAPABILITIES_REQ or RSP came from the peer, or once a
  configuration exists on the link. The exchange-then-write order above is therefore expected to
  be refused. The spec's use is a write before the exchange, on a reconnection, with the copy from
  an earlier link; the read then may return the cached copy without an exchange. The Tag reads
  the remote capabilities itself, so its exchange may still reach the initiator first. The test
  build tries both orders (§8.4 step 1, decided 2026-09-19); the design follows from which works.
  The [v2] command (0x20a6) is used: [v1] has no IPT subfeature bit or IPT timings.

Open, settled by the hardware test (§8.4 step 1) before any design:
- Whether the reflector's controller accepts timings it does not support, rejects them (an LL
  error such as the 0x20 of the former §8 run), or runs them with aborted or degraded steps.
  Each outcome is a result for the study; only a rejection limits it.
- How the controller picks among several supported values (presumably the shortest common one).
  This decides whether the configuration carries masks or one value per timing (µs, as the
  planner shows them, converted to a one-bit mask by the firmware).
- T_SW does not appear in configuration complete; check whether its effect is visible in the
  step data.

### 8.2 Outline after the test (superseded 2026-09-19 by §8.5: the write does not work)

Only if the connection-time write works (§8.4 step 1); T_PM only. T_PM then becomes a setting
the Python GUI marks as changeable, so that experiments can run with different values
(decided 2026-09-19). If the write is refused, the only means is CS test mode (HCI LE CS Test,
`bt_le_cs_start_test()`, explicit `t_pm_time`, `CONFIG_BT_CHANNEL_SOUNDING_TEST`, a test image
on both boards); whether to build it is decided then.

- `cs_utils`: an optional T_PM override on the initiator record, a setter, and an apply
  function called at the connection, before the reflector's capability exchange.
- Protocol: one optional initiator configuration message (valid only in the CS initiator mode),
  with its CRC position between the peer data and the log configuration; the version bump and the
  shared CRC vector as in §9.
- `cs_roles` (initiator), `cs_client`, `cs_hostless_initiator` and the planner export.
- Python: the planner timing fields, today example values overwritten by the
  configuration-complete report, become sent settings of the initiator when the override is on;
  bridge, export, simulator and recording.
- Tests and documentation as for §1 and §2.

### 8.3 Former test switch

[x] Removed. `CONFIG_APP_CS_TEST_REFLECTOR_CREATES` (`common/libs/Kconfig`, `cs_role_initiator.c`,
`cs_role_reflector.c`, `cs_reflector_tag/src/main.c`, never committed) belonged to the former §8.
Kept from that change: the initiator's warning for a
configuration-complete event with another ID and the `deliver_queued()` split in
`cs_role_events.c`.

### 8.4 Steps

1. [x] Hardware test first (done 2026-09-19): an initiator test build (`cs_hostless_initiator`, DK) that logs the
   local and the reflector's timing fields and the chosen timings from configuration complete,
   and writes the reflector's capabilities with test values in both orders (§8.1, decided
   2026-09-19): on every link after the exchange (expected 0x0C), and on a later link to the same
   peer before the remote capabilities read, with the copy from the first link. A refused write
   is logged and the link continues with the exchanged capabilities. Only the initiator has a
   test build (`-DCONFIG_APP_CS_TEST_TIMINGS=y`, `cs_role_test_timings.c`, removed 2026-09-19
   with its hooks and Kconfig options; `test_timings.conf`, which then only selected the
   preferred T_PM for §8.5, was not kept); the reflector runs its normal image: `cs_hostless_reflector` on an nRF54L15 DK
   (2026-09-19: board files added; no USB, console and log on the debug UART at 921600). Its
   name does not match the initiator's default `CSTag` prefix, so the initiator is built with an
   export whose pattern matches it (`configs/cs_generated_config_initiator.c`: `CS` then, "CS
   Hostless Reflector" since its regeneration, §8.5). Record per
   order and timing: accepted or not, whether the read returned the written
   copy, the chosen value, and whether procedures run and how the steps look. Settle the §8.1
   open points here.
   - Link 1 (2026-09-19, LM20 DK initiator, L15 DK `cs_hostless_reflector`): local and remote
     timings identical, T_IP1 0x7c (30–80 µs), T_IP2 0x7e (20–80), T_FCS 0x1e0 (60–120), T_PM
     0x3 (10, 20), T_SW 0. The write after the exchange was refused with 0x0C (SDC enforces
     the rule). Configuration complete chose T_IP1 30, T_IP2 20, T_FCS 60, T_PM 10 µs: the
     shortest common value of each. The choice is limited by the initiator's own capabilities
     too, so between two nRF54L devices a written copy can only select among values both
     support; values neither supports (T_IP1 10/20, T_IP2 10, T_FCS 15–50) are out of reach
     this way.
   - Later link (same day): the write before the read was also refused with 0x0C. The
     reflector reads the remote capabilities about 0.3 s after encryption; the initiator
     reaches its read about 0.7 s after encryption (RAS discovery first), so the reflector's
     exchange always comes first. To win the race the write would have to follow the
     connection, before encryption (the reflector's read needs encryption: 0x2f before).
     Added the same day as `CONFIG_APP_CS_TEST_WRITE_AT_CONNECT` (test build only); to be
     run with narrower masks, where the copy would choose T_IP1 50, T_IP2 145, T_FCS 100,
     T_PM 20 µs.
   - Connection-time write (same day, `test_timings.conf`): accepted, but the read returned
     the reflector's real capabilities ("exchanged despite the write") and configuration
     complete chose 30/20/60/10 µs again. The reflector's own capability exchange replaces the
     written copy. Result: from the initiator alone, T_PM cannot be forced over a connection.
     Not tried: a reflector that skips its own capability read (would change the reflector
     firmware, and the Tag the same way).
   - Seen in the same runs: the initiator's statistics stayed at 0 procedures and subevents,
     with and without `CONFIG_APP_CS_TEST_TIMINGS`. Cause: `cs_hostless_initiator` counted a
     subevent only after its USB report succeeded, and reports fail with `-ENOTCONN` while
     no host has the CDC port open. Fixed 2026-09-19: counted first, then reported; verified
     on hardware the same day (8 procedures/s, local subevents = RAS subevents + the one in
     flight, 36 + 36 steps per procedure, no aborts, no RAS data lost over 60 s). Still
     open: once, on the first link after boot, the reflector logged the configuration but
     no procedure enable and dropped the link with 0x08 (supervision timeout) about 3.5 s
     after the initiator's enable. The link after the automatic restart ran normally
     (reflector: 8 procedures/s, 36 steps each, no aborts).
2. T_PM as an initiator setting through CS Params Set (§8.5 "Next", confirmed on hardware
   2026-09-19). The cached-capabilities write (step 1) is not used. Design (decided
   2026-09-19):

   | Type | Value | Direction | Fields | Size |
   | --- | --- | --- | --- | --- |
   | `SET_T_PM` | 0x0112 | Host → client | `t_pm_us: u8` | 13 |

   - Protocol version `0x0009`. Optional configuration of the CS initiator mode only
     (`MODE_MISMATCH` otherwise). Without it the initiator prefers 10 µs, so only 20 and 40
     are accepted (`VALUE_OUT_OF_RANGE` otherwise): one byte representation per
     configuration, and configurations without it keep their CRC.
   - CRC order and `GET_CONFIG` replay: mode, configuration, patterns, device name, peer
     data, T_PM, log configuration. Shared vectors: the initiator configuration and two
     patterns of `0xB61D36F1` with `SET_T_PM(40)` → `0x2DBB98CB`, and with
     `SET_LOG_CONFIG(4, 3)` after it → `0x6A66BE09`.
   - `cs_utils`: `t_pm_us` appended to `struct cs_initiator_config` (60 bytes, default 10),
     `cs_initiator_config_set_t_pm()`, print; `apply_creation` rejects other values.
   - `cs_roles`: the initiator calls CS Params Set before every LE CS Create Config
     (`cs_role_controller.c`, under the controller's multithreading lock; the SDC HCI layer
     does not route the vendor command), so an earlier run's value never carries over. A
     refused call fails setup at `CS_ROLE_FAILURE_CONFIG` with its HCI status.
   - [x] Firmware and Python protocol (2026-09-19): `cs_utils`, protocol header, `host_link`
     staging/CRC/replay/conversion, `cs_roles`, the T_PM in the boot/apply log of
     `cs_client` and `cs_hostless_initiator`; `TpmPacket`, `ClientConfig(t_pm=…)` and the
     shared vectors in `test_protocol.py`; native and Python tests; firmware READMEs.
   - [x] Planner and GUI (2026-09-20): T_PM as a changeable initiator setting (plan files,
     bridge), C export (`cs_initiator_config_set_t_pm()`), simulator, recording (§9 item 5).
3. [ ] The averaging experiments with different T_PM values are the user's (2026-09-19): no
   analysis tool here.

### 8.5 CS test mode for T_PM (decided 2026-09-19; dropped the same day, see below)

Found 2026-09-19 while starting §8.5: the SoftDevice Controller sets a preferred T_PM itself.
The vendor-specific HCI command CS Params Set (`sdc_hci_cmd_vs_cs_params_set()`, opcode 0xfd22,
`SDC_HCI_VS_CS_PARAM_TYPE_CS_T_PM_SET`, 10, 20 or 40 µs) makes the controller use that T_PM at
the next LE CS Create Config when both devices support it; the build-time equivalent is
`CONFIG_BT_CTLR_SDC_CS_T_PM_LEN_10_US`/`_20_US`/`_40_US` (default 10, sent by the HCI driver
at init). The initiator creates the configuration and both nRF54L devices support 10, 20 and
40 µs, so T_PM can be chosen on a normal connection with RAS, at run time. CS test mode is not
started until a hardware check confirms this (initiator built with
`CONFIG_BT_CTLR_SDC_CS_T_PM_LEN_40_US=y`, configuration complete should report T_PM 40); if
it does, T_PM becomes an initiator setting sent through the host link and shown as changeable
in the GUI, and §8.5 below is dropped. The same command also offers the voltage regulator mode
(`CS_VREG_MODE_SET`, LDO "may improve some RF characteristics"), a possible later experiment.

Confirmed on hardware 2026-09-19 (LM20 DK initiator with `CONFIG_BT_CTLR_SDC_CS_T_PM_LEN_40_US`,
L15 DK reflector unchanged): configuration complete chose T_PM 40 µs (T_IP1 30, T_IP2 20,
T_FCS 60 unchanged), procedures ran without aborts, partial subevents or RAS data lost. CS test
mode is dropped. With the export's 5 ms subevent and 10 ms maximum procedure length, steps per
subevent fell from 36 to 20: the controller fits fewer of the longer steps, so fewer channels
per procedure. T_PM comparisons need a subevent long enough for every channel at 40 µs (about
20 ms for 72 channels and 2 mode-0 steps, maximum procedure length 25 ms or more), so that
all T_PM values give the same steps.
`configs/cs_generated_config_initiator.c` was regenerated with that (2026-09-19, CRC
0xa52ea759: 20 ms subevent, maximum procedure length 40, pattern "CS Hostless Reflector");
verified at T_PM 20 µs: 74 steps per subevent (72 channels and 2 mode-0 steps), 8
procedures/s, no aborts; T_PM 10 and 40 µs the same (74 steps, 8 procedures/s), so the three
values are comparable (2026-09-19). Over longer runs at 20 µs about 0.9% of procedures lost their RAS data (one ACL event
between procedures for the larger RAS payload); a procedure interval of 3 ACL events would
give RAS two events at 5.3 procedures/s (left for later, 2026-09-19). The RAS data lost
counter rose by two per lost procedure: the tracker reported it when the next procedure
started, and its late RAS data, no longer matching, was reported again. Fixed 2026-09-19:
`cs_ras_match()` returns `-EALREADY` for the late data of the procedure last reported lost
and `ras_data_cb` drops it without a report (tests in `test_ras.c` and `test_role_sm.c`).

Next (to be designed): T_PM as an initiator setting, sent through the host link, applied with
CS Params Set before LE CS Create Config, shown as changeable in the GUI; the hostless export
applies it the same way. The CS test mode points below are kept only as a record.


T_PM is set through HCI LE CS Test (`bt_le_cs_start_test()`, `struct bt_le_cs_test_param`):
both boards run the test with the same parameters, one as initiator and one as reflector,
without a connection or capability exchange, so `t_pm_time` (10, 20 or 40 µs) is used as
given. The other step timings (`t_ip1_time`, `t_ip2_time`, `t_fcs_time`, `t_sw_time`) are
parameters of the same command and are set to the connected-mode values (30, 20, 60, 0 µs on
the nRF54L pair) so that only T_PM changes. T_PM is shown as changeable in the Python GUI.

Reference: Zephyr `samples/bluetooth/channel_sounding` (`cs_test/initiator`,
`cs_test/reflector`, `src/cs_test_*.c`): `CONFIG_BT_CHANNEL_SOUNDING_TEST=y`, results through
`bt_le_cs_test_cb_register()` (`le_cs_test_subevent_data_available`,
`le_cs_test_end_complete`). The sample runs the test for a few seconds, stops it, then connects
over GATT so that the reflector sends its step data to the initiator, and repeats.

Open, to settle before implementation:
- Where it runs: a new operation mode of `cs_client` (host link, GUI-driven on both boards)
  or a hostless test pair. GUI control of T_PM points to `cs_client`.
- How the reflector's step data reaches the host: its own `cs_client` session (each board
  reports its own subevents; `ble-channel-sounding` pairs them) or a GATT transfer to the initiator as in
  the sample.
- Pairing without a connection: both sides need the same `drbg_nonce`, channels and start;
  how the two runs are aligned and how their subevents are matched (procedure counter,
  timing).
- Which test parameters the GUI exposes besides T_PM (mode, steps, channels, subevent length
  and interval, antenna configuration, SNR control, transmit power), and their defaults.
- Protocol: a new configuration message and operation mode, version bump and CRC position as
  in §9.
- Controller: whether the SoftDevice Controller's CS test accepts two devices under test
  (the sample suggests it does) and needs `CONFIG_BT_CTLR_CHANNEL_SOUNDING_TEST`.

## 9. Python TODOs

Consolidated: 2026-09-18 (time not recorded). Updated: 2026-09-20.

The Python-side work that remains in §§1–8, grouped for planning. The step lists in each section
stay the progress record: tick a step there, and tick the item here when all its steps are done.

**Protocol order.** §1 and §2 are in protocol version `0x0008`, the T_PM setting (§8.4 step 2)
in `0x0009`. The CRC order: operation mode, configuration, patterns, device name, peer data
(§1.3), T_PM (§8.4 step 2), log configuration (§2.4).
Each shared CRC vector in `tests/test_protocol.py` must match the C vector in
`tests/host_link/test_config_store.c`, so the Python protocol items finish together with the C
protocol steps (§1.9 step 2, §2.7 step 2, §8.4 step 2).

1. [x] **Reflector data / IPT support (§1; §1.9 steps 2, 6–8)**
   - [x] Add `host_settings.peer_data`, planner control, tooltip, enable/reset behavior,
     validation, and schedule notes.
   - [x] Add `PeerDataPacket`, `CsPeerDataPacket`, the `PEER_IPT_UNSUPPORTED` reason, the
     current protocol version `0x0008`, the shared CRC vector, and `ClientConfig` support.
   - [x] Update C export generation, simulator rules, session/error handling, hostless mode,
     and controller configuration comparison.
   - [x] Check that the session and the app do not require `RAS_READY` before `RUNNING` (§1.4).
   - [x] Update results analysis for initiator-only procedures and PBR, IPT corrections, and
     unavailable RTT.
   - [x] Record `/config` `peer_data`, `/reports/peer_data`, and MAT output.
   - [x] Add protocol, planner, simulator, results, recorder, session, controller, and export coverage.
   - [x] Documentation: `python/ble_channel_sounding/planner/README.md`, `python/README.md` (§1.8).
   - Standalone `ble_channel_sounding_planner` is intentionally excluded: it does not expose or serialize
     `peer_data`; its hostless export leaves reflector-data selection to the firmware default
     or a firmware override.
   - [x] Fixes from the firmware comparison (2026-09-18):
     - [x] The connected `ble-channel-sounding` export and CRC include the optional peer-data payload;
       standalone `ble_channel_sounding_planner` intentionally omits it so firmware can apply its own override.
     - [x] Results take reflector data from the applied configuration
       (`ClientSession.applied_peer_data`, on every sync change) as well as from `CS_PEER_DATA`.
     - [x] Connecting to a running client: the session sends `GET_CONFIG` after a `RUNNING`
       `CONNECT_RESPONSE` and emits `attached_to_run` with the differences from the host's
       configuration (`field_diff`, which now includes `peer_data`); the app loads the client's
       configuration, warns, and skips the sync dialog. The run is not stopped.
     - [x] Simulator: `CS_PEER_DATA` after each configuration complete, once per link;
       `PEER_IPT_UNSUPPORTED` after an OK START response and the remote capabilities, which
       report `cs_ipt_reflector_supported`; `SET_PEER_DATA` and `APPLY_CONFIG` checks, their
       order (missing configuration, missing patterns, then reflector data) and error codes as
       the firmware.
     - [x] Controller view: with none, missing reflector IPT or a configuration without IPT is
       listed first as `Run fails: …` and counted in the status line.
     - [x] `QtSession` lacked the `peer_data` signal the session emits, so the app raised on the
       first `CS_PEER_DATA`; added with `attached_to_run`.
     - [x] Tests: shared vector `0x8252106B` (`ClientConfig` and connected export), standalone
       default-CRC/override omission, `GET_CONFIG` round trip with reflector data, `CS_PEER_DATA` timing, `PEER_IPT_UNSUPPORTED`,
       simulator `SET_PEER_DATA` rules, attaching to a running client, controller run failures.
   - [x] The `ble-channel-sounding` initiator export (alone or in a *both* export) writes
     `cs_initiator_config_set_peer_data(config, CS_CONFIG_PEER_DATA_NONE)`; the standalone
     `ble_channel_sounding_planner` export does not (decision below).
   - [x] *CS modes → Reflector data* sits directly below *Inline PCT transfer (IPT)* (it was in
     the *Host* form, labelled "Peer data").
   - [x] Stale tests after the Results/Controller layout commits (fail at HEAD too), updated:
     `test_controller.ControllerViewTests.test_view_fills_tables_and_issues` (no `summary` label)
     and `test_planner_gui…test_cs_modes_labels_controls_and_options_have_tooltips` (row count).
   - Found by the plan check and done on 2026-09-19:
     - [x] Schedule notes (§1.6): Mode 3 with none (RTT has no reflector timing, no independent
       check of the IPT phase); none allows a procedure interval of 1 ACL event; RAS with
       `min_procedure_interval` 1 needs ACL events between procedures.
     - [x] Initiator-only PBR uses the initiator's tone quality (it was `QUALITY_HIGH` for every
       sample) and the initiator's mode-0 offset.
     - [x] IPT with RAS (§1.6): the reflector's I (clamped at 0) is the amplitude; a non-zero Q
       or negative I is counted as an IPT protocol violation (PBR summary) and the tone gets
       quality unavailable. `tone_pair_delay_us` keeps its form under IPT (the interval between
       the reciprocal tones is unchanged, `docs/Bluetooth_CS_Inline_Phase_Transfer.tex`) with
       T_SW_IPT from the capabilities (`ResultStore.t_sw_us(configuration)`).
     - [x] *Both* export: the reflector file notes that the initiator runs without RAS.
     - [x] Tests (§1.7): `test_results.py` initiator-only procedures, IPT PBR with and without
       reflector amplitude, RTT unavailable; `test_recorder.py` `/config/peer_data` and
       `/reports/peer_data`; `test_export_c.py` the setter call and a compiled initiator-only
       export.

2. **Runtime logging configuration (§2; §2.7 steps 2, 5–6)**
   - [x] Add the *Console* and *Host* level selectors (top general toolbar since §6.1), saved in plan files
     (`host_settings.log`) and radio test presets.
   - [x] Add `LogConfigPacket`, configuration serialization, the shared CRC vector, and the
     sync dialog field diff.
   - [x] Update C export generation, simulator filtering/apply behavior, and `/config` log recording.
   - [x] Hostless mode: the hostless initiator's `LOG_MESSAGE` frames reach the Session log,
     Results and HDF5 `/log`.
   - [x] Add protocol, session/simulator, GUI, recorder, and export tests.
   - [x] Documentation: `python/ble_channel_sounding/README.md` (§2.6).
   - Standalone `ble_channel_sounding_planner` is intentionally excluded: it does not expose or serialize log
     levels and its export omits `cs_generated_config_log()`, leaving the firmware default or
     a firmware override in control.

3. **Planner timing defaults (§5.4; §5.5 step 1)**
   - [x] Confirm the mandatory timing values and update `Scenario()` in both planners.
   - [x] Update dependent tests, notes, tooltips, and README examples.

4. **Results/session history overhaul (§7; §7 open items, §7.5 steps 1–9)**
   - [x] Implement temporary session-history storage with indexing, segmentation, size limits,
     context seeding, and failure handling.
   - [x] Implement correct confirmed/refused START and hostless Connect/Disconnect lifetimes,
     including clearing Results only after a successful hostless `transport.open()` (§7.1).
   - [x] Replace the rebuilding `QTreeWidget` with a lazy `QTreeView` and full-history filtering.
   - [x] Support HDF5 capture browsing, cancellable text search, and detail loading for old procedures.
   - [x] Turn the hidden Steps, Subevents, Reports and Log widgets into the detail pane of the
     selected row, and remove their separate filling.
   - [x] Performance check at mode-3, 4-path report rates in the simulator.
   - [x] Add Save Session, background export, cancellation, and the `source` and
     `history_truncated` root attributes; readers and MAT conversion accept a file without
     `/config` (hostless sessions, §7.3).
     - [x] Add the unsaved-session prompt.
   - [x] Add run-description storage/editing (§7.4): the Recording-group field, append-mode
     write of the `description` and `description_updated` root attributes, *Edit description…*
     for the last recording and an opened capture, replay display, and MAT `description`.
     - [x] Add the end-of-run *Run description* dialog and the description field in *Save
       session…*.
   - [x] Tests cover `ResultStore` direction and timestamp, `recorder.load(with_direction=True)`,
     History filtering and step children, save/cancel, description reread/editing, prompts/dialogs,
     host/peer records, simulator parity, and MAT conversion.
   - [x] Documentation: `python/ble_channel_sounding/README.md` covers Results tabs, session history, Save
     session, current run-description behavior, and the HDF5/MAT format sections.
   - [x] Host messages in the history (§7.6): `append_host` record, `show_message` levels,
     `add_text` and `logging` handler feeding the current history, `/host_log` in recordings and
     saved sessions, MAT `host_log`, History *Host* filter; tests and documentation.
   - [x] Peer console input (§7.7): optional second serial port, line reader with level parsing,
     records with source `peer` in history, `/host_log` and Session log, History *Peer* filter;
     tests with a fake port and documentation.
   - [x] Description field in the Recording group before START (§7.4); it is stored in the
     recording metadata and used as the initial run description.
   - Found by the plan check and done on 2026-09-19:
     - [x] Disk bound as a setting (§7.1; 2 GB is a constant, `DEFAULT_HISTORY_MAX_BYTES`), and
       History says where the kept history starts after segments are dropped
       (`truncated`/`first_kept_timestamp` are never shown).
     - [x] *Save session…* (§7.3): default name `session_<mode>_<start time>.h5` in the recording
       folder (today `session.h5` in the working directory); the action in the Recording group
       too; when *Recording* covered the session, say so and offer to open that file; save the
       planner JSON beside the file; with a capture open, *Save session…* saves the live history,
       not the one shown.
     - [x] MAT `host_log` (§7.6): a struct array with `text` and `source` as `char` rows, empty
       when `/host_log` is absent; today it is a struct of columns with cell text, and missing
       when absent.
     - [x] Peer console (§7.7): the level is parsed only when the tag starts the line, but
       `app_log` and Zephyr prefix a timestamp (`[12.345] <err> …`), so real lines are all
       `info`; the tests use lines without a timestamp. Open failure and port loss are
       reported as errors, not warnings. Closing the window closes the peer console before
       the unsaved-session prompt, so *Cancel* leaves the session without it.
   - [x] Description display (§7.4): the replay description is shown above the Results tabs
     and in the Session tab header.
   - [x] *Save session…* enabled only when the session history is not empty (§7.3); today it is
     always enabled and answers with a message.
   - History in the Session tab (§7.8, decided 2026-09-19):
     - [x] History exists only in the Session tab; Results has no History tab and keeps PBR per
       channel, RTT, Estimates, Controller and FAE.
     - [x] `SessionLogView` is removed; its Pause and category filters move to History and apply
       to the whole history; its Clear button goes.
     - [x] The Session tab shows whatever session is open: the live or last session, or an
       opened capture, and says which.
     - [x] The timeline holds all the data: frames sent (tx), frames received, and local logs
       (host records, peer console lines), with direction as a column and warning/error colours
       and counts.
     - [x] The panel at the bottom of History shows the selected record parsed: packet fields,
       subevent steps and header, host/peer text, level and source.
     - [x] *Save session…* and *Edit description…* move with History.
     - [x] Results follows the open session's configuration: its CS modes decide the Results
       views, Results keeps its own procedure selector, and replay-history selection updates the
       analysis views for the selected procedure and its immediate neighbours while leaving
       Controller link-wide.
     - [x] GUI tests (live, after STOP, capture, detail pane per record kind) and
       `python/ble_channel_sounding/README.md`.
   - Session view cost and selection (§7.9, decided 2026-09-22):
     - [x] Browsing: a row's children are known from its kind without decoding the record, and the
       disk-backed model reads a window of rows per query instead of one `LIMIT 1 OFFSET ?` query
       per row, so a redraw no longer costs a query and a decode per row.
     - [x] Live tail: rows are selectable during a run and a click shows the record in the detail
       pane; the search and the filters stay disabled and nothing beyond the tail is retained.
     - [x] A subevent click fills *Procedure*, *Subevents* and *Steps* from `ResultStore`, which is
       keyed by the procedure key, so the detail is a lookup rather than a scan of the session and
       works during a live run too (decided 2026-09-23; the indexed-entry scan stays as the
       browsing fallback).
     - [x] STOP leaves live mode and asks for *Save session…*; after the save the app switches to
       replay over the saved file, and browsing, search and procedure selection happen there.
     - [x] Keep the procedure key on subevent results only (checked 2026-09-22: `ResultStore.add`
       and `session_history._procedure_key` bind nothing else); per-procedure retention in
       `ResultStore` has to be revisited before another report is bound to a procedure key.
     - [x] Moving the highlight repaints the timeline, so a selection change made with the
       selection model's signals blocked leaves no stale highlights behind.
     - [x] Tests: a browsing redraw reads only the records it shows and still knows which rows
       expand; moving the highlight repaints the timeline and leaves one selected row
       (`test_results.HistoryModelTests`).
     - [x] Tests: a live click fills the detail pane and keeps the tail following, an evicted row
       keeps its copied detail, a stopped run offers the save once, and the saved file is what is
       browsed afterwards (`test_app_gui`, `test_results`).  A live click also fills the three
       procedure tabs from the store without reading the session, and leaves them empty for a
       procedure the store has dropped
       (`test_results.HistoryModelTests.test_live_click_fills_the_procedure_detail_from_the_decoded_store`).
       Found on the way: the simulator
       start/stop GUI test left its run-description dialog visible, which made that dialog the
       application's active window and broke the planner hover tests that ran later; it is closed
       with the window now.
     - [x] Documentation: the Session tab paragraphs in `python/ble_channel_sounding/README.md`.

5. [x] **T_PM setting (§8.4 step 2; replaces the timing override, 2026-09-19)**

   Design (decided 2026-09-20): the request is the new `t_pm` host setting, not the example
   `configuration.t_pm_time_us`. The example field stays what a negotiated `CS_CONFIGURATION`
   replaces (§5.1), so a report can never overwrite a request, and the two quantities stay
   separate as *Reflector data* and `CS_PEER_DATA` already are. Selecting 20 or 40 µs copies the
   value into the example field once, so the prediction follows the request without pinning it.
   The control is *CS modes → Preferred T_PM*, below *Reflector data*, read-only at 10 µs for a
   reflector configuration or without Mode 2 or 3 (`PBR_HOST_FIELDS`, `unused_host_fields`).
   The standalone `ble_channel_sounding_planner` ignores `t_pm` as it ignores `peer_data` and `log`
   (`STANDALONE_IGNORED_SETTINGS`): its exports stay firmware-owned, which both READMEs say.
   - [x] Protocol (2026-09-19): `TpmPacket`, version `0x0009`, `ClientConfig(t_pm=…)` send
     order and `from_packets`, `GET_CONFIG` packet list, shared vectors `0x2DBB98CB` and
     `0x6A66BE09` in `test_protocol.py`.
   - [x] Planner/GUI (2026-09-20): the `t_pm` host setting in `HOST_DEFAULTS` (saved in plan
     files), the bridge check (10, 20 or 40; non-default for CS initiator mode only), the
     control and its help, `collect_config`/`config_received`, and the Controller view
     comparing the request with the reported T_PM and checking it against both capability
     reports before the run.
   - [x] C export (2026-09-20): `cs_initiator_config_set_t_pm(config, CS_CONFIG_T_PM_<n>_US)`
     for 20 and 40, the CRC from the same `ClientConfig`, a header comment, and the setting
     cleared for every reflector file (as `peer_data` was for a *both* export).
   - [x] Simulator (2026-09-20): `SET_T_PM` rules as `host_link_config_check_t_pm()` (staged
     mode, CS initiator only, 20/40), the last frame wins, `GET_CONFIG` replay, and a requested
     T_PM in its `CS_CONFIGURATION`; without one the simulated controller keeps its own choice.
   - [x] Recording (2026-09-20): `/config/t_pm` beside `/config/peer_data`, with the `SET_T_PM`
     payload already in `/config/payloads`; tests (8 new) and `python/README.md`,
     `ble_channel_sounding/README.md`, both planner READMEs.

6. **End-to-end verification with `ble-channel-sounding` (§3.3 "Host application")**
   - [ ] Verify `ble-channel-sounding` against `cs_client`: connect, sync, apply, start/stop, recording, and MAT conversion.
   - [x] Verify `ble-channel-sounding` in hostless mode against `cs_hostless_initiator` (2026-09-23). Two
     recordings: attaching to an initiator already running (`procedure_counter` starts at 813,
     so the cached resend on DTR rise backfills capabilities, configuration, peer data and
     connection parameters), and attaching before the link comes up. Reports, results, `/log`
     and the saved HDF5 are all populated, `close_reason` `session saved`,
     `protocol_version` 11. The ATT MTU row reads 498 on this hostless pair as well, since both
     images set `CONFIG_BT_L2CAP_TX_MTU=498`; §10 item 8 still needs the hosted link.
   - The hardware checks for IPT/peer data and runtime logging are
     firmware steps (§1.9 step 9, §2.7 step 7; §10 item 6); `ble-channel-sounding` is only the viewer there.
     The T_PM experiments (§8.4 step 3) record through `ble-channel-sounding`.

7. **Simulator command-rule parity (found with §10 item 3, 2026-09-18)**
   The firmware rules are pinned by `tests/host_link/test_commands.c`; `ble_channel_sounding/simulator.py`
   differs from them in these cases:
   - [x] A frame of an unknown type raises `AttributeError` in `Simulator.handle()` (a `Frame` has
     no `PACKET_TYPE`); the firmware answers `UNSUPPORTED`, with or without a session.
   - [x] A frame of a known type and the wrong size is dropped by `PacketReceiver` without a
     response; the firmware answers `INVALID_FRAME`. Both checks come before `NOT_CONNECTED`.
   - [x] `SET_PERIPHERAL_PATTERNS` without a staged mode is accepted (firmware:
     `BAD_STATE / MISSING_CONFIG`), in the radio test mode too (`REJECTED / MODE_MISMATCH`); a
     count, length, NUL or UTF-8 error answers `NONZERO_PADDING` (firmware:
     `VALUE_OUT_OF_RANGE`; only padding is `NONZERO_PADDING`).
   - [x] `CLOSE_SESSION` and a lost host keep the staged configuration; the firmware clears it
     when the session ends (the applied one stays).
   - [x] Configuration commands are accepted in `LINK_CONNECTING` and in `ERROR` with the link
     still up; the firmware answers `LINK_ACTIVE` while a link, scan or advertising is active.
     Done 2026-09-19: `Simulator.link_active()` follows `cs_role_link_active()` (from
     `CONNECTING`; `cs_role_fail()` keeps the link after a setup failure such as `PEER_IPT`), and
     discovery commands follow `peer_discovery.c` (only `PEER_CONNECT` during a scan); tested.
   - Matching already: status, reason, client state and packet type values, version `0x0008`,
     `GET_CONFIG` order, `BUSY` before `LINK_ACTIVE`, `START` rules, `SET_DEVICE_NAME` after the
     configuration. `ble-channel-sounding` shows a `STOP_TIMEOUT` response reason in the Session tab.

8. **Radio Test Configuration views (§6.1, decided 2026-09-19)**
   - [x] Keep the existing Configuration view switch and move operation mode plus both log
     selectors into the top general toolbar; do not create a General tab group.
   - [x] Put Bluetooth name, GAP role, CS role and central-only scan prefixes in the first CS
     setup tab. Radio Test does not share these controls.
   - [x] Group RadioTestView settings into Test, Channel, Timing and FEM tabs with dynamic
     enable/visibility rules and exact inactive-field retention.
   - [x] Add a Radio Test context pane with fixed-test, sweep, duty-cycle and sleep explanations;
     the preview does not represent synthetic measurements.
   - [x] Preserve RadioTxTestConfigPacket serialization, validation, presets, configuration
     change signals and log-level synchronization; no firmware/protocol changes are needed.
   - [x] Add GUI coverage for stable Configuration-shell identity, mode transitions, tab order,
     help links, preview updates, inactive-field retention, and Radio Test mode transitions.
   - [x] Add explicit GUI coverage for Radio Test locking/read-only states and radio preset
     save/open round trips.
   - [x] Update `python/ble_channel_sounding/README.md` after the UI refactor; the repository has no separate
     manual-QA document, so the current QA notes live with the README/test coverage.

9. **ACL connection parameters in the GUI (§12, decided 2026-09-20)**
   - [x] Add the `QtSession.connection_parameters` signal the session emits; without it the first
     `CONNECTION_PARAMETERS` packet raises `AttributeError` in the GUI (§12.3).
   - [x] `ControllerReports` keeps and clears the latest `ConnectionParametersPacket`;
     `compare_connection()` builds the interval, latency and timeout rows (§12.1).
   - [x] Controller view: the "Connection parameters" box above "Configuration complete", with
     "not requested" in the Requested column for a peripheral (§3.1).
   - [x] `compare_procedure` converts the event and procedure intervals with the negotiated ACL
     interval, leaving them in ACL-event units until the report arrives.
   - [x] CS view: the negotiated parameters feed the anchor/latency/timeout illustration under
     the `loading` guard, with the planned values as the source before a report (§12.2).
   - [x] Simulator: `CONNECTION_PARAMETERS` on every `LINK_CONNECTED`, from the applied
     configuration's ACL values (§12.3).
   - [x] Tests: the new rows and their statuses, the peripheral case, the millisecond conversion
     with and without the report, the reports store, the bridge narrowing the range, and the
     simulator report reaching both views through `MainWindow`.
   - [x] Documentation: the Controller tab box in `python/ble_channel_sounding/README.md`.

10. **Session-actions toolbar: teardown and naming (§7.8, decided 2026-09-20, revised 2026-09-22)**
   - [x] *Connect* becomes *Disconnect* while a session is open and stays enabled for the second press
     (`RunBar.set_connection_state()`, `MainWindow.toggle_connection()`, commit `fab1ecd`).
   - [x] The toggled action has its own icon: the `unplug` glyph, distinct from the Bluetooth-off
     `disconnect` of *Disconnect link* (`views/icons.py`, commit `d7093d9`).
   - [x] Cancel a pending CONNECT (decided 2026-09-21): while the handshake is unanswered the action reads
     *Cancel connection* (crossed-circle `cancel` glyph) and stays enabled; pressing it calls
     `Session.cancel_connect()`, which drops the pending command and closes the transport — as a CONNECT
     timeout does, the handshake having no transaction ID — but ends DISCONNECTED, so the port is not marked
     rejected. Tests cover the session cancel and the toolbar label, enablement and reconnect.
   - [x] Hostless: the toggle only closes the port and stays enabled in hostless mode
     (`Session.close()` hostless branch; verified on hardware 2026-09-22).
   - [x] Removed the *Close session* action from `views/run_bar.py` (`GROUPS`, `ICONS`) and its wiring in
     `app.py` (the `invoke` list and the hostless enablement branch in `update_controls()`). The `close`
     glyph, left without a user, went with it.
   - [x] Renamed *Stop* to *Stop session* and *Start* to *Start session* in `views/run_bar.py`; the labels
     are the dictionary keys `app.py` wires and the tests index, so both followed.
   - [x] Hosted second press of the toggle: LINK_DISCONNECT, then CLOSE_SESSION, then the port
     (`Session.close()` → `close_session(close_port=True)`). No STOP.
   - [x] *Disconnect link* is `Session.close_session()`: LINK_DISCONNECT then CLOSE_SESSION, port left
     open. Its confirmation prompt now says the session ends, and is asked whether or not a run is going,
     since ending the session is the bigger consequence. `allow_interrupt` is gone with the STOP.
   - [x] `Session.close()` split into `close_session(close_port=False)` and `close_port()`; the
     CLOSE_SESSION ack closes the transport only for the toggle (`_close_port_with_session`).
     `reconnect()` is the port-open/no-session state: it resets the session fields through the new
     `_reset_session()` (shared with `connect()`), emits `session_started` and sends CONNECT over the open
     transport. `MainWindow.toggle_connection()` calls it when the state is DISCONNECTED with a transport,
     `update_controls()` keeps *Connect* enabled there, and `port_view` stays disabled as before because
     it already follows `transport is None`.
   - [x] Also needed by the above, decided while implementing:
     - `Session.can_disconnect_link` replaces the inline rule in `update_controls()`, so the action is
       enabled exactly when it sends the frame. It excludes RADIO_TX_TEST, which reports RUNNING with no
       link: a radio session's teardown is CLOSE_SESSION alone. The firmware accepts LINK_DISCONNECT
       without a link (`cs_role_link_disconnect_request()` falls through to `err = 0`), so the other
       non-IDLE states keep sending it.
     - `Simulator`: LINK_DISCONNECT while RUNNING interrupts the client instead of answering BUSY, which
       is the §10 item 9 change on the simulated side. Without it the rejection clears the queue and the
       CLOSE_SESSION behind it is dropped. The firmware change followed on 2026-09-24.
     - `MainWindow.offer_session_save()` offers once per session (`_save_offered`, cleared in
       `history_started()`). The teardown ends the run twice — the client's interrupt report and then
       CLOSE_SESSION — and the user was asked to save twice.
   - [x] Tests: the teardown order with no STOP frame; *Disconnect link* closing the session and leaving
     the port open, then reconnecting over it; `reconnect()`'s guards; a close with no link sending
     CLOSE_SESSION alone; the hostless port close through the toolbar; the GUI toggle across all three
     presses. `test_app_gui.py`'s group-contents and `Close session` assertions moved to the new actions,
     and `test_peer_discovery.py` reconnects where it used to keep scanning after a link disconnect.
   - [x] Documentation: the toolbar paragraph and the Stop / *Disconnect link* / *Close session* note in
     `python/ble_channel_sounding/README.md`. The Apply bullet no longer claims a STOP either: `Session.apply()` refuses
     while running and queues LINK_DISCONNECT alone.
   - **Depends on §10 item 9.** A teardown that starts while procedures are running sends LINK_DISCONNECT
     to a client that still answers BUSY, and the rejection clears the queue, so the CLOSE_SESSION behind
     it is dropped and the session stays open. The simulator is already on the new behaviour, so the GUI
     and its tests are not; hardware was, until the guard went (2026-09-24). Verify the teardown on
     hardware with §10 item 9.

11. **RAS transfer in the CS view timelines (§13, decided 2026-09-22; drawn from the MTU 2026-09-22)**
   - [x] `model.py`: `RasTransfer`, `ras_transfer()`, `ras_step_bytes()` and `ll_packet_us()`, with
     `Schedule.ras` (`None` without RAS real-time or without a schedule). `build_schedule()` takes
     `mtu` and `phy`; `mtu` 0, or below the ATT default, is the pre-negotiation 23 (§13.5).
   - [x] `draw_connection` and `draw_procedures`: a fourth lane, *RAS (reflector)*, with the air
     time of each ACL event after the procedure, only with `peer_data` 0 (§13.1, §13.5).
   - [x] The MTU is `connection.mtu`, a connection parameter in the Connection tab's example
     panel (`ATT MTU`), at the ATT default until `apply_packet` writes a client's reported value
     (§13.5). The drawn air time follows the host reference PHY, read as the assumed ACL PHY.
   - [x] `draw_connection` draws every preview procedure that starts inside the 12-anchor window,
     not only the first, so the repetition the Procedures view promises is visible and a RAS
     transfer running into the next procedure can be seen (§13.5).
   - [x] `host_edited()` now recomputes the schedule: reflector data and the PHY enter it, and the
     host controls only emitted `configuration_changed` before.
   - [x] Schedule notes: the counts and the floor, plus a warning when the air time exceeds the
     window before the next procedure. Tooltips and `views/control_help.py` say occupancy, not
     drain rate, for `peer_data` and `phy` and on the Host tab.
   - [x] Tests: the `cs_hostless_initiator` worked case (736 bytes, 3 LL PDUs at MTU 498, 39
     notifications at the default), the PHY air times, the absent transfer with `peer_data` 1, the
     notes, and the GUI lanes, captions and reported-MTU redraw.
   - [x] Documentation: the view paragraphs and a *RAS real-time transfer* section in
     `python/ble_channel_sounding/planner/README.md`, and the MTU paragraph in `python/ble_channel_sounding/README.md`.
   - Standalone `ble_channel_sounding_planner` is excluded by the §9 decision below: it has no `peer_data` (§13.3).

12. **Negotiated ATT MTU in the connection report (§12.4, decided 2026-09-22)**
   - [x] `ConnectionParametersPacket`: the `mtu` field, the 20-byte frame and protocol version
     `0x000B`, matching the C header. The configuration CRC and its field order do not change
     (§12.4). Finishes together with the C side (§10 item 8).
   - [x] `ControllerReports`/`compare_connection()`: a fourth row, "ATT MTU", with "not
     requested" in the Requested column and `INFO` status (§12.1).
   - [x] `report_log.py` Session line and `recorder.py` `/reports/connection_parameters`: the new
     value. Recordings written before `0x000B` have no `mtu` column, so whatever reads the table
     must tolerate its absence.
   - [x] Simulator: an MTU with the ACL values on `LINK_CONNECTED`, and a second report when it
     changes, so the Controller row can be seen without hardware.
   - [x] Simulator: `ATT_MTU_DEFAULT` 23 became `ATT_MTU_NEGOTIATED` 498 with §10 item 8, so the
     simulated link reports what a hosted one now negotiates; `set_mtu()` still shows a change.
   - [x] Tests: the frame size and round trip, the new row and its status, the recorder field,
     and the simulator report.
   - [x] Documentation: the Controller tab box in `python/ble_channel_sounding/README.md` and the
     `/reports/connection_parameters` field list in `session_record.md` (§8.4).

13. **Main-mode step bounds only with a sub-mode (§14, decided 2026-09-23)**
   - [ ] Export the neutral main-mode step bounds when the mode has no sub-mode, instead of the
     scenario's last values: `configuration.min_main_mode_steps`,
     `configuration.max_main_mode_steps` and `main_steps` are already `unused_fields()` for
     modes 1, 2 and 3 and disabled in the CS view, but they are still serialized and exported,
     so a greyed-out control still reaches the controller in LE CS Create Config (§14).
   - [ ] Settle which value is neutral (`1, 1` or the model defaults `2, 10`) and apply it in
     `ble_channel_sounding` and standalone `ble_channel_sounding_planner` alike.
   - [ ] Move the shared configuration CRC vectors in `tests/test_protocol.py` and
     `tests/host_link/test_config_store.c` together, since the exported creation record changes.
   - [ ] Tests: an export from a mode-2 scenario whose main-mode bounds were edited under a
     sub-mode mode carries the neutral values, and the CS view still round-trips the scenario.

Decision (2026-09-19): the standalone `ble_channel_sounding_planner` does not support reflector-data or runtime
log settings. These are host/session settings and belong only in `ble_channel_sounding`. The standalone
planner accepts older shared JSON files but drops legacy `peer_data` and `log` keys when loading
or saving. Its C export omits the optional peer-data payload and `cs_generated_config_log()`;
the firmware weak defaults or board-specific overrides therefore remain authoritative. The
standalone CRC and embedded JSON also exclude both settings. `ble-channel-sounding` continues to expose,
serialize and export them.

14. [ ] **Controller capability limits in the planner (§15.1, §15.2)**
    - [ ] The CS view offers a sub-mode and the sounding and random RTT types, and the export
      writes them, but the SDC rejects both at LE CS Create Config with `0x11` (§15.1, §15.2).
      A scenario that cannot run should not be exportable in silence. Decide between a warning
      in the CS view, a capability-aware control that disables what the connected controller
      does not report, and leaving it alone because the planner is meant to describe any
      controller, not only this one.
    - [ ] Whichever is chosen, `ble-channel-sounding` should surface the local capabilities it already
      receives (`modes_supported`, `rtt_capability`, `rtt_sounding_n`, `subfeatures_supported`)
      somewhere a person can read before exporting. They are in the capabilities report today
      and reading them would have replaced three flash cycles with one (§15.2).

15. [x] **Discovery lists peers matching the scan prefixes (§16, decided 2026-09-24)**
    - [x] `ClientSession.visible_peers()` keeps the peers whose name starts with an applied
      prefix (bytes, case-sensitive); unnamed peers stay hidden until a scan response names
      them; without prefixes every peer is listed.
    - [x] Peers view **Show all** check box lists every report; the combo box follows it.
    - [x] Tests in `test_peer_discovery.py`: prefix, unnamed, show-all and no-prefix cases; the
      simulator's `Lab peer å` is hidden until **Show all**.

## 10. Firmware TODOs

Consolidated: 2026-09-18 11:06 EEST. Updated: 2026-09-18 11:24 EEST.

The firmware-side work that remains in §§1–3 and §8, grouped for planning. As in §9, the step
lists in each section stay the progress record: tick a step there, and tick the item here when
all its steps are done.

**Protocol order.** The protocol version and CRC order rule in §9 applies here too: §1 and §2 are
in `0x0008` and the T_PM setting (§8.4 step 2) in `0x0009`; the CRC order is operation mode,
configuration, patterns, device name, peer data (§1.3), T_PM, log configuration (§2.4). Each C protocol step finishes together with
the Python one, since the shared CRC vectors in `tests/host_link/test_config_store.c` and
`tests/test_protocol.py` must match (§1.9 step 2, §2.7 step 2, §8.4 step 2).

**Order.** `tests/cs_roles/test_role_sm.c` is created in item 3. The initiator-only cases (§1.7)
and the timing override cases (§8.4 step 2) are added to it, so its harness comes before those
steps.

1. **Reflector data / IPT support (§1; §1.9 steps 1–5, 8)**
   - [x] `cs_utils`: `peer_data` field (the record stays 59 bytes), default RAS, setter,
     `cs_initiator_config_check_peer_data()`, print (§1.2), with native tests.
   - [x] Protocol `0x0008`: `SET_PEER_DATA`, `CS_PEER_DATA`, `PEER_IPT_UNSUPPORTED` (0x14), CRC
     order and `GET_CONFIG` replay, shared CRC vector (§1.3). C side only; the Python side must
     use the vector `0x8252106B` from §1.9 step 2 (§9 item 1).
   - [x] `host_link`: staging, commit, validation (`NONE` only, CS initiator mode only, `NONE`
     without IPT rejected at `APPLY_CONFIG` through the check), conversion to the setter,
     `host_link_report_peer_data()` (§1.5), with native tests.
   - [x] `cs_roles` initiator-only setup (§1.4): `cs_role_start_initiator()` calls the check; no
     RAS discovery or RREQ; `PEER_IPT` failure at remote capabilities and at configuration
     complete, without `auto_restart`; STOP and finite count without the RAS wait.
   - [x] Native initiator-only cases in `test_role_sm.c` (§1.7), 2026-09-18.
   - [x] `cs_client`: send `CS_PEER_DATA` at configuration complete, map `PEER_IPT` to
     `PEER_IPT_UNSUPPORTED`; check that `RUNNING` does not require `RAS_READY` (§1.5).
   - [x] `cs_hostless_initiator` (§1.5): log the reflector data setting and CRC at boot; send
     `CS_PEER_DATA` and resend it with the cached link records when the port opens; on `PEER_IPT`,
     log an error and halt radio activity until reset; leave the RAS counters out of the stats
     line when RAS is off. `cs_generated_config` needs no header change: only the exported
     function calls the new setter (§9 item 1). A loaded export is also checked with
     `cs_initiator_config_check_peer_data()` at boot, so none without IPT halts like any other
     rejected export.
   - [x] Firmware documentation of §1.8 (the Python READMEs are §9 item 1): `cs_utils`,
     `cs_protocol`, `host_link`, `cs_client` and `cs_hostless_initiator` READMEs.
   - [x] Builds: both `cs_client` builds, `cs_hostless_initiator` with and without an
     initiator-only export, without compiler warnings (§1.7). `cs_hostless_reflector` also
     builds without warnings.

2. **Runtime logging library (§2; §2.7 steps 1–4, 6)** (firmware done 2026-09-18)
   - [x] `common/libs/app_log/`: per-consumer thresholds, formatting, queue and log thread, drop
     count reported as one warning, console consumer; Kconfig (`CONFIG_APP_LOG`,
     `CONFIG_APP_LOG_MESSAGE_MAX` replacing `CONFIG_APP_HOST_LINK_LOG_MESSAGE_MAX`); native tests
     in `tests/app_log/` (§2.3, §2.6).
   - [x] `host_link`: register the protocol consumer; `app_log_config` in `host_link_config_set`;
     `SET_LOG_CONFIG` staging, CRC, replay and apply (defaults and levels above 4 rejected);
     shared CRC vector; the same handling in the radio test build (§2.4).
   - [x] Migrate `common/libs`, `cs_client` (both builds), both hostless apps and
     `cs_reflector_tag` from `LOG_*`, `HOST_LINK_LOG_*` and the queue-full `printk` notices; then
     remove `HOST_LINK_LOG_*`, `host_link_report_logf()` and the `LOG_MODULE_*` templates of
     `APP_HOST_LINK` and `APP_CS_ROLES`. `tests/*` apps are not changed (§2.3).
   - [x] `cs_generated_config_log()` weak default, called before Bluetooth starts by the hostless
     apps and the Tag; `cs_hostless_initiator` registers the protocol consumer on its USB CDC
     port; the reflector images ignore `protocol_level` (§2.4).
   - [x] Builds: both `cs_client` builds, `cs_hostless_initiator` (DK) and
     `cs_hostless_reflector` (DK, Tag), `cs_reflector_tag`, with and without an export, without
     compiler warnings (2026-09-18). The exports in `configs/` predate `cs_generated_config_log()`
     and use the weak default.

3. **Host-link and role reliability (§3.1–§3.2)** (done 2026-09-18)
   - [x] Native command-rule tests for every `host_link.c` status path, staging/apply, `GET_CONFIG`
     replay and the `START` CRC mismatch.
   - [x] `tests/cs_roles/test_role_sm.c` and `test_events.c` as listed in §3.1. Needed before the
     role cases of items 1 and 4.
   - [x] Streamed vs. record-built subevent frames for all step types and 1–4 antenna paths
     (needs the Zephyr Bluetooth headers on the host).
   - Python check (2026-09-18): the protocol enums and version match the C header, and the 282
     frames of `test_stream.c` parse in `ble_channel_sounding.protocol` and re-encode byte for byte. The
     simulator differs from the command rules in places: §9 item 7.
   - Large reports (§3.2): moved to future work (§11, 2026-09-18).

4. **Phase measurement period T_PM (§8; scope narrowed to T_PM 2026-09-19)**
   - [x] Hardware test first (§8.4 step 1): `cs_hostless_initiator` writes the reflector's
     capabilities with other T_IP1/T_IP2/T_FCS/T_PM/T_SW values
     (`bt_le_cs_write_cached_remote_supported_capabilities_v2()`) after the exchange and, on a
     reconnection, before it; `cs_hostless_reflector` on an nRF54L15 DK runs its normal image. The former reflector-creates
     test switch is removed (§8.3). Test build done 2026-09-19 (`CONFIG_APP_CS_TEST_TIMINGS`,
     builds without warnings). Both orders refused (0x0C); the connection-time write
     (`test_timings.conf`) is the one run left.
   - [x] Result (2026-09-19): the write is accepted at connection time but the reflector's
     exchange replaces it; T_PM cannot be forced over a connection.
   - [x] T_PM 40 µs confirmed on a normal connection through the controller's preferred T_PM
     (§8.5, 2026-09-19); CS test mode dropped.
   - [x] T_PM as a host-link setting applied with CS Params Set (§8.4 step 2, 2026-09-19):
     `SET_T_PM`, protocol `0x0009`, `cs_utils`, `host_link`, `cs_roles`, both initiator
     apps; native tests and builds without compiler warnings. The GUI side is §9 item 5.
   - [ ] Hardware: configuration complete reports the T_PM selected over the host link (20 and
     40 µs) and from a hostless export, and 10 µs again after a run at 40 without
     rebuilding. The experiments are the user's (§8.4 step 3).
     - Already shown by the §8.4 step 1 timing tests (2026-09-19, `cs_hostless_initiator` ↔
       `cs_reflector_tag`, user's runs): configuration complete reports T_PM 10, 20 and 40 µs
       on this hardware pair, through the controller's preferred T_PM (§8.5). Those runs
       selected it at build time (`CONFIG_BT_CTLR_SDC_CS_T_PM_LEN_*`) and predate `SET_T_PM`
       (protocol `0x0009`, the same evening), so the mechanism and all three values are
       confirmed on hardware.
     - Left: the same three values driven through `SET_T_PM` instead — over the host link from
       `ble-channel-sounding`, and from a planner hostless export — and 10 µs again after a run at 40
       without reflashing, which is what shows CS Params Set before every Create Config
       (`cs_role_controller.c`) rather than a build-time default.
   - Replaced on 2026-09-19: the reflector creating the configuration (former §8, now §11). Its
     test build ran once on hardware and failed with 0x20; see §11.

5. **Firmware documentation (§1.8, §2.6)**
   - [x] `common/libs/cs_utils`, `cs_protocol`, `host_link`, new `app_log` READMEs;
     `cs_client`, both hostless and Tag READMEs. The §2.6 part is done (2026-09-18); the §1.8
     part with §1.9 step 8, and T_PM with item 4 (§8.4 step 2, firmware READMEs).

6. **Hardware verification**
   - [ ] §3.3 in full: role pairs and timing, minimum RAS procedure interval, STOP and STOP
     timeout, finite count, stack high-water marks, discovery and failures, antennas, radio test
     build. The `ble-channel-sounding` end-to-end checks are in §9 item 6.
   - [ ] Reflector data / IPT: §1.9 step 9.
   - [ ] Runtime logging: §2.7 step 7.
   - [x] T_PM 40 µs through the preferred T_PM (§8.5, 2026-09-19).

7. **Tag application parity (§3.1, found 2026-09-20; done 2026-09-20)**
   - [x] Decided: `cs_reflector_tag` is kept and ported onto `cs_roles`
     (`CONFIG_APP_CS_ROLES_REFLECTOR`), not retired for
     `cs_hostless_reflector -b nrf54l15tag/nrf54l15/cpuapp`. `src/main.c` keeps the Tag's own
     parts (unique name, antenna checks, `TEST_*` configuration and its dump, counters) and
     drops its connection/CS/RAS callbacks, event queue and advertising; extended advertising
     and the `cs_roles` link restart replace the legacy advertising and the `recycled` restart,
     with a cold reboot after five consecutive link failures.
   - [x] `CONFIG_BT_BONDABLE=n`, `CONFIG_BT_TRANSMIT_POWER_CONTROL=y`, `CONFIG_BT_CTLR_PHY_2M=y`
     and `CONFIG_BT_ATT_PREPARE_COUNT=3` in the Tag; `BT_RAS`, `BT_RAS_RRSP` and
     `BT_GATT_CLIENT` dropped from `prj.conf`.
   - [x] The `config/cs_generated_config.c` lookup of the hostless applications in
     `cs_reflector_tag/CMakeLists.txt`, with `config/.gitkeep`.
   - [x] Builds for `nrf54l15tag/nrf54l15/cpuapp` without compiler warnings, without an export,
     with `config/cs_generated_config.c` and with `-DCS_CONFIG_SOURCE` (2026-09-20).
   - [ ] Hardware: repeat §3.3 on the `cs_roles` image, which is what decides whether the RAS
     buffer failures and the silent Tag change.

8. **Negotiated ATT MTU in the connection report (§12.4, decided 2026-09-22)**
   - [x] `cs_protocol`: `mtu` in `cs_protocol_connection_parameters_frame_t` (18 → 20 bytes, the
     static asserts with it) and `CS_PROTOCOL_VERSION` `0x000B`. No CRC or field-order change:
     the frame is a report, not a staged setting. Finishes together with the Python side
     (§9 item 12).
   - [x] `cs_roles`: read `bt_gatt_get_mtu(conn)` in `report_connection_params()` and carry it
     through the `connection_params` callback; register a `struct bt_gatt_cb` whose
     `att_mtu_updated` reports again, so an exchange completing after the link is up reaches the
     host (§12.4).
     `cs_config_connection` is a configuration record, so the MTU travels beside it rather than
     in it.
   - [x] `cs_client` and `cs_hostless_initiator`: fill the new field, including the cached resend
     on DTR rise.
   - [x] `cs_client/prj.conf`: `CONFIG_BT_GATT_AUTO_UPDATE_MTU=y` beside the
     `CONFIG_BT_L2CAP_TX_MTU=498` already there, so a hosted link exchanges the MTU instead of
     staying at the ATT default 23 (§12.4, decided 2026-09-22). One line covers both `cs_client`
     roles; the reflector-only images need nothing.
   - [x] `cs_client/README.md`: the `prj.conf` row said "ATT MTU 498", the local maximum rather
     than what the link settled on; it now says the exchange is started on connection.
   - [ ] Hardware: confirm the Controller tab's ATT MTU row reads 498 on a hosted link, and that
     a `cs_client`-to-`cs_client` link is unharmed by both ends requesting the exchange. This is
     the measurement §12.4 held the decision open for; take it before calling the item done.
   - [x] Native tests: the 20-byte frame and its offsets in `tests/host_link/`, with the
     `cs_roles` stubs (`tests/cs_roles/bt_stubs.c`) gaining `bt_gatt_get_mtu`.
   - [x] Documentation: `common/libs/cs_protocol/README.md` (frame and version) and the
     `cs_client` README.

9. **Session end stops the client in every busy state (§7.8, decided 2026-09-22)**
   - The host side of the teardown is in (§9 item 10, 2026-09-22) and depends on this: it sends
     LINK_DISCONNECT with no STOP before it, which a client with the BUSY guard rejects, taking the
     CLOSE_SESSION behind it out of the queue. Code, native tests and documentation done 2026-09-24;
     hardware open.
   - [x] `end_session()` in `common/libs/host_link/host_link.c` stops the client instead of interrupting
     only a RUNNING one: `handlers->stop()` covers scanning, advertising, connecting and CS setup, where
     `handlers->interrupt()` does nothing. `client_state()` reaches RUNNING only when procedures go live
     (`client_state_set()` in `cs_client/src/cs_session.c`), and `cs_role_interrupt()` is gated a second
     time on the `running` flag, which `cs_role_core.c` sets at `CS_ROLE_STAGE_RUNNING`. A host that closes
     the session today therefore leaves a scanning, advertising or mid-setup board running unattended.
     Done 2026-09-24: RUNNING still goes to `interrupt()`, which keeps the session's error (-ECANCELED
     or -ENOTCONN); SCANNING, ADVERTISING, LINK_CONNECTING, LINK_CONNECTED and RAS_READY go to `stop()`.
     A CS setup runs while the state is LINK_CONNECTED or RAS_READY, and `cs_role_stop()` is a no-op on
     an idle link, so both are included. A cancelled setup reports `STOPPED(INTERRUPTED, -ECANCELED)`
     whatever ended the session: `cs_roles` ignores an interrupt outside RUNNING. The other states
     (IDLE, CONFIGURED, STOPPED, LINK_LOST, LINK_DISCONNECTED, ERROR) call neither handler, which also
     keeps the radio build's `stop()` away from an idle radio.
   - [x] Drop the BUSY guard on LINK_DISCONNECT while RUNNING (`handle_command()` in `host_link.c`). The
     `link_disconnect()` handler in `cs_client/src/cs_session.c` already calls `cs_role_stop()` before
     `peer_discovery_stop()`, so the guard makes that call unreachable and forces the host to queue a STOP
     it does not need. Check the radio client's handler (`cs_client/src/radio_session.c`) for the same
     assumption before removing the guard.
     Done 2026-09-24. The radio handler does not rely on the guard: it has no link and returns OK, so a
     running test is left to STOP or CLOSE_SESSION. The host sends no LINK_DISCONNECT in radio mode
     (`Session.can_disconnect_link`). No protocol version change: the frame layout is unchanged and a
     host written for the guard sent STOP first anyway.
   - [x] Confirm the interrupt report still reaches the next session: `end_session()` runs after the
     CLOSE_SESSION response, and `client_state_session_changed()` re-reports an undelivered interruption on
     the next CONNECT (`cs_client/src/client_state.h`). A stop raised from `end_session()` must not be lost
     between the two.
     Confirmed 2026-09-24, no code change. `set_session(false)` runs before the handler, and `cs_roles`
     posts STOPPED to its event thread. The role thread (priority 7) and the event thread (8) both run
     above the host link thread (10), so by the time `cs_role_interrupt()` / `cs_role_stop()` returns,
     the event thread has already tried the report with no session. `client_state_set()` then keeps it
     as undelivered, and `session_changed(true)` sends it after the next CONNECT_RESPONSE. This holds
     only while the host link thread stays below both `cs_roles` threads, which its Kconfig help already
     requires. Recorded in `host_link/README.md` and the `stop` handler documentation.
   - [x] Native tests in `tests/host_link/`: CLOSE_SESSION while scanning, advertising and in setup stops
     the client; LINK_DISCONNECT while running is accepted and stops it.
     Done 2026-09-24: `test_session_end_stops()` (every busy state stops, a lost port while advertising
     stops, idle states call neither handler) and LINK_DISCONNECT while RUNNING in
     `test_busy_and_link_active()`.
   - [x] Documentation: the `session_changed` / end-of-session paragraph in
     `common/libs/host_link/README.md` (2026-09-24), with the LINK_DISCONNECT and CLOSE_SESSION rules in
     `cs_protocol/README.md` and `cs_client/README.md`.
   - [ ] Hardware: on a flashed `cs_client`, *Disconnect* and *Disconnect link* while procedures run
     end the session with `STOPPED(INTERRUPTED)` and no BUSY; *Disconnect* while scanning, advertising
     and during CS setup leaves the board idle (no advertising seen from a phone, no link attempt); the
     next Connect shows the interruption of the previous session. Blocked on the 2026-09-23 hardware
     gate.

10. **Stack sizes from the 2026-09-24 measurement (§15.4)**
    - [x] Raise the three upstream stacks (2026-09-24): `BT_LONG_WQ_STACK_SIZE` 2100 to 2560
      (peak 1864 during link setup), `MPSL_WORK_STACK_SIZE` 1024 to 1280 (peak 768 on the
      reflector) and `BT_TX_PROCESSOR_STACK_SIZE` 900 to 1024 (peak 744 once RAS notifications
      flow). Placed as `configdefault` entries at the end of `common/libs/Kconfig`, gated on
      `APP_CS_ROLES`: the pressure comes from using the roles library rather than from any one
      application, so a build without it is untouched and an application can still override.
      The alternative - the same three lines in four `prj.conf` files - was rejected because the
      next application added would silently miss them.
    - [x] Reduce the application stacks (2026-09-24): `APP_CS_ROLES_THREAD_STACK_SIZE`
      3072 to 1536 (peak 880), `..._EVENT_STACK_SIZE` 2048 to 1024 (peak 568),
      `APP_LOG_THREAD_STACK_SIZE` 1536 to 768 (peak 368). Each carries its measurement in its
      Kconfig help. `cs_role` keeps the widest margin on purpose: the peaks come from one peer
      and two applications, and `cs_client` runs the same code with a host link attached.
    - [ ] `SYSTEM_WORKQUEUE_STACK_SIZE` (2048, peaked 344) is left alone for now - it is a
      Zephyr symbol like the three above and shares their placement question, and the system
      work queue carries whatever work an application posts to it.
    - [x] `APP_HOST_LINK_THREAD_STACK_SIZE` unmeasured, left at 2048, with the reason recorded
      in its Kconfig help (2026-09-24).
    - [x] `thread_analyzer.conf` deleted and the fragment recorded in §15.4 instead
      (2026-09-24). It could not stay shared: the USB log-level lines it needs on the initiator
      are a fatal Kconfig warning on the Tag.

11. **Tag diagnosability (§15.5, §15.6)**
    - [ ] Decide whether a failure between `bt_enable()` and `cs_role_init()` should keep
      returning from `main()`. A reboot, or a repeating error line, would be recognizable; the
      current silent halt is not. Whatever is chosen, the boot log should say the Tag has
      stopped rather than simply ending.
    - [ ] Print the reset cause at boot (`CONFIG_HWINFO`, `hwinfo_get_reset_cause()`;
      `nrfx_reset_reason` backs this on the nRF54L). One line separates a brownout or a bad
      debug-board contact from a lockup or a software reset, which is what the §3 reboot item
      has been missing.
    - [x] Record the `CONF_FILE` trap in `cs_reflector_tag/README.md` (2026-09-24, §15.5): the
      "Build with `CONF_FILE` set, and the antennas disappear" subsection under Build and
      verify, with the boot lines to check and the `.config` grep.

12. **Mode 1 only: subevents with no antenna paths (§18)**
    - [x] `cs_utils` and `cs_roles` accept `num_antenna_paths` 0 for steps without tones, and
      still reject it on a Mode 2 or 3 step (2026-10-01). Native tests extended; `cs_client`
      built.
    - [x] Verify on hardware: a Mode 1 only run works with the fix (2026-10-01, run by the
      user; the earlier `RAS_DATA_LOST` on every procedure is gone).

## 11. Future work

Left out of the current work (2026-09-18). Not scheduled: an item moves back into a section and
the TODO lists only when it is picked up.

- **Task watchdog on the host link thread** (from §3.1). A host that stops reading while DTR stays
  asserted stalls every sender for the report timeout (`CONFIG_APP_HOST_LINK_REPORT_TIMEOUT_MS`,
  responses `CONFIG_APP_HOST_LINK_RESPONSE_TIMEOUT_MS`), including Bluetooth callbacks through
  `client_state_set()`, and nothing resets the client. The idea: `CONFIG_TASK_WDT`, fed by the host
  link thread, so a link that stays stalled for a couple of seconds resets the client. The thread
  keeps running during a stall, so it would feed the watchdog only while the TX ring buffer is
  empty or has drained since the last feed, not on every loop.
- **Large reports: TX buffer size and slow-host policy** (from §3.2, §10 item 3). A mode-3, 4-path
  subevent of 160 steps is about 10 KB. Decide the host link TX buffer size
  (`CONFIG_APP_HOST_LINK_TX_BUF_SIZE`, 16 KB today, about one such subevent) and the slow-host
  policy. Today a subevent that does not fit is dropped whole and counted, and the drop count is
  announced as `LOG_MESSAGE` through `app_log` once room returns. The alternative is
  back-pressure. Base the decision on the hardware throughput in §3.3, then implement it.
- **CS configuration created by the reflector** (the former §8, moved 2026-09-19). A configuration
  creator setting (`INITIATOR` default, or `REFLECTOR`): the reflector calls
  `bt_le_cs_create_config()` with role reflector, its own creation fields and the context "local
  and remote", the initiator waits in `CS_ROLE_STAGE_WAIT_PEER_CONFIG`, and CS security,
  procedure parameters and enable stay with the initiator. Both devices must use the same setting.
  It does not lift any capability limit, so it does not serve the timing study (§8). The one
  hardware run (2026-09-19, Tag reflector-only controller, DK `cs_hostless_initiator`
  initiator-only controller) failed: encryption and the remote capabilities passed, the create
  was accepted, and configuration complete reported 0x20, Unsupported LL Parameter Value, about
  50 ms later on every link, with the default creation fields the initiator uses successfully.
  (The Tag reads the remote capabilities only after encryption: 0x2f before that.) Not tested:
  both-role controllers (`CONFIG_BT_CTLR_SDC_CS_ROLE_BOTH`) on both devices.
- **Quantitative RAS transfer in the planner** (from §13.2, 2026-09-22). §13 marks the ACL events
  that carry RAS real-time data but draws no duration. A predicted duration needs bytes per
  procedure (ranging-data and subevent headers plus per-step data, by mode and antenna paths),
  the segmentation at the ATT MTU, and how many notifications leave per ACL event — and the last
  depends on the MTU, PHY, event length and controller TX buffers, none of which the planner has
  an input for or the specification fixes. Revisit after the §1.9 hardware runs give measured
  drain times to calibrate against; `cs_hostless_initiator/src/main.c` holds the one worked case
  today (about 740 bytes per procedure, 72 mode-2 steps at 1 path, three LL PDUs at ATT MTU 498).
  Narrowed 2026-09-22 by §12.4: once the client reports the negotiated ATT MTU, bytes per
  procedure and the segmentation into notifications and LL PDUs are computable from reported
  values, and only the drain rate — PDUs per ACL event — is left. That single variable is what
  the §1.9 hardware runs would calibrate, and until they do it is the whole of the missing
  model (§13.2). Implemented 2026-09-22 (§13.5) up to that line: bytes, notifications, LL PDUs
  and their air time are drawn as a floor; only the drain rate is still left here.

## 12. ACL connection parameters in the GUI (decided 2026-09-20)

`CONNECTION_PARAMETERS` (protocol `0x000B`, §0) reports the negotiated ACL interval, peripheral
latency, supervision timeout and ATT MTU of the current link. `ClientSession` stores the packet in
`context["connection_parameters"]` and emits `connection_parameters` (`session.py`),
`report_log.py` writes one Session-log line, `recorder.py` records
`/reports/connection_parameters`, and both history stores classify it as a *report* row
(`session_history.py`, `views/session_view.py`). Decision: two surfaces, the Controller view first.
The Controller view now shows the ACL values and ATT MTU;
the CS view uses only the ACL values for its illustration.

### 12.1 Controller view (Results → Controller)

The values are negotiated by the controller against a request the host made —
`connection_interval_min`/`_max`, `connection_latency` and `connection_timeout` are fields of
both host configuration packets — which is the Requested/Negotiated/Status shape the
Configuration and Procedure tables already use.

- `ControllerReports` keeps the latest `ConnectionParametersPacket` (`add()` returns True for it,
  `clear()` forgets it), so a lost link drops it with the other reports as `app.py` already does.
- `controller.py` gains `compare_connection(requested, negotiated)` returning four `Row`s built
  with the existing helpers: Connection interval (`_within` over the requested min/max,
  `× 1.25 ms`), Peripheral latency (`_compare`), Supervision timeout (`_compare`, `× 10 ms`),
  and informational ATT MTU.
- `ControllerView` draws them with `draw_rows` into a fourth group box, "Connection parameters",
  at the top of the right splitter above "Configuration complete": the ACL link precedes the CS
  configuration. Title suffix `· not received` as the other two boxes use.
- Per §3.1 a peripheral does not request connection parameters — `cs_role_link_params.connection`
  is used only when `cs_roles` creates the connection as the GAP central. With `gap_role == 1`
  the Requested column reads "not requested" (`INFO` status), not the inert host values.
- `compare_procedure` converts "Event interval" and "Procedure interval" from ACL events to
  milliseconds only after the negotiated ACL interval is reported. Before then, it shows only
  ACL-event values so the requested interval is not presented as the actual link interval.

### 12.2 CS view illustration

`CsView` draws the anchor, latency and supervision-timeout illustration from the planned
`connection` values. Feed it the negotiated packet the way `app.py` already feeds negotiated CS
timings to `cs_view.apply_config()` — inside the `loading` guard, so it does not mark the host
configuration edited — and the picture shows the link that exists rather than the one planned.
A live link has one interval rather than a range, so `bridge.apply_packet` narrows
`interval_min`/`interval_max` to the reported interval; the scenario then stays valid
(`validate()` requires min ≤ selected ≤ max) and the next request asks for what the link uses.
The planned values are the source until a report arrives, as for negotiated CS timings; a
report is not undone by a lost link. Whether the illustration credits the client is decided by
comparing the three shown values with the last report (`PlannerWidget.reported_connection()`),
not by a flag on the scenario: `Connection` is validated and saved as a request, and an edit to
any of the three values leaves the report behind on its own.

### 12.3 Plumbing (both surfaces)

`QtSession` has a `connection_parameters` signal and its emit hook routes the packet from
`App.cs_packet_received` to both views; this was the failure recorded in §9 item 1.

The simulator did not send `CONNECTION_PARAMETERS` at all, so neither surface could be seen
against it. `Simulator.set_state()` now sends the applied configuration's ACL values whenever it
reports `LINK_CONNECTED`, as `cs_session.c` reports them from its parameter-update callback.

### 12.4 Negotiated ATT MTU in the connection report (decided 2026-09-22)

The report carries the ACL parameters only, and the negotiated ATT MTU cannot be added where
they come from: `bt_conn_info` has no MTU field, so `report_connection_params()`
(`cs_role_link.c`) cannot read one from the connection. The value belongs to the ATT layer —
`bt_gatt_get_mtu(conn)`, with `att_mtu_updated` in a `struct bt_gatt_cb` to know when the
exchange has settled. NCS has no `BT_GATT_CB_DEFINE`: GATT callbacks register at runtime, so
`cs_role_link_init()` calls `bt_gatt_cb_register()` in both of its build variants. Decision: report it as a fourth value of the same packet.

It deserves a protocol field because it is bimodal across our own images and nothing shows which
case a link got. `cs_hostless_initiator/prj.conf` sets `CONFIG_BT_GATT_AUTO_UPDATE_MTU=y` and
reaches 498; `cs_client/prj.conf` did not, and no peer of ours started the exchange instead —
`cs_hostless_reflector` and `cs_reflector_tag` have `CONFIG_BT_GATT_CLIENT` off, and a
`cs_client` reflector has the client but not the Kconfig — so a hosted link between our own
images stayed at the default 23. The RAS responder segments the ranging data at `mtu - 4` (`rd_segment_send()` in the NCS
`bt_ras_rrsp`: three octets of ATT notification header and one of RAS segment header), which is
the difference between 2 and 39 notifications for the 740-byte procedure of
`cs_hostless_initiator/src/main.c` — the two cases §13.2 contrasts in prose today.

Amended 2026-09-22: `cs_client/prj.conf` sets `CONFIG_BT_GATT_AUTO_UPDATE_MTU=y` as well, so a
hosted link exchanges the MTU instead of staying at 23. The Kconfig depends only on
`BT_GATT_CLIENT` and Zephyr starts the exchange from `bt_gatt_connected()` without testing the
GAP role (`subsys/bluetooth/host/gatt.c`), so the one line in the shared `prj.conf` covers a
`cs_client` initiator and a `cs_client` reflector alike, and on a `cs_client`-to-`cs_client` link
both ends request it. The reflector-only images are untouched: `cs_hostless_reflector` and
`cs_reflector_tag` have `CONFIG_BT_GATT_CLIENT` off, so the Kconfig has nothing to depend on.
`CONFIG_BT_L2CAP_TX_MTU=498` and the 502-byte ACL buffers are already there, so the negotiated
value is the 498 the Ranging Profile asks for and no buffer sizing moves. The report (§12.4) is
what makes the change observable rather than assumed: the Controller tab's ATT MTU row reads 23
on a hosted link today and should read 498 afterwards.

- Frame: `mtu` (`uint16_t`) after `timeout` in
  `struct cs_protocol_connection_parameters_frame_t`, growing it from 18 to 20 bytes, at protocol
  version `0x000B`. This is a client→host report, not a staged setting, so the configuration CRC
  and its field order (§9, §10) do not change.
- The client sends the report as it does today (USB session open, DTR rise for the hostless
  initiator, each ACL parameter update) and additionally from `att_mtu_updated`, so an exchange
  that completes after the link is up is not missed. An MTU change and an ACL parameter change
  produce the same packet; `mtu` is 0 while there is no link.
- Controller view (§12.1): a fourth row, "ATT MTU", in the "Connection parameters" box. The host
  never requests an MTU, so the Requested column reads "not requested" and the status is `INFO`,
  as the peripheral case of §12.1 already does.
- The CS view illustration (§12.2) does not use it: the MTU is not part of the anchor, latency
  and supervision-timeout picture. **Amended 2026-09-22 (§13.5):** it does now, as the size of
  the drawn RAS transfer. The report writes `connection.mtu`, which the Connection tab shows in
  its example panel and which holds the ATT default until a link reports its own.

## 13. RAS transfer in the CS view timelines (decided 2026-09-22)

With RAS real-time (`peer_data` 0) the reflector's ranging data travels on the ACL events
between procedures, and nothing in the planner shows it. The consequence is only described in
prose: the schedule note at `planner/model.py` ("RAS real-time with a minimum procedure interval
of 1 ACL event: the reflector's RAS data needs ACL events between procedures, or it arrives late
and aborts the next procedure") and `cs_hostless_initiator/README.md`. Decision: draw the RAS
events as occupancy, and do not predict the transfer duration. Amended 2026-09-22 (§13.5): the
occupancy is drawn with a width, the air time computed from the reported ATT MTU (§12.4); the
drain rate is still not predicted.

### 13.1 Which views

Only the two ACL-scale views. *3 Event*, *4 Step* and the channel views are intra-procedure at
microsecond scale, where RAS does not exist.

- **1 Connection** (`draw_connection`, lanes *Peripheral example / Central · anchors / Selected
  CS*): mark the anchors that follow the CS subevents of the shown procedure.
- **2 Procedures** (`draw_procedures`): lane 2 draws an ACL anchor marker per CS event only
  (`anchor = i * spacing + event * p.event_interval * c`). The anchors in the gap between
  procedures — the RAS ones — are not drawn at all, so they are new blocks, not recolored ones.

Both are driven by `peer_data`, which `refresh()` already reads
(`self.host_settings.get("peer_data", 0)`, the same value it passes to `build_schedule`). With
`peer_data` 1 the marking disappears, which is the visible counterpart of the existing
"no RAS notifications between procedures" note.

**Amendment (2026-09-22, §13.5).** The marking became a lane of its own in both views,
*RAS (reflector)*, rather than a recoloring of the anchors: the blocks now have a width, and the
anchor markers keep meaning "a point in time". `host_edited()` had to start the recompute timer
for either view to follow `peer_data` at all; it only emitted `configuration_changed` before.

### 13.2 Occupancy, not duration (superseded in part by §13.5)

A drawn RAS box would need bytes per procedure, then notifications at the ATT MTU, then ACL
events to drain. The first step is tractable — the ranging-data and per-subevent headers plus
per-step data, sized by mode and antenna paths, and `cs_hostless_initiator` already carries a
worked case: about 740 bytes per procedure for 72 mode-2 steps at 1 path, three LL PDUs at ATT
MTU 498 (`src/main.c`), against 19-byte segments without an MTU exchange (`prj.conf`).

The last step is not. How many notifications leave per ACL event depends on the ATT MTU, the
PHY, the event length and the controller's TX buffers. The planner has no field for any of them,
and none is spec-deterministic: every prediction it makes today is controller timing defined by
the specification, declared as such in the schedule notes ("Predicted timing; mode cadence is
deterministic, not the controller's randomized sequence"). A RAS box would be the first width
drawn from an assumption about host throughput, and would read as a prediction at the same
weight as the step timing beside it. Mark the events as reserved for RAS instead; the width of
an anchor marker already means nothing (`timing_duration=0`, "marker width is only for
visibility, not ACL airtime").

**Amendment (2026-09-22, with §12.4).** Once the client reports the negotiated MTU, the second
step stops being an assumption: the responder segments at `mtu - 4`, so notifications per
procedure are `ceil(bytes / (mtu - 4))` and the LL PDUs each one costs
`ceil((4 + 3 + data) / DLE)` with `CONFIG_BT_CTLR_DATA_LENGTH_MAX` 251 — arithmetic over a
reported value rather than a guess. The decision stands, because the third step is what a drawn
width would rest on. PDUs drained per ACL event depend on the reflector's event length and TX
buffer count (`CONFIG_BT_CTLR_SDC_MAX_CONN_EVENT_LEN_DEFAULT` 7500 µs,
`CONFIG_BT_CTLR_SDC_TX_PACKET_COUNT` and `CONFIG_BT_BUF_ACL_TX_COUNT` 3 in the built initiator
image) and on how quickly the peer's host refills the controller: its build, which the link does
not report, and controller scheduling, which the specification does not fix. What the reported
MTU does allow — and what §13.1's marking may carry as text, never as width — is a count and a
floor: N notifications, M LL PDUs, at least K ACL events. That is the same occupancy stated more
precisely, not a predicted duration.

**Superseded in part (2026-09-22, §13.5).** The width is drawn after all, from the air time of
those M PDUs. What stays is the reason: the drain rate is not predicted, and the drawn width is a
floor rather than a schedule.

### 13.3 Standalone planner

Excluded, by the existing §9 decision (2026-09-19): the standalone `ble_channel_sounding_planner` does not expose
or serialize `peer_data`, because reflector data is a host/session setting. `ble_channel_sounding_planner`'s
`build_schedule(s)` has no `peer_data` parameter at all, so the marking has no input there and
the views stay as they are. This is the pre-existing rule, not a new exception.

### 13.4 Left out

A quantitative RAS transfer model (§11). Worth revisiting only after the §1.9 hardware runs
provide measured drain times to calibrate against; predicting them offline first would fix an
assumption that the hardware is about to answer.

**Narrowed (2026-09-22, §13.5).** Bytes, notifications, LL PDUs and their air time are now
computed. What is left out is only the drain rate — PDUs per ACL event — which is what the §1.9
runs would calibrate.

### 13.5 Drawn air time from the reported MTU (decided 2026-09-22)

The §12.4 report makes the transfer computable, so the lane carries a width: the air time of the
PDUs, and before an exchange is reported the air time at the ATT default the link starts on. This
supersedes §13.2's "no width", not its reasoning — the width is a floor, and the caption, the
tooltip and the schedule note all say occupancy rather than drain rate.

- `Schedule.ras` (`RasTransfer`, `model.py`) holds the MTU and its source, the bytes,
  notifications, LL PDUs, total air time and the air time placed in each successive ACL event.
  It is `None` with `peer_data` 1 and without a schedule, which is what removes the drawing.
- Sizes: a 4-byte ranging header, 8 bytes per subevent, and per step a 1-byte step header plus the
  reflector's step data (mode 0 is 3 bytes; RTT 6, or 14 with a sounding sequence; tones
  1 + 4 per antenna path and extension slot). The `cs_hostless_initiator` case confirms them:
  736 bytes, 2 notifications and 3 LL PDUs at MTU 498, 39 notifications without an exchange —
  the figures `src/main.c` and `prj.conf` record from hardware.
- Segmentation: `ceil(bytes / (mtu - 4))` notifications, each L2CAP frame fragmented at
  `CONFIG_BT_CTLR_DATA_LENGTH_MAX` 251, as the §13.2 amendment derived.
- Air time per PDU: an empty PDU, the fragment and two T_IFS gaps. `ll_packet_us()` covers
  LE 1M, LE 2M and both coded rates; the empty-PDU times (80, 44, 720 and 462 µs) fix it.
- MTU: a connection parameter, not a hidden input (decided 2026-09-22 on review: "the MTU must be
  reported in connection parameters config with default"). `Connection.mtu` joins interval,
  latency and timeout, defaults to `ATT_DEFAULT_MTU` 23, is validated 23–517 and is shown as
  *ATT MTU* in the Connection tab's example panel — the controller-selected panel, because the
  host never requests an MTU. `apply_packet` writes the reported value from
  `ConnectionParametersPacket` beside the ACL values, and a report without one (no link, or a
  client older than protocol `0x000B`) leaves the default. It is an `EXAMPLE_FIELDS` entry, so it
  is never sent or exported, and editing it explores another MTU. The model labels the value
  itself ("the ATT default, before an MTU exchange"); the view adds where it came from —
  reported by the client, or an example that is not.
- The standalone `ble_channel_sounding_planner` has no MTU, and its `loads()` now drops group fields it does not
  have, so a ble-channel-sounding plan file still loads there (the §9 decision's file compatibility).
- PHY: the RAS data rides on the ACL, and nothing reports the ACL PHY. Decision (2026-09-22, asked
  and answered): reuse the host `phy` setting rather than add an ACL PHY field. It is the
  procedure parameters' TX-power-delta reference, so the two meanings are coupled and its default
  LE 1M draws a slower link than the images here reach (`CONFIG_BT_CTLR_PHY_2M` with Zephyr's
  automatic PHY update). The tooltip, the setting detail, the Host tab help and the drawn caption
  all name the PHY the air time uses, so the assumption is visible and one control changes it.
- Fill: successive ACL events take at most one connection interval of air time each, so the event
  count is a floor. A note warns when the air time exceeds the window between the first anchor
  after the procedure and the next procedure — the drawn overlap, stated in words.
- *1 Connection* draws every preview procedure that starts inside its 12-anchor window, at
  Procedure spacing, rather than the first alone. It drew one procedure before, which read as if
  the schedule did not repeat and left the RAS blocks of a late transfer sitting in empty space
  instead of over the procedure they delay.

## 14. Main-mode step bounds only with a sub-mode (decided 2026-09-23)

`min_main_mode_steps` and `max_main_mode_steps` bound how many main-mode steps run before a
sub-mode step. Zephyr says so on the field itself, and the controller agrees: a temporary log of
the raw `bt_conn_le_cs_config` in `cs_role_core.c` shows it reporting `main steps 0-0` for a
mode-2 configuration whatever was requested (§1.9 step 9, 2026-09-23). They mean nothing without
a sub-mode.

The planner already knows this. `unused_fields()` (`planner/model.py`) returns `SUB_MODE_FIELDS`
whenever `mode >> 4` is zero, so for modes 1, 2 and 3 the three keys
`configuration.min_main_mode_steps`, `configuration.max_main_mode_steps` and `main_steps` are
classified unused and the CS view disables them. What it does not do is stop exporting them: the
serialized values survive, `cs_initiator_config_set_creation()` carries them, and they go out in
LE CS Create Config. The 2026-09-19 export shipped `min 1, max 4` on a mode-2 configuration for
exactly this reason.

**Decision.** Without a sub-mode the export writes the neutral value rather than whatever the
scenario last held. A disabled control must not be able to change what the firmware sends.

Open, to settle when it is picked up: which value is neutral. `1, 1` states "no main-mode run to
bound" and is what the 2026-09-23 runs used; the model defaults are `2, 10`. The spec allows
0x01-0xFF and the controller reports 0 back either way.

Why it matters beyond tidiness: the user's reading on 2026-09-23 is that
`max_main_mode_steps` above 1 costs a second ACL event, and `procedure_interval` 1 appeared in
the same build that brought it from 4 to 1. That is not isolated yet (§1.9 step 9), but a field
the GUI greys out should not be able to halve the update rate.

Note for whoever implements it: changing the exported values changes the configuration CRC, so
the shared vectors in `tests/test_protocol.py` and `tests/host_link/test_config_store.c` move
together (§9 protocol order). The standalone `ble_channel_sounding_planner` carries the same `SUB_MODE_FIELDS`
rule and needs the same treatment.

## 15. Controller capability limits and the stack measurement (2026-09-24)

Found while building the deepest configuration this pair will run, for the stack high-water-mark
measurement (§3 "Roles and timing"). The configuration lives in
`configs/cs_generated_config_initiator.c`, hand-written rather than exported; it carries the
findings below in its header comment so the next person editing it does not retry them.

### 15.1 The SDC rejects a CS sub-mode

`CS_CONFIG_MODE_3_SUB_MODE_2` (0x23) makes LE CS Create Config fail with
`opcode 0x2090 status 0x11` ("Unsupported Feature or Parameter Value"), raised by the
initiator's own controller before anything reaches the air. The reflector never sees a
configuration and only observes the initiator hanging up (HCI 0x13) a few hundred ms after
`waiting for the initiator`, so the reflector log alone cannot diagnose this.

The rejection is not conditional on anything else in the record: it persisted with RAS real-time
and with the sounding RTT type removed, and plain `CS_CONFIG_MODE_3` with otherwise identical
parameters is accepted. Nothing in `CONFIG_BT_CTLR_SDC_CS_*` gates sub-modes;
`BT_CTLR_SDC_CS_STEP_MODE3` enables mode-3 *steps*, not a sub-mode.

**Consequence.** `min_main_mode_steps` and `max_main_mode_steps` are dead parameters on this
controller — no configuration it accepts can have a sub-mode for them to bound. That is the
practical form of the §14 decision: the neutral pair is not a tidiness question here, it is the
only pair that can ever be exported.

### 15.2 The SDC rejects a sounding-sequence RTT type

`CS_CONFIG_RTT_TYPE_32_BIT_SOUNDING` fails the same way, `0x2090 / 0x11`, both with and without
a sub-mode. `CS_CONFIG_RTT_TYPE_AA_ONLY` is accepted and the link runs. A sounding sequence needs
`rtt_sounding_n > 0` in the controller's capabilities
(`sdc_hci_subevent_le_cs_read_remote_supported_capabilities_complete_t`); the local capabilities
report carries the same fields and was not read during these runs, which is how this cost three
flash cycles instead of one.

**Consequence.** Mode-3 steps on this hardware time RTT from the access address only. The random
and 96-bit sounding types are untested and, on this evidence, unlikely to be accepted.

### 15.3 The configuration that does run

Mode 3, RTT AA-only, two antenna paths (A1:B2), three mode-0 steps, all 72 channels, RAS
real-time, IPT requested, T_PM 10 us, 30 ms connection interval, 16 ms subevent
(`max_procedure_len` 26):

- `procedure_interval` 2, so 16.7 procedures/s.
- **114 steps per procedure** (117249 steps over 1034 procedures), against 74 in the 2026-09-23
  mode-2 runs. About 1900 steps/s against 1240.
- Zero aborted and zero partial subevents over four minutes and 3034 procedures.
- `RAS data lost` 42 of 3034 procedures. The rate builds to a steady state rather than being
  constant from the start: 0 in the first 1000 procedures of the run, then 11, 16 and 15 in each
  following thousand, so about 1.5 percent sustained. That is the §3.3 fault (b) reproduced at
  mode 3 with two paths, and it is worse than the 0.5-1 percent recorded for mode 2 with one
  path - consistent with the fault scaling with RAS payload per procedure rather than being
  specific to one configuration.

### 15.4 Stack high-water marks: the opposite of the expected result

Measured with `CONFIG_THREAD_ANALYZER` on `cs_hostless_initiator` under the configuration above.
Interim: four minutes of steady state plus one boot of connect/encrypt/disconnect churn at 2.3 s
per cycle, which is where the link-setup paths peak. Every figure below except `ISR0` had
plateaued by the first minute of ranging and did not move again; `ISR0` creeps (432 bytes at one
minute, 576 at three and a half) and is the only one still rising at four minutes, at 28 percent
of 2048.

Peaks from both ends of the same link. "Init" is `cs_hostless_initiator` on the DK, "Refl" is
`cs_reflector_tag`; a dash means the thread does not exist in that application.

| Thread | Init | Refl | Max | Size | Symbol |
| --- | --- | --- | --- | --- | --- |
| `BT LW WQ` | **1864** | 1192 | 1864 | 2104 | `BT_LONG_WQ_STACK_SIZE` |
| `MPSL Work` | 496 | **768** | 768 | 1024 | `MPSL_WORK_STACK_SIZE` |
| `bt_tx_processor` | **744** | 404 | 744 | 904 | `BT_TX_PROCESSOR_STACK_SIZE` |
| `usbhs@20000` | 304 | - | 304 | 512 | driver |
| `BT RX WQ` | 1744 | 1264 | 1744 | 3200 | `BT_RX_STACK_SIZE` |
| `logging` | 608 | 528 | 608 | 2048 | `LOG_PROCESS_THREAD_STACK_SIZE` |
| `cs_role` | 880 | 768 | 880 | 3072 | `APP_CS_ROLES_THREAD_STACK_SIZE` |
| `cs_role_events` | 568 | 568 | 568 | 2048 | `APP_CS_ROLES_EVENT_STACK_SIZE` |
| `ISR0` | 576 | 556 | 576 | 2048 | `ISR_STACK_SIZE` |
| `BT RAS RRSP WQ` | - | 520 | 520 | 1024 | `BT_RAS_RRSP_WQ_STACK_SIZE` |
| `app_log_thread` | 368 | 368 | 368 | 1536 | `APP_LOG_THREAD_STACK_SIZE` |
| `sysworkq` | 344 | 328 | 344 | 2048 | `SYSTEM_WORKQUEUE_STACK_SIZE` |

The four stacks §3 asks us to resize are the four with the most headroom: no application thread
exceeds 29 percent on the heaviest configuration the hardware accepts, in either role. The three
near the edge are Zephyr and MPSL stacks at their Kconfig defaults, with no override anywhere in
this workspace, and each peaks in a different place:

- `BT LW WQ` reached 88 percent on the initiator during link setup, not during ranging, so the
  reconnect path is what sizes it; the reflector's own peak is 1192.
- `MPSL Work` reached 75 percent on the **reflector** and only 48 on the initiator. Had the Tag
  not been measured this would have been missed entirely, which is the argument for measuring
  both ends of a shared library rather than one.
- `bt_tx_processor` went from 404 to 744 bytes on the initiator the moment RAS notifications
  began, and stayed at 404 on the reflector that sends them.

Everything except `ISR0` plateaued within the first minute of ranging and never moved again over
four minutes; `ISR0` creeps (432 bytes at one minute, 576 at three and a half), which reads as
interrupt-nesting variability rather than growth, and it is at 28 percent.

`APP_HOST_LINK_THREAD_STACK_SIZE` is not in the table and cannot be measured this way:
`host_link_report_only_init()` starts no thread, so the hostless applications never create it.
It needs a `cs_client` run.

To repeat the measurement, build with an extra Kconfig fragment holding:

```
CONFIG_THREAD_ANALYZER=y
CONFIG_THREAD_NAME=y
CONFIG_THREAD_ANALYZER_USE_LOG=y
CONFIG_THREAD_ANALYZER_LOG_LEVEL_INF=y
CONFIG_THREAD_ANALYZER_AUTO=y
CONFIG_THREAD_ANALYZER_AUTO_INTERVAL=30
CONFIG_THREAD_ANALYZER_RUN_UNLOCKED=y
CONFIG_THREAD_ANALYZER_AUTO_THREAD_PRIORITY_OVERRIDE=y
CONFIG_THREAD_ANALYZER_AUTO_THREAD_PRIORITY=14
CONFIG_THREAD_ANALYZER_ISR_STACK_USAGE=y
CONFIG_LOG_BUFFER_SIZE=8192
```

`THREAD_ANALYZER` selects `INIT_STACKS`, so the marks are cumulative from boot and a reset
discards them. `RUN_UNLOCKED` matters: walking every stack word by word with interrupts locked
is long enough to drop a subevent. The analyzer thread goes below the log thread's priority so
analysis never preempts the role, event or host-link threads, and the console log level stays at
info while only the protocol sink goes to debug - at debug on both, the analyzer's own blocks are
what the UART drops.

On `cs_hostless_initiator` the USB device stack also needs silencing, or its per-transfer `INF`
lines overrun the log buffer and take analyzer blocks with them:

```
CONFIG_UDC_DRIVER_LOG_LEVEL_ERR=y
CONFIG_USBD_LOG_LEVEL_ERR=y
CONFIG_USBD_CDC_ACM_LOG_LEVEL_ERR=y
```

Those three belong to the initiator only. On the Tag, which has no USB device stack, assigning
them is a fatal Kconfig warning ("was selected, but no symbol ended up as the choice
selection"), so the two applications need separate fragments rather than one shared file.

### 15.5 The Tag build silently drops its board configuration

`cs_reflector_tag/boards/nrf54l15tag_nrf54l15_cpuapp.conf` carries
`BT_CTLR_SDC_CS_NUM_ANTENNAS=2`, `MAX_ANTENNA_PATHS=4` and `BT_CTLR_EXTENDED_FEAT_SET=y`. Zephyr
merges `<app>/boards/*.conf` only when `CONF_FILE` is undefined
(`zephyr/cmake/modules/configuration_files.cmake`, the board lookup sits inside
`if(NOT DEFINED CONF_FILE)`). A build that sets `CONF_FILE` explicitly — the VS Code nRF Connect
extension does — drops all three without a warning.

The failure mode is confusing because the board *overlay* is passed separately through
`DTC_OVERLAY_FILE` and still applies: the device tree has the `bt-cs-antenna-switch` node while
the controller reports one antenna, so the hardware looks present and the capability is gone. The
Tag then fails `check_antennas()` and returns from `main()`.

This also explains the reboot recorded in §3 as unexplained. On 2026-09-24 a Tag that had been
running cleanly showed a banner mid-session and came back with Bluetooth threads but no
`cs_role` / `cs_role_events` in the thread analyzer and no advertising. That was not a brownout:
it was a reflash to a build without the board conf, whose new boot took the
`TEST FAIL configuration does not fit the controller` early return. The error lines were lost
because the Tag's RTT backend is `LOG_BACKEND_RTT_MODE_DROP` and the viewer was detached across
the flash.

Build the Tag from the CLI, as `AGENTS.md` documents, and check
`nRF54L15 Tag CS reflector: 2 antennas` in the boot log before trusting a run.

### 15.6 Returning from `main()` leaves the Tag silently alive

Every failure between `bt_enable()` and `cs_role_init()` in `cs_reflector_tag/src/main.c` is a
`return 0`. The application thread ends, Bluetooth stays up, no role threads are created and
nothing advertises — indefinitely, with no further output. A device in that state is powered,
enumerates over RTT and does nothing, which is the hardest failure to recognize remotely. See
§10 item 11.

## 16. Discovery lists peers matching the scan prefixes (decided 2026-09-24)

`cs_client` reports every advertiser during host-driven discovery (`peer_discovery.c`,
`SCAN_RESULT` contract in `common/libs/cs_protocol/README.md`), and the Peers view listed all of
them, so the scan prefixes applied with the configuration had no visible effect.

**Decision.** Filter in Python, not in the firmware. The wire contract stays: `SCAN_RESULT`
still carries every report, including unnamed, nonconnectable and non-matching peers. The Peers
view lists only peers whose advertised name starts with one of the applied prefixes, compared
as bytes like `cs_role_link.c`'s own match, and a **Show all** check box lists every report. An
unnamed peer is hidden until a scan response names it. No protocol, CRC or firmware behaviour
change. Implemented the same day (§9 item 15).

## 17. Preferred peer antennas are checked on both sides (decided 2026-09-24)

The Tag hard-faulted in the controller's antenna-switch interrupt (`ASSERTION FAIL ... Unsupported
pin`, `gpio.h:1698`) right after a `cs_client` initiator enabled procedures. The host plan sent
`preferred_peer_antenna` 4: a bit mask, so reflector antenna 3, on a two-antenna Tag. The Tag's
controller switched to antenna index 2 unchecked; the SDK's `cs_antenna_switch.c` table holds four
entries, and the overlay fills only the first two, so entry 2 has a NULL port and `gpio_pin_set_dt()`
asserted on garbage read through it. With A1:B2 requested, the link negotiated A1:B1, probably
because one bit is too few for B2 (not confirmed against the controller). Nothing on either side
checked the mask: `ble_channel_sounding` offered a plain 0–15 box and sent it as is,
`host_link_config_check_antennas()` checks only the local side, and the `cs_utils` procedure
setters copied it.

**Decision.** Two rules, both in firmware and mirrored in Python:

1. Record validity, in `cs_*_config_set_procedure()` (`-EINVAL`): the tone antenna configuration is
   defined, and the mask names antennas 1–4, is non-zero and sets at least as many bits as the
   configuration's peer side (B for an initiator, A for a reflector). A1:B2 needs 3 from the
   initiator. Python: `validation.validate_preferred_peer_antenna()` in `ClientSession.apply()`,
   the simulator's `SET_CS_*_CONFIG` handling and both C exporters (`ble_channel_sounding`, `ble_channel_sounding_planner`).
   Report ingestion (`bridge.config_packet()`) does not check, so plans saved with a bad mask still load.
2. The peer's antennas, in `cs_roles` at remote capabilities: an initiator whose mask has a bit
   above the reflector's `num_antennas_supported` fails with the new
   `CS_ROLE_FAILURE_PEER_ANTENNA` and `-ERANGE`, before any configuration or procedure. Like
   `PEER_IPT` it is not restarted (`auto_restart`): the same peer would fail again. `cs_client`
   reports it as `CLIENT_STATE(ERROR, CS_CONFIG_FAILED, -ERANGE)`, so there is no new protocol reason
   or version; `cs_hostless_initiator` halts as for `PEER_IPT`. Python lists it as a run failure in
   `check_compatibility()`. A reflector's mask (initiator antennas) is not checked against the
   initiator's capabilities.

`cs_hostless_initiator`'s fallback now prefers reflector antennas 1 and 2 (3). The generated
initiator export already did. The Tag overlay stays as it is: placeholder entries for antennas 3
and 4 would hide the fault but switch the wrong antenna.

Built (`cs_client`, `cs_hostless_initiator`, `cs_reflector_tag`); the native tests pass, and the
Python suite apart from the planner tooltip-hover test, which fails in the full run without this
change as well. Not verified on hardware. To verify: `cs_client` initiator with mask 4 against the Tag ends in
`CS_CONFIG_FAILED, -ERANGE` and the Tag keeps running; with mask 3 and A1:B2 the Tag logs
negotiated antenna configuration 4 and two-path subevents.

Done 2026-09-25: Preferred peer antenna is four check boxes (ANT1–ANT4, bits 0–3) in the `ble_channel_sounding`
CS view and in `ble_channel_sounding_planner`, not a 0–15 number box. The mask shows beside them, with a warning while
fewer boxes are checked than the peer's side of the antenna configuration needs. Bits above 3 in a
loaded plan are kept and shown in the warning colour, so validation still reports them.

## 18. Mode 1 only reports no antenna paths (found and fixed 2026-10-01)

A Mode 1 only run reported `RAS_DATA_LOST` for every procedure. Nothing was lost on the link.
Without phase measurement the controller reports `num_antenna_paths` 0 in every subevent result
(HCI: "ignored because phase measurement does not occur"; NCS commit `66e76007db` says the same of
`n_ap` "in the case of RTT only"), and the RAS responder copies that into the ranging header as an
empty `antenna_paths_mask`. `cs_utils` and `cs_roles` treated 0 as invalid in five places:

- `ras_ranging_header()` in `cs_role_initiator.c` stopped the RAS parser before the first subevent,
  so `stream_procedure()` returned `-EBADMSG` and the procedure was reported lost.
- `cs_role_stream_hci()` in `cs_role_events.c` returned without a report, so the local subevents
  were dropped as well. Only the RAS loss was visible on the host.
- `cs_step_decode()`, `cs_subevent_parse()` and `cs_ras_map_subevent()` rejected it with `-EINVAL`.

**Fix.** 0 to 4 antenna paths are accepted. A step that carries tones (Mode 2 or 3) still needs at
least one and fails `cs_step_decode()` with `-EINVAL`, which ends the subevent there as incomplete.
The subevent header reports the 0 as it is; nothing is clamped to 1 as the NCS sample does. No wire
format, protocol version or CRC change: the field was already a byte, and its documented range in
`cs_protocol_packets.h` is now "1..4; 0 without phase measurement". Python needed no change:
`ResultStore`, RTT pairing and the Results and Session views take a zero-path subevent as they are
(checked with a synthetic Mode 1 procedure), and `test_protocol.py` now pins the round trip.

Tests: `tests/cs_roles` covers the empty mask in `cs_ras_map_subevent()`, a RAS procedure with an
empty mask being streamed instead of lost, zero-path Mode 0/1 subevents through both streaming
passes and the record parser, and a Mode 2 step on a zero-path subevent being refused. Each new
case fails against the previous code. Native tests and the Python suite pass; `cs_client` builds.

No Mode 1 recording existed to check the diagnosis against beforehand, so the cause rested on the
code path and the NCS commit. Confirmed on hardware the same day (§10 item 12): the user ran Mode 1
only with the fixed initiator image and it works. The reflector image needs no reflash for this:
its RAS responder is NCS code and was already sending the data.
