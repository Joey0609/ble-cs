# Integrated CS host

For the user-focused install and first-run walkthrough, see [Getting Started](GETTING_STARTED.md). The **Help** action at the right end of the session toolbar (or **Help → Help topics…**) opens the in-app help: an overview of the application's purpose and capabilities, followed by task-based topics (`views/help_dialog.py`). This document is the detailed reference.

Install from the repository root; run `cs-app` for the integrated host or `cs-planner` for the standalone planner:

```sh
.venv/bin/python -m pip install -e ./python
cs-app
# Preselect the simulator port:
cs-app --simulate
# Simulator that replays measurement packets from an existing capture:
cs-app --simulate run.h5
```

The port list always ends with **Simulator — in-memory client**, so no flag is
needed to try the app without hardware; `--simulate` only preselects it and
supplies the capture to replay.

The top general toolbar contains the operation mode and **Client log** selectors,
with independent **Console** and **Host** levels (Off, Error, Warning, Info and
Debug). CS-only identity, GAP role, device name and scan prefixes stay in the CS
setup view. The levels apply in every operation mode, are saved as
`host_settings.log`, and are included in radio test presets. Firmware defaults
(Info on the console and Warning over the host protocol) are represented by
omitting `SET_LOG_CONFIG`; other selections are part of the configuration CRC.

The top general toolbar contains the operation mode selector (**CS** and **CS
Hostless**) and the Console/Host log-level selectors. **Radio Test** remains
visible but disabled while its firmware paths are work in progress. The
Configuration tab shows the selected mode's view. CS setup is the first CS tab
and contains the Bluetooth name, GAP role, CS role and scan prefixes.

The top panel holds the **Serial port** and **Recording** settings side by side. The Serial port
group has **Client** and **Peer** tabs: Client contains the main protocol link, while Peer has
its own read-only serial port and baud rate;
the values are saved under `host_settings.peer_console`, never enter the client
configuration or CRC, and the console is opened for a run (or hostless
connection) only when a port is configured. It is closed with that session.
Each console line takes its level from the Zephyr/`app_log` tag after the
optional timestamp (`[12.345] <err> module: …`, `[00:00:01.234,567] <wrn> …`);
the device timestamp stays in the text, and hexdump continuation lines join
the line before. A port that fails to open or is lost is a host warning. The
Recording group has an optional run description and a movable, floatable session-actions
toolbar. Its groups are Connect client; Apply config and Synchronise; Scan and Connect peer;
Start session and Stop session; and the record-management group Record from now, Describe session, Open capture… and
Clear. Describe session (pencil) opens the
multi-line notes of the open session or capture, next to Record from now so a
running recording can be described while it runs; it is enabled whenever there
is a session, a loaded capture or an existing description, with no link needed.
Open capture… (folder) and Clear (eraser) act on the results view the Results tab
shows — CS analysis or radio RX — need no link either, and are disabled only
while a run owns the views.
Connect client opens the host session and becomes Disconnect client to end it. While the CONNECT
handshake is unanswered it reads Cancel connection (crossed circle) and a second press
abandons the attempt instead of waiting out the 10-second deadline; the port is closed
and the session returns to DISCONNECTED without being marked as a failed port.
Disconnect client closes the peer link and host session but keeps the serial port open.
The Connect peer icon changes to the disconnect-link icon when a peer is connected.
Disconnect peer drops the Bluetooth link and automatically starts a fresh host session over the
port, so Scan and Connect peer are ready for another device. The port selector stays disabled
while the port is ours. The status
bar shows the session state, sync state, link state and frame counters. In simulator mode select **Connect**
and **Apply host configuration to client**.
Choose an operation mode, edit the configuration, Apply config, and Start. CS measurements, FAE and
logs appear in the configuration/results/session tabs. The Controller sub-tab under Results shows
the local and remote capabilities, the ACL parameters of the current link, the
completed configuration and procedure enable complete reports next to the
requested configuration, and lists settings a controller does not support.
For a GAP central, **Scan** and **Connect peer** are in the top toolbar next to the session controls.
Connect peer starts a scan when one is not active and changes to **Disconnect peer** when linked.
Start session is enabled only when the configuration is synced, a matching peer has been scanned,
and the peer is connected; its tooltip explains the missing step. Scan and connection attempts
show an alert with the next action to take.
Connection parameters, including the negotiated ATT MTU, are reported by the client whenever a
link's parameters are set; only a GAP central asks for the ACL values, so for a peripheral the request
column reads "not requested". The MTU is informational because the host does not request it, but it is shown as a connection
parameter in the Configuration view too — *Connection → ATT MTU*, in the example panel, holding
the 23-byte ATT default until a link reports its own — and it sizes the reflector's RAS real-time
transfer drawn on the Connection and Procedures timelines. The reported interval also gives the event and
procedure intervals their duration in milliseconds, and the Connection
illustration in the Configuration view then shows the link that exists rather
than the planned one, until one of its three values is edited. Opening a record
refills the tab from the record itself: the reports of the link it ends on, and
the configuration, reflector data and T_PM its host asked for; a hostless record
carries no request, so its reports stand alone. The simulator uses the
same packet API as the serial connection, supports reset, late/no connect replies,
a cached configuration, and the stop/disconnect requirements. Its numerical
measurements are synthetic, not an RF accuracy model.

