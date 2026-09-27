# CS configuration and timing (planner)

The **Configuration** tab of `ble-channel-sounding` in a CS operation mode. The Qt view lives in
`ble_channel_sounding/views/cs_view.py`; this package holds its Qt-free logic: `model.py`
(schedule), `channels.py` (CSA #3a/#3b/#3c example sequences), `bridge.py`
(packets ↔ scenario) and `export_c.py` (planner JSON and hostless C export).

## Views

1. **Connection:** the first 12 ACL anchor positions, selected versus requested
   connection interval, example peripheral attendance under latency, an assumed
   ACL activity width, and every preview procedure that starts inside that
   window, at Procedure spacing. A **RAS (reflector)** lane holds the
   reflector's real-time ranging data on the ACL events after each procedure
   (see *RAS real-time transfer* below), so a transfer running into the next
   procedure is visible. A separate axis illustrates supervision timeout
   measured from a hypothetical last valid reception.
2. **Procedures:** repeated procedure instances, their maximum budgets, CS events,
   and the associated ACL anchors, with the same **RAS (reflector)** lane per
   instance. The preview repeats the same illustrative schedule, capped by the
   preview count or finite procedure count.
3. **Events & subevents:** the selected event, full subevent budgets, occupied
   time, and individual steps separated into mode lanes. Repeated main steps
   are marked `R` in labels/tooltips.
4. **Individual step:** chronological initiator and reflector transmit structures,
   packet/tone periods, antenna-path slots, extension slots, ramp-down, guard,
   and interlude timing. Hover narrow blocks to see their labels and exact
   durations. Frequency-hop gaps are shown in the event view, outside the
   individual step's start/end range.
5. **Channels:** an **example** hop sequence for the first procedure (channel versus
   step index, colored by mode, hollow markers for repeated steps, dashed subevent
   boundaries), above the channel map on a 2402–2480 MHz axis with reserved channels,
   per-channel use counts and 20 MHz Wi-Fi 1/6/11 bands for reference. Click a marker
   to open its step; click a channel to toggle it.

## Settings tabs

Each settings tab lists the values sent to the client (`bridge.py`) or exported to C first.
Below them, a panel headed **Example config values selected by the controller** holds the
values that are never sent (`EXAMPLE_FIELDS` in `model.py`):

| Tab | Example values |
| --- | --- |
| Connection | Selected interval (the central's choice within the requested range), ACL activity example, ATT MTU (23 until an MTU exchange; reported with the connection parameters), CS offset from anchor |
| CS modes | Illustrative main run; T_IP1, T_IP2, T_FCS, T_PM (negotiated, reported at CS configuration complete); T_SW, T_SW_IPT (declared in the CS capabilities) |
| Schedule | Fresh-step workload; Subevents / event, Subevent spacing, CS event spacing (reported at procedure enable complete); Preview instances |
| Channels | Example seed |

The host cannot request these: the HCI CS configuration and procedure parameter commands
have no fields for them. They stay editable so the prediction can explore them, and applied
controller reports replace them. The panels stay editable while a run or hostless mode
locks the sent settings. The planner JSON layout is unchanged.

### Help pane

Below the settings tabs, a help pane with two views explains them (`views/control_help.py`):

- **About this tab** gives the general definitions for the current settings tab: what the group
  controls and how its fields relate (for Connection: interval, latency and supervision timeout,
  and how the interval sets the CS procedure and event periods). It links to each setting on the tab.
- **Setting details** shows the detailed entry of one setting: its tooltip, then what it defines
  (the HCI parameter or LL value), where Core v6.3 defines it (volume, part, section and parameter
  name) and the effect of a change on the plan (step, subevent or procedure duration, steps per
  subevent, validation) and on other controls. It notes when the setting is read-only.
  Selecting a setting (click, Tab or a link in About this tab) shows its entry at once;
  resting the pointer on it shows it after 400 ms.

Every setting has one key. Its tooltip (`*_CONTROL_HELP`) is the short form and `CONTROL_DETAILS`
holds the three detailed parts, so both are kept in one module; the GUI tests check that every
control has both.

The **Channels** settings tab edits the channel map (toggle grid, All/Even/Odd/None
presets, or 20-character hex in planner-JSON byte order), map repetition, CSA #3b/#3c
selection, the #3c shape/jump (read-only with #3b) and the example seed. Imported
reserved bits are kept and reported rather than silently cleared.

**The actual hop sequence depends on the CS DRBG state.** That state comes from the
security setup and advances every procedure, so no offline tool can predict the real
channels. `channels.py` follows the structure of Core 6.1 Vol 6 Part H §4.1–4.2 —
`cr1` shuffling, a separate mode-0 array (#3a), #3b shuffles, #3c hat/X ramps with
Table 4.2 parameters, salt insertion, filtering and block shuffling, regeneration on
exhaustion, mode-1 sub-mode and Main_Mode_Repetition channel reuse — but draws its
random numbers from a seeded Python PRNG (`Scenario.channel_seed`) instead of the
DRBG and `hr1`. Different seeds show other sequences with the same structure; step
timing does not depend on the seed. Each previewed procedure instance replays the
same example. Channel counts that follow from the rules, not the random draws (for
example, when #3b cycles run out), are reliable; #3c array lengths vary with the
random salt counts.

Change any field to recalculate. Hover any box for its meaning, start, end and
duration. Click a procedure, event, subevent or step to drill down; the selectors
at the top provide the same navigation. Selecting a later procedure preserves
that instance's offset in the detailed views. Mouse wheel zooms, drag
pans, and **Fit views** restores the calculated extents. **Open/Save** round-trip
planner JSON files. **Export view** saves the current view, including its
explanation, as PNG; individual plots also expose PyQtGraph's export tools.

The header reports completed/target fresh steps, subevent and CS-event counts,
elapsed procedure time, and total steps including calibration and repetitions.
An incomplete workload is explicitly distinguished from one that fits.
Errors and early closure messages include **What to correct**, naming the input
controls and calculated minimum values where available. Corrections address the
reported constraint; changing one budget may require adjusting its parent spacing.

All CS views share a time origin at the **first ACL anchor**. Detailed x-axis
ranges run exactly from the selected event/subevent/step's scheduled start to
its executed end, with the endpoints labeled on the axis. Subevent budgets may
extend beyond the executed end; their full reserved end is still in the tooltip.
The step axis uses µs and includes the CS offset and selected procedure's position
in the campaign, rather than resetting to zero. These are predicted schedule
coordinates, not measured hardware timestamps. The supervision-timeout illustration
has its own explicitly labeled origin at the last valid reception.

## Data and integration

`Scenario.configuration` is the existing `CsConfigurationPacket` and
`Scenario.procedure` is the existing `CsProcedureEnableCompletePacket`, imported
from `ble_channel_sounding.protocol.packets`. These remain the canonical field layouts and retain
their wire encoding. Planner-only assumptions live in `Scenario`/`Connection`.

### Applying configurations to the view

Call these on the Qt GUI thread:

```python
view.apply_config(Scenario())                    # a default configuration as a whole
view.apply_config(config_frame, procedure_frame)  # negotiated reports as received
view.apply_channel_list([2, 3, 4, *range(40, 60)])
```

`apply_config` accepts, in any mix and applied in order:

| Item | Effect |
| --- | --- |
| `Scenario` | Replaces everything (defaults, or a loaded planner file). |
| `CsConfigurationPacket` | Negotiated configuration replaces the CS configuration; `procedure.config_id` follows its `id`. |
| `CsProcedureEnableCompletePacket` | Negotiated procedure replaces the procedure parameters. |
| `CsInitiatorConfigPacket` / `CsReflectorConfigPacket` | Requested connection/procedure ranges and, for the initiator, the `creation_*` fields. The planner's selected interval, subevent length, procedure spacing and illustrative main run are clamped into the requested ranges. |

Each item may be the decoded dataclass, a received `Frame` (packet type plus
payload, as yielded by `PacketReceiver`) or complete wire-frame bytes. All items
are decoded before the view changes, so a malformed frame (`ValueError`) or a
non-configuration packet (`TypeError`) leaves it untouched. The provenance line
reports whether controller-negotiated or host-requested fields were applied.

`apply_channel_list` takes CS channel indices (0–79) or a raw 10-byte map. Reserved
channels are kept and reported by validation, not silently removed.

Actual connection timing, event offset, antenna switching time and workload remain
local assumptions; the packets do not provide every input needed for a complete
timeline. Editing the controls marks the configuration hypothetical again.
`apply_controller_packets(configuration, procedure)` remains as a wrapper.

### Collecting a configuration to transmit

**Apply config** in the main window calls `collect_config()`, which refuses with the
listed problems when the plan is invalid and otherwise returns a
`CsInitiatorConfigPacket` or `CsReflectorConfigPacket` for the selected operation mode:

```python
packet = view.collect_config(OperationMode.CS_INITIATOR)  # raises ValueError if invalid
```

The planner's selected procedure spacing and subevent length are requested as
min = max. Host fields the planner does not show (GAP role, CS_SYNC antenna, TX
power, procedure PHY, TX power delta, peer antenna, SNR control, creation context)
start from the firmware defaults in `cs_utils/cs_config.c` and are replaced by the
last applied initiator/reflector config, so a received host config round-trips.
T_IP1/T_IP2/T_FCS/T_PM have no host-packet field; the controller selects them.
A CS initiator can ask for a T_PM of 20 or 40 µs with the `t_pm` host setting,
which travels as its own `SET_T_PM` packet (`python/README.md`). The UI defaults
to 40 µs, the mandatory Core Specification value; 10 µs remains the optional
no-preference value.
The session sends `SET_OPERATION_MODE` before and `APPLY_CONFIG` after it.

The conversions live in `bridge.py` (standard library and protocol dataclasses
only): `decode_config`, `apply_packet`, `apply_channel_list` and `config_packet`.

JSON files use a versioned planner schema, with the channel map encoded as hex;
they are not configuration commands and are not transmitted to devices. A saved
file is a complete configuration:

| JSON key | Meaning |
| --- | --- |
| `configuration.role` | Operation mode, set by the General group (0 CS initiator, 1 CS reflector; same values as `OperationMode`) |
| `configuration.cs_enhancements_1` | IPT request, **CS modes → Inline PCT transfer (IPT)** (0 off, 1 requested). Needs Mode 2 or 3; sent only in the initiator config (`creation_cs_enhancements_1`) |
| `host_settings` | GAP role, CS_SYNC antenna, max TX power, PHY, TX power delta, peer antenna, SNR control, creation context, `peer_data` (0 RAS real-time, 1 initiator-only with IPT), `t_pm` (preferred T_PM in µs: 10 leaves the controller's choice, 20 and 40 are sent) and `peripheral_patterns` (GAP central only) |

`model.py` uses only the standard library and protocol dataclasses. It is suitable
for headless use:

```python
from ble_channel_sounding.planner.model import Scenario, build_schedule

result = build_schedule(Scenario(target_steps=20))
assert result.complete
print(result.duration)  # 32636 microseconds, including scheduled gaps
```

With `peer_data` set to `1`, schedule notes identify initiator-only IPT
analysis: reflector amplitude is unavailable and RTT is unavailable. They add
that the procedure interval can be 1 ACL event without RAS and, for Mode 3, that
RTT has no reflector timing and nothing checks the IPT phase independently.
With RAS real-time (`0`) and a minimum procedure interval of 1, a note warns
that the RAS data needs ACL events between procedures.

## RAS real-time transfer

With `peer_data` 0 the reflector's RAS responder sends one procedure's ranging
data on the ACL events that follow it, and `Schedule.ras` sizes it
(`RasTransfer`, `None` without RAS real-time or without a schedule):

| Step | Value |
| --- | --- |
| Ranging data | 4-byte ranging header, 8 bytes per subevent, and per step a 1-byte step header plus the reflector's step data (mode 0: 3; RTT: 6, or 14 with a sounding sequence; tones: 1 + 4 per antenna path and extension slot) |
| Notifications | `ceil(bytes / (mtu - 4))`: the responder segments at the ATT MTU less the notification and RAS segment headers |
| LL PDUs | each notification's L2CAP frame fragmented at `CONFIG_BT_CTLR_DATA_LENGTH_MAX` (251) |
| Air time | per PDU, an empty PDU, the fragment and two T_IFS gaps, on the assumed ACL PHY |
| ACL events | the air time filled into successive events, at most one connection interval each |

The MTU is `connection.mtu`, a connection parameter beside interval, latency and
timeout: `ATT MTU` in the Connection tab's example panel, 23 (the ATT default a
link keeps until an exchange raises it, which is what a hosted link between the
images here has) until a client reports the negotiated value with
`CONNECTION_PARAMETERS`, and editable to try another. `build_schedule(s,
peer_data, phy=...)` reads it from the scenario; `phy` is the host reference PHY,
read as the assumed ACL PHY. `cs_hostless_initiator` is the worked case: 736
bytes per procedure, 2 notifications and 3 LL PDUs at MTU 498, 39 notifications
without an exchange.

The lanes and the note state occupancy and a floor — bytes, notifications, LL
PDUs, air time and *at least* N ACL events — never a drain rate: how many PDUs
leave per ACL event depends on the reflector's event length, its TX buffers and
its host, which the link does not report. A second note warns when the air time
exceeds the window between the first ACL anchor after the procedure and the next
procedure, so the data arrives late and can abort it.

The example `configuration.t_pm_time_us` stays the value the schedule is drawn
with, so a negotiated CS configuration report can always replace it. Selecting a
`t_pm` of 20 or 40 µs in the view copies it there once, so the prediction follows
the request without pinning the example value.

## Timing model and scope

The model implements the step structures below. IPT keeps the formulas but
substitutes `SW = T_SW_IPT` (**CS modes → T_SW_IPT**, enabled only while IPT is
requested; `t_sw_ipt_us` in planner JSON), and `IP2` must come from the
reflector's IPT `T_IP2` list. The step, event, procedure and connection views
therefore follow `T_SW_IPT`: the step view labels the gaps `T_SW_IPT` and
`T_IP2 (IPT)`, colors the pre-rotated reflector tones separately, and reports
the reflector's real-time margin `RD + IP2`.

Controls that the selected modes do not use are read-only (greyed) and held at
their `Scenario()` defaults (`inactive_fields()`, `unused_host_fields()` and
`apply_mode_defaults()` in `model.py`). Opened plans and applied packets are
normalized the same way, and the C export and host packets send the defaults:

| Condition | Read-only fields and held values |
| --- | --- |
| No sub-mode (1, 2, 3) | Minimum/Maximum main run 2/10 and Illustrative main run 2, as in the Zephyr `connected_cs_initiator` sample. The specification reserves these fields without a sub-mode; controllers may report them as 0. |
| No RTT (2) | RTT sequence AA only; host SNR control initiator/reflector Not used (SNR control applies to Mode-1/3 CS_SYNC packets). |
| No PBR (1) | T_IP2, T_PM, T_SW, T_SW_IPT and IPT (off) at the planner assumptions; antenna configuration A1:B1; host preferred peer antenna 1. |
| IPT off / requested | T_SW_IPT / T_SW at the planner assumption. |
| CSA #3b | #3c shape Hat and jump 2, the firmware defaults. |
| One subevent per event | Subevent spacing 0, as validation requires. |
| Reflector configuration | Host creation context Local and remote (only the initiator configuration carries it). |

```text
d0 = 2*SY0 + 2*RD + IP1 + GD + FM
d1 = 2*SY  + 2*RD + IP1
d2 = 2*(SW+PM)*(NAP+1) + 2*RD + IP2
d3 = 2*SY + 2*GD + 2*(SW+PM)*(NAP+1) + 2*RD + IP2
```

Before the controller reports negotiated timing, `Scenario()` predicts with the mandatory
values T_IP1 = 145 µs, T_IP2 = 145 µs, T_FCS = 150 µs and T_PM = 40 µs; the controller
may select another value from the supported lists. The possible values are T_IP1/T_IP2 =
10, 20, 30, 40, 50, 60, 80 or 145 µs; T_FCS = 15, 20, 30, 40, 50, 60, 80, 100,
120 or 150 µs; and T_PM = 10, 20 or 40 µs. At runtime, these values are selected during
the Channel Sounding Configuration procedure after the Channel Sounding Capabilities
Exchange, based on the local controller's capability bitmask, the peer controller's
capability bitmask/constraint, mandatory or conditional support, and, for IPT, the
reflector's T_IP2_IPT capability. T_SW and T_SW_IPT remain 2 µs as planner assumptions
because their values are device-specific. `RD=5 µs`, `GD=10 µs`,
`FM=80 µs`.
Mode-0 packets never inherit the selected
RTT sequence. Tone extension slots reserve time in both directions even when
no physical transmission is present. Mode-3 uses **IP2 and two guard periods**.

Within each subevent, steps are packed in order with `FCS` **between** steps.
Each new subevent adds Mode-0 and any available repeated main steps. The fresh
mode cadence continues across subevent boundaries. Repetitions consume time and
step count but do not advance the requested fresh workload.

For zero-based subevent index `i`, with `P` subevents/event:

```text
event, slot = divmod(i, P)
start_us = event * event_interval * connection_interval_us
         + slot * subevent_interval * 625
elapsed_us = last_subevent.start_us + last_subevent.duration_us
```

The schedule checks timeout, spacing, parameter encodings, procedure duration,
160 steps/subevent, 256 total steps/procedure and 32 subevents/procedure. It also
closes the procedure once `channel_map_repetition` non-mode-0 channel arrays are used
up (§4.2); with #3b, each array provides one step per enabled channel. Reaching
a limit may close the predicted procedure before the requested workload is done.

This is a timing/workload explorer, not a full controller simulator:

- The user chooses a **fresh non-Mode-0 step workload**, not a guaranteed number
  of distinct measured channels (mode-1 sub-mode steps reuse channels). Channel
  assignments are a seeded example of CSA #3a/#3b/#3c, not the DRBG-determined
  sequence; the running channel map update (CSFilteredChM) is taken as the configured map.
- Mixed-mode cadence is an explicit fixed example inside the configured range;
  the CS DRBG, actual antenna permutation and randomized extension transmissions
  are not reproduced. A displayed fit applies to this illustrative sequence.
- Timing choices are not checked against two devices' capabilities. PHY airtime
  is modeled; packet loss, controller interruptions, propagation delay and clock
  drift/window widening are not.
- Connection controls model ordinary 1.25 ms-unit ACL intervals, without subrating
  or the newer shorter-connection-interval feature. Latency illustrates allowed
  skipping; it does not alter anchor spacing or predict attendance during CS.
- ACL activity is an explicit illustration, not airtime calculated from connection
  interval. Possible overlap is reported; no radio coexistence scheduler runs.
- Inline phase transfer is explicitly rejected rather than silently using baseline
  step durations. Setup, command transport and result-reporting latency are outside
  the elapsed procedure time shown.

References:

- [Core 6.1 Vol 6 Part H §§4.2–4.4: sequencing and step structures](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-61/out/en/low-energy-controller/channel-sounding.html).
- [Core 6.1 Vol 6 Part B §§4.1.4, 4.5.18.1: spacing, limits and ACL anchoring](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Core-61/out/en/low-energy-controller/link-layer-specification.html).
- [Zephyr procedure completion fields](https://docs.zephyrproject.org/latest/doxygen/html/structbt__conn__le__cs__procedure__enable__complete.html).

## Checks

From the `python` directory:

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

GUI checks skip when Qt/PyQtGraph are absent; timing tests require neither. Tests
cover reference durations, exact-fit boundaries, repetitions, cross-subevent
cadence, early closure, limits, serialization and live GUI navigation/rendering.