The **Session** tab is the timeline of whatever session is open: the live run,
the last run after Stop, or an opened capture (its header says which). It holds
every record in order: commands sent, frames received, and local logs (host
messages and peer-console lines). Rows show time, direction, type, procedure and
a one-line summary; warnings and errors are coloured, counted in the header and
never hidden by the type filters. The panel at the bottom shows the selected
record parsed (all packet fields; for a subevent also its procedure's Steps and
Subevents). Results keeps the analysis views: Controller, Mode 0 / FFO, PBR per
channel, RTT and Estimates. The Controller view places the remote FAE table
below Capabilities. Mode 0 / FFO plots the initiator's Mode-0 measured offsets
and reported frequency compensation by subevent report over the last 30 seconds
(or around the selected procedure in a replay). The session's configuration
decides which analysis tabs are shown (its CS modes), and Results has its own
procedure selector. While a
run is live that selector shows the procedure being followed; in a replay it
lists every procedure the session history holds, ten rows at a time with a
scrollbar, and picking one that the bounded store no longer keeps decodes it
and its neighbours again.

The wrapped and unwrapped PBR per-channel plots show separate correction lines
for the Mode-0 measured offset and the reported frequency compensation. The
Estimates plot compares raw, Mode-0 corrected and frequency-compensation
corrected slope distances across procedures. Checkboxes above the plot control
which estimate lines are visible. All PBR comparisons use the same selected
path, tone quality filter and correction sign.

For hardware, the client must implement the handshake and commands in
`common/libs/cs_protocol/README.md`. The existing firmware test images are not protocol clients.
A typical arrangement is a hosted initiator board and a hostless reflector
flashed with a configuration exported from the CS view. This Python change does not
provide or modify the firmware client, hostless applications, or their C interface
header (`cs_generated_config/cs_generated_config.h`).

## Configuration and run control

- **Synchronise** offers Get from client or Apply from host. Get verifies the
  returned CRC before loading the view. Start stays disabled if the view cannot
  represent the client settings exactly.
- The CS setup tab exposes the Bluetooth name, GAP role, CS role, scan prefixes,
  CS_SYNC antenna, TX power, procedure PHY, TX delta, peer antenna mask, SNR
  controls and creation context. Prefixes are validated as 1–8 UTF-8 strings of
  1–32 bytes for GAP central. Radio Test does not show or use them.
- Loaded procedure/subevent ranges survive an unedited round trip. Editing a
  selected value replaces that range with a single-value request. Negotiated
  reports update the timing illustration without changing the requested packet.
- The CS modes tab carries the two client settings that have no field in the
  configuration packet: **Reflector data** and **Preferred T_PM**, both for a CS
  initiator only. The UI defaults to the Bluetooth Core Specification's mandatory
  40 µs T_PM; 20 µs is conditional and 10 µs is optional. A preferred T_PM of 20
  or 40 µs is sent as `SET_T_PM` and is part of the configuration CRC, while 10 µs
  leaves the controller's own preference and sends nothing. The Controller tab
  compares the request with the T_PM reported at CS configuration complete and
  lists a value the peer does not support under Compatibility.
- Apply validates locally, requests confirmation when a Bluetooth
  link must be interrupted, then sends Link Disconnect before staging
  and applying CS settings. This also clears a peer link retained across a
  host-session close; the host session stays open. Radio-to-radio applies do
  not send Link Disconnect. Apply stops at the first rejection.
- One command is outstanding at a time. Connect has a 10-second deadline; Start,
  Stop, Apply, Get and Link Disconnect use 5 seconds; other commands use 2 seconds.
  A timeout closes the transport to prevent a late response from being mistaken
  for a later command. Reconnect to inspect the client's actual state. Cancelling a
  pending Connect closes the transport for the same reason: the handshake has no
  transaction ID and cannot be resumed.
- Stop session ends the active run and its recording but keeps the Bluetooth link and
  the host session. When the UI configuration still matches the device, Start session
  remains available to run again and the toolbar continues to show the peer as connected.
  If the configurations differ, getting the device configuration asks before replacing
  the UI values; declining offers to upload the UI configuration instead. Disconnect peer
  drops that link and ends the host session with it: a session whose peer is gone has nothing
  left to measure. Neither teardown sends a STOP first — for a running measurement the
  firmware treats STOP, LINK_DISCONNECT and CLOSE_SESSION alike and interrupts the client itself, reporting the interruption as
  STOPPED / INTERRUPTED. `cs_client` accepts LINK_DISCONNECT while running since the BUSY
  guard was dropped (2026-09-24); an older client still refuses the frame, and the
  rejection cancels the CLOSE_SESSION behind it. Reattaching to a running client offers Stop session and
  **Record from now**; Get its configuration first if the host does not match.
- Radio-test packet and preset parsing remain available for compatibility with
  existing captures. Radio Test cannot be selected or applied in this deployment
  build; its firmware builds are documented as work in progress.

Each successful FAE report replaces the Controller view's table using its
supplied scale; failed reads retain the previous table and display the error.
Link loss clears the table with the other controller reports. Text/raw FAE
tables built without a packet fall back to 1/32 ppm per LSB.

## C export

The CS view's **Export C configuration…** action exports initiator, reflector,
or separate files for both roles into a chosen folder (asking before it replaces files). JSON files save the operation mode
(`configuration.role`), the IPT request (`configuration.cs_enhancements_1`) and the
Host settings as well as the scenario. Exported files embed the JSON for reopening
with **Open…**, with the operation mode of that file.

Both-role export makes the initiator GAP central and the reflector GAP peripheral;
name prefixes must be configured for the central. Exported bodies initialize the
`cs_utils` records through setters and contain CRCs computed from the same
`ClientConfig` as Apply. The firmware integration must supply the planned
`cs_generated_config.h` interface and select the corresponding GAP role. No
firmware file is changed by editing a plan; export only writes on explicit action.

## Recording and MATLAB

Enable **Logging**, enter an optional description, choose an output folder with **Browse…** (a folder
picker), then Start. Each run receives a new file named after its operation mode
and start time, `<mode>_<DD>_<Mon>_<YYYY>_<HH>_<MM>_<SS>.h5` (for example
`cs_initiator_14_Sep_2026_13_05_22.h5`; `__2` is appended if a second run
starts within the same second). A rejected Start discards its file. Stop,
finite radio completion, transport loss and session close finish the recording
with a stored reason. Record from now marks the file `partial`.

The HDF5 writer owns its file on a background thread, uses a bounded queue and
chunked resizable tables, and flushes every second. Queue or disk failures are
reported instead of silently dropping recorded data. Existing files are never
replaced.

### Session History

The app keeps a temporary, always-on history for the current run, independent
of the **Record each run** switch. It is seeded with link context and uses
bounded segments; above the **Session history** limit in the Recording group
(default 2 GB, applied from the next session) the oldest segment is dropped and
the Session tab says where the kept history starts. A refused Start does not
replace the previous history. Hostless mode starts history only after the port
opens successfully. Host messages from before the first session are shown from
memory.

The Session tab's timeline is a lazy tree view. While running it follows the
newest 200 records (**Pause** stops following); after Stop it browses the
complete kept history. Type, procedure and cancellable text filters are enabled
when browsing a stopped session or playing an opened recording and apply to the
full index; a true live stream remains an unfiltered tail, because searching and
filtering read the whole session. Clicking a row always works, live tail
included: it reads the record the view already holds and shows it in **Selected
entry** and **Record**. Selecting a subevent also fills **Procedure**,
**Subevents** and **Steps** with both roles' reports of that procedure, live tail
included: they come from the decoded result cache, which is keyed by the same
procedure key, so no record of the session is read for them. A procedure that
cache has already dropped leaves the three tabs empty during a live run; while
browsing it is rebuilt from the indexed records instead. The procedure selection
and the analysis-view updates stay out of the live path: replay selection updates
the analysis views with that procedure and its immediate neighbours. The Controller view remains link-wide.
HDF5 captures use the same model. A clicked row keeps its highlight while the
tail still holds it, and the tail goes on following the newest records; when the
tail evicts the row the copied detail stays.

A stopped run offers **Save session…**, because the session is browsed from a
file rather than from the temporary history: once the save has finished the app
opens it, so the timeline, its filters and the procedure selector all read the
saved capture. A session already covered by a recording or a save is not
offered again.

Use **Save session…** (Session tab or Recording group, enabled while the live
session has history) to replay temporary history into the normal HDF5 format.
It proposes `session_<mode>_<start time>.h5` in the recording folder and writes
the planner JSON beside it, as recordings do. When *Recording* covered the
session, it says so and offers to open that recording instead. The export runs
in the background and includes both directions, decoded tables,
`source="session"`, `history_truncated`, and the first kept history time when
applicable; a failed or cancelled save removes its files. Hostless session
files omit `/config`; negotiated reports remain under `/reports`. Temporary
history is discarded on application exit unless it is saved.

- Root attributes contain the version, timestamp, client/connection information,
  operation mode, configuration CRC, run number, partial flag, `source`,
  `history_truncated`, optional `history_first_timestamp`, `description`, and
  close reason.
- `/config` stores the applied settings, exact payloads used by the CRC, prefixes,
  the reflector data in `/config/peer_data`, the requested T_PM in `/config/t_pm`
  (10 µs when none was asked for), the two applied log levels in `/config/log`,
  and the planner JSON. `/context` copies the latest link reports at run start.
- `/host_log` contains host and peer messages with arrival time, level, source
  and UTF-8 text; older files without it remain readable.
- `/raw/frames` contains direction, arrival index, relative host time, type, and
  complete frame bytes. Decoded tables are under `/reports`, `/fae`, `/events`,
  `/results` and `/log`; tables are created when their first row arrives.
- Subevents reference contiguous rows in `/results/steps`; steps reference rows
  in `/results/tones`. Numeric record fields use int64 unless a narrower dtype
  is explicitly required (raw IDs, timestamps and signed FAE bytes). Fixed arrays
  stay rectangular for NumPy and MATLAB.

The session toolbar's **Open capture…** loads a recording (or a JSON-lines/raw-frame
capture) into Results and the Session tab, and `cs-app --simulate run.h5` replays one
through the simulator.

The Recording group converts recordings to MATLAB files next to the source:
**Convert last to MAT** converts the last recording once its run has closed the
file, and **Convert recording to MAT…** converts any chosen `.h5` file. An existing
`.mat` file is only replaced after confirmation.

MAT v5 uses compressed structs of column vectors, with fixed arrays as N×k
matrices and attributes in `meta`. Raw frames are omitted. Variables above
2 GB are rejected with guidance to use MATLAB `h5read`. The top-level
`description` variable is a MATLAB char row, preserving newlines; `host_log` is
a 1×N struct array with `timestamp`, `level` (1 error … 4 debug), `source` and
`text` fields (`source` and `text` as char rows), and 1×0 when the recording has
no host messages.

When a recorded run ends, a non-modal **Run description** dialog allows
multi-line notes without blocking Results; it opens on the notes typed during
the run with **Describe session**, and **Save session…** has the same field.
Closing the app saves an open description editor, and an unsaved unrecorded
history prompts **Save session / Discard / Cancel**.

## Validation

```sh
cd python
QT_QPA_PLATFORM=offscreen ../.venv/bin/python -m unittest discover -s tests
```

Tests cover the core session with an injectable clock, simulator-backed GUI flow,
range preservation, FAE scales and failed reads, validation, export/reimport,
recorder boundaries and indices, replay, peer-console parsing, simulator command
parity, performance at the mode-3 four-path rate, and MATLAB readback. Generated helper
bodies are syntax-checked through compiler stdin against the existing `cs_utils`
header. Full hostless-image compilation and serial/RF bring-up require the
separate firmware work.

## Hostless CS mode

Select **Hostless CS** when connecting to a hostless initiator or reflector.
The application opens the serial port in receive-only mode and decodes report
frames without sending the normal CONNECT handshake or any commands. The
planner displays reported configurations and negotiated controller values
read-only; discovery, configuration, run controls, GAP settings, radio views
and other command-oriented controls are dormant. Client `LOG_MESSAGE` frames
still feed the Session tab (with the level from their `<err>`/`<wrn>` prefix)
and, when Recording is enabled, the HDF5 `/log` table.
