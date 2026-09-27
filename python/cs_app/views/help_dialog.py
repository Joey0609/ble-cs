"""User help for the CS Host desktop application: a topic list beside the selected page."""

from PyQt6 import QtCore, QtGui, QtWidgets as W


HARDWARE_GUIDE = "https://github.com/Sens-Wear/ble-cs/blob/main/docs/GETTING_STARTED.md"
HOST_REFERENCE = "https://github.com/Sens-Wear/ble-cs/blob/main/python/cs_app/README.md"
PLANNER_REFERENCE = "https://github.com/Sens-Wear/ble-cs/blob/main/python/cs_planner/README.md"

# (key, title, body). Links to "help:<key>" open another topic in the dialog.
HELP_PAGES = (
    (
        "about",
        "About CS Host",
        f"""
        <p class="lead">CS Host (<code>cs-app</code>) is the desktop application for measuring distance between
        two Bluetooth devices with <b>Bluetooth Channel Sounding (CS)</b>. It controls a CS client board over
        USB, plans and applies the CS configuration, runs measurements, shows the results as they arrive, and
        keeps every session for later analysis.</p>

        <h2>What Channel Sounding measures</h2>
        <p>Channel Sounding is part of the Bluetooth Core Specification. Two connected devices take part in
        each measurement: the <b>initiator</b> starts CS procedures, and the <b>reflector</b> answers them. In a
        procedure they hop over many RF channels and exchange packets and tones. Two kinds of measurement
        estimate the distance between them:</p>
        <ul>
          <li><b>Phase-based ranging (PBR)</b>, Mode 2: the phase of tones across channels changes with
          distance, so the slope of phase against frequency gives the range.</li>
          <li><b>Round-trip timing (RTT)</b>, Mode 1: the time a packet takes to go to the reflector and back.</li>
          <li>Mode 3 combines both. Mode 0 steps at the start of every subevent calibrate frequency and timing.</li>
        </ul>

        <h2>What you can do with CS Host</h2>
        <table>
          <tr><th>Task</th><th>How CS Host helps</th></tr>
          <tr><td>Plan a measurement</td><td>Edit modes, channels, timing, antennas and connection settings, and
          see an illustration of the resulting connection, procedures, subevents, steps and channel
          sequence before anything is sent. See <a href="help:configuration">Configuring a measurement</a>.</td></tr>
          <tr><td>Control a client board</td><td>Connect to the <code>cs_client</code> firmware, apply the
          configuration, find and connect a reflector, and start and stop sessions. See
          <a href="help:hardware">Measuring with hardware</a>.</td></tr>
          <tr><td>Watch results live</td><td>Controller capabilities and negotiated settings, Mode-0 frequency
          offsets, PBR phase per channel, RTT and distance estimates. See
          <a href="help:results">Reading results</a>.</td></tr>
          <tr><td>Inspect every record</td><td>The Session tab lists every command, report and log line in
          order, with each record decoded. See <a href="help:session">Session timeline</a>.</td></tr>
          <tr><td>Keep and share data</td><td>Record runs to HDF5, save any session afterwards, add notes, and
          convert recordings to MATLAB. See <a href="help:recording">Recording and export</a>.</td></tr>
          <tr><td>Review earlier work</td><td>Open a recording to browse it in Results and Session, or replay it
          through the simulator.</td></tr>
          <tr><td>Receive a hostless stream</td><td>Decode the reports of hostless initiator firmware, which
          runs without host commands. See <a href="help:hostless">Hostless mode</a>.</td></tr>
          <tr><td>Configure firmware</td><td>Export the planned configuration as C source for the hostless
          firmware applications.</td></tr>
          <tr><td>Learn without hardware</td><td>The built-in simulator behaves like a client board. See
          <a href="help:quickstart">First steps with the simulator</a>.</td></tr>
        </table>

        <h2>How the pieces fit together</h2>
        <p>In the usual <b>hosted</b> setup, CS Host talks to one board and that board measures against a second
        one:</p>
        <pre>CS Host  ──USB (CDC ACM)──  nRF54LM20 DK running cs_client
                              CS initiator · Bluetooth central
                                        │
                                  Bluetooth CS
                                        │
                              Reflector: cs_hostless_reflector (DK)
                                         or cs_reflector_tag (Tag)</pre>
        <p>The client board runs as the CS <b>initiator</b> and Bluetooth <b>central</b>: it scans for the
        reflector, connects to it and runs the procedures. The reflector runs its own firmware and needs no
        host. Optionally, a second serial port can show the reflector's log lines next to the session (see
        <a href="help:logs">Logs and the peer console</a>).</p>

        <h2>Limits of this build</h2>
        <ul>
          <li>CS Host does not build or flash firmware. Use the <a href="{HARDWARE_GUIDE}">hardware Getting
          Started guide</a> for that.</li>
          <li>The client operates as CS initiator and GAP central only. <i>Reflector</i> and <i>Peripheral</i>
          are listed in CS setup so saved configurations keep their values, but cannot be selected.</li>
          <li>Radio Test mode is disabled while its firmware is work in progress.</li>
          <li>Simulator measurements are synthetic. They show how the app behaves, not radio accuracy.</li>
        </ul>

        <h2>Where to go next</h2>
        <ul>
          <li>New to the app: <a href="help:quickstart">First steps with the simulator</a>, then
          <a href="help:window">The main window</a>.</li>
          <li>Ready to measure: <a href="help:hardware">Measuring with hardware</a>.</li>
          <li>Something does not work: <a href="help:troubleshooting">Troubleshooting</a>.</li>
        </ul>
        <p>Hover over any control for its tooltip. The command <code>cs-planner</code> opens the configuration
        planner on its own, without a client connection.</p>
        """,
    ),
    (
        "quickstart",
        "First steps with the simulator",
        """
        <p>The simulator is an in-memory client that answers every command like a real board. It needs no
        hardware, so it is the quickest way to learn the workflow. Start the app with <code>cs-app --simulate</code>
        to select it automatically, or select it by hand as described below.</p>
        <ol>
          <li><b>Select the simulator.</b> In the <b>Serial port</b> group, on the <b>Client</b> tab, choose
          <b>Simulator — in-memory client</b> as the Port. If the Serial port group is hidden, click the summary
          bar at the top of the window to expand it.</li>
          <li><b>Connect.</b> Click <b>Connect client</b> on the session toolbar. The status bar shows the firmware
          version and the session state.</li>
          <li><b>Synchronise.</b> CS Host now compares its configuration with the client's. When they differ, the
          <b>Synchronise configuration</b> dialog opens: choose <b>Apply host configuration to client</b> to send
          the settings shown in the Configuration tab, or <b>Get configuration from client</b> to load the
          client's settings into the app.</li>
          <li><b>Find the reflector.</b> Click <b>Scan</b>. Matching peers appear in the list next to the session
          toolbar. Select one and click <b>Connect peer</b>.</li>
          <li><b>Start.</b> Click <b>Start session</b>. Results arrive in the <b>Results</b> tab; every record
          appears in the <b>Session</b> tab.</li>
          <li><b>Stop.</b> Click <b>Stop session</b>. The peer stays connected, so you can change nothing and start
          again, or change the configuration, click <b>Apply config</b> and start again.</li>
        </ol>
        <p>To try the recording features, enable <b>Record each run</b> in the Recording group before starting,
        or use <b>Save session…</b> after stopping. See <a href="help:recording">Recording and export</a>.</p>
        <p>To replay a recording through the simulator, start the app with
        <code>cs-app --simulate path/to/recording.h5</code>. The simulator then sends the recorded reports
        instead of synthetic ones. To look at a recording without replaying it, use <b>Open capture…</b>.</p>
        """,
    ),
    (
        "hardware",
        "Measuring with hardware",
        f"""
        <h2>What you need</h2>
        <ul>
          <li>An <b>nRF54LM20 DK</b> running the workspace's <code>cs_client</code> firmware. This is the client
          that CS Host controls.</li>
          <li>A <b>reflector</b>: an nRF54L15 or nRF54LM20 DK running <code>cs_hostless_reflector</code>
          (advertised name <code>CS Hostless Reflector</code> by default), or an nRF54L15 Tag running
          <code>cs_reflector_tag</code> (name starting with <code>CSTag</code>).</li>
          <li>A USB <b>data</b> cable to the client DK's native USB port.</li>
        </ul>
        <p>The firmware is built with nRF Connect SDK v3.4.1 and flashed with <code>west</code>; the
        <a href="{HARDWARE_GUIDE}">hardware Getting Started guide</a> has the commands.</p>

        <h2>Choose the right port</h2>
        <p>The client DK exposes two serial ports. The host protocol runs on the <b>USB CDC ACM</b> port of the
        native USB connector. The debug UART carries firmware log text only; selecting it as the Client port
        fails the connection. Use <b>Refresh</b> if the board was plugged in after the app started.</p>

        <h2>Run a session</h2>
        <ol>
          <li>Power the reflector so that it advertises.</li>
          <li>In <b>Serial port → Client</b>, select the client's USB CDC ACM port and click <b>Connect client</b>.
          If the client has a configuration that differs from the app's, choose which one to keep in the
          Synchronise dialog.</li>
          <li>Keep <b>Operation mode</b> at <b>CS</b>. In <b>Configuration → CS setup</b>, check the
          <b>Peripheral prefixes</b>: the scan lists only peers whose advertised name starts with one of these
          lines (case-sensitive). Add <code>CS Hostless Reflector</code> or <code>CSTag</code> as needed.</li>
          <li>Adjust the measurement in the other Configuration tabs, then click <b>Apply config</b>. CS Host
          validates the settings before it sends them.</li>
          <li>Click <b>Scan</b>, select the reflector in the peer list and click <b>Connect peer</b>. The status bar
          shows the link state.</li>
          <li>Click <b>Start session</b>, and <b>Stop session</b> when you have enough data.</li>
        </ol>
        <p><b>Start session</b> stays disabled until the client is connected, the configuration is in sync and
        the peer is connected. Its tooltip names the missing step.</p>

        <h2>Changing and ending</h2>
        <ul>
          <li><b>Stop session</b> ends the measurement but keeps the Bluetooth link and the client session, so you
          can start again straight away.</li>
          <li><b>Apply config</b> while a peer is connected disconnects the peer first; CS Host asks before it
          does. Connect the peer again after applying.</li>
          <li><b>Disconnect peer</b> drops the Bluetooth link and opens a fresh client session, ready to scan for
          another device.</li>
          <li><b>Disconnect client</b> ends the client session and the peer link, but keeps the serial port.</li>
        </ul>
        <p>If CS Host connects to a client that is already running a measurement, it loads the client's
        configuration and warns you. Use <b>Stop session</b> to end that run, or <b>Record from now</b> to keep
        its remaining data.</p>
        """,
    ),
    (
        "hostless",
        "Hostless mode",
        """
        <p>Hostless firmware (<code>cs_hostless_initiator</code>) runs Channel Sounding from a configuration
        compiled into the image. It needs no commands: it scans for its reflector, connects and measures by
        itself, and streams its reports over USB. CS Host can receive and decode that stream.</p>
        <ol>
          <li>Set <b>Operation mode</b> to <b>CS Hostless</b>.</li>
          <li>In <b>Serial port → Client</b>, choose the hostless initiator's USB CDC ACM port.</li>
          <li>Click <b>Connect client</b>. Reports appear in Results and Session as they arrive.</li>
        </ol>
        <p>In this mode CS Host only listens:</p>
        <ul>
          <li>Apply config, Synchronise, Scan, Connect peer, Start session and Stop session are disabled.</li>
          <li>The Configuration tab is read-only and shows the configuration the firmware reports.</li>
          <li>With <b>Record each run</b> enabled, recording starts with the first frame received and the file
          is marked partial, because the stream started before the app connected. <b>Save session…</b> also
          works.</li>
        </ul>
        <p>To change what a hostless initiator does, change its compiled configuration. The planner's
        <b>Export C configuration…</b> action writes the source file for that; the firmware README explains
        where to put it.</p>
        """,
    ),
    (
        "window",
        "The main window",
        """
        <p>The window is arranged from top to bottom:</p>
        <table>
          <tr><th>Area</th><th>Contents</th></tr>
          <tr><td>Summary bar</td><td>One line with the port, baud rate, operation mode, GAP role, recording
          state and connection state. Click it (or ▲/▼) to show or hide the settings panel below it.</td></tr>
          <tr><td>Settings panel</td><td><b>Serial port</b> (Client and Peer tabs) and <b>Recording</b> side by
          side.</td></tr>
          <tr><td>General controls</td><td><b>Operation mode</b> (CS or CS Hostless) and the client log levels
          <b>Console log</b> and <b>Host log</b> (see <a href="help:logs">Logs and the peer console</a>).</td></tr>
          <tr><td>Session toolbar</td><td>Connection, configuration, peer, run and record actions, and
          <b>Help</b>. The peer list and <b>Show all</b> follow it. See
          <a href="help:toolbar">Session toolbar</a>.</td></tr>
          <tr><td>Main tabs</td><td><b>Configuration</b> (the planner), <b>Results</b> (analysis) and
          <b>Session</b> (the record timeline).</td></tr>
          <tr><td>Status bar</td><td>Left: firmware version, client state, whether the client holds a
          configuration and how many antennas the board supports. Middle: short messages about the last action.
          Right: session state, sync state (<i>in sync</i> or <i>modified / mismatch</i>), link state and
          counters for frames, packet errors and lost RAS data.</td></tr>
        </table>
        <p>The session toolbar can be moved or floated. The <b>Help</b> menu holds these topics and the version
        information.</p>
        """,
    ),
    (
        "toolbar",
        "Session toolbar",
        """
        <p>Hover over an icon for its name. A disabled action's tooltip often says what it is waiting for.</p>
        <table>
          <tr><th>Action</th><th>What it does</th><th>Available</th></tr>
          <tr><td><b>Connect client</b></td><td>Opens the selected port and starts a client session. While the
          handshake is pending it reads <i>Cancel connection</i>; once connected it becomes <b>Disconnect
          client</b>, which ends the session and peer link but keeps the port open.</td><td>Always, except
          while a command is pending</td></tr>
          <tr><td><b>Apply config</b></td><td>Validates the Configuration tab and sends it to the client. A
          connected peer is disconnected first, after confirmation.</td><td>Client connected, no run</td></tr>
          <tr><td><b>Synchronise</b></td><td>Compares host and client configuration and lets you get the
          client's or apply the host's.</td><td>Client connected, no run</td></tr>
          <tr><td><b>Scan</b></td><td>Searches for advertising peers and fills the peer list. A new scan clears
          the list.</td><td>Configuration in sync, no peer link</td></tr>
          <tr><td><b>Connect peer</b></td><td>Connects the peer selected in the list, scanning first if nothing is
          listed. Becomes <b>Disconnect peer</b> while linked.</td><td>Configuration in sync</td></tr>
          <tr><td><b>Start session</b></td><td>Starts CS procedures and a new session.</td><td>In sync and peer
          connected</td></tr>
          <tr><td><b>Stop session</b></td><td>Ends the run and its recording; keeps the link. Also stops an
          active scan or connection attempt.</td><td>During a run, scan or connection attempt</td></tr>
          <tr><td><b>Record from now</b></td><td>Records the rest of a run that is not being recorded. The file
          is marked partial.</td><td>During an unrecorded run</td></tr>
          <tr><td><b>Describe session</b></td><td>Edits the notes kept with the session and written to its
          recording.</td><td>A session, capture or notes exist</td></tr>
          <tr><td><b>Open capture…</b></td><td>Loads a recording or capture file into Results and Session for
          review.</td><td>No run</td></tr>
          <tr><td><b>Clear</b></td><td>Removes the shown results, the open capture and the session timeline.
          </td><td>No run</td></tr>
          <tr><td><b>Help</b></td><td>Opens these topics.</td><td>Always</td></tr>
        </table>
        <p>Next to the toolbar, the peer list shows each scanned peer's name, address and signal strength
        (RSSI). By default it lists only names that start with a configured prefix. <b>Show all</b> lists
        every peer, including unnamed ones. If a loaded configuration uses GAP role Peripheral, an
        <b>Advertise</b> button replaces the peer list: the client then advertises and waits for a central to
        connect.</p>
        """,
    ),
    (
        "configuration",
        "Configuring a measurement",
        f"""
        <p>The <b>Configuration</b> tab is a planner: the left side holds the settings, the right side draws what
        those settings produce, and the pane below explains the selected setting. Nothing reaches the client
        until you click <b>Apply config</b>.</p>

        <h2>Settings tabs</h2>
        <table>
          <tr><th>Tab</th><th>Settings</th></tr>
          <tr><td><b>CS setup</b></td><td>Bluetooth name of the client, GAP role, CS role, Peripheral prefixes
          (the scan filter), CS_SYNC antenna, maximum TX power, reference PHY, TX power delta, preferred peer
          antennas, SNR control and creation context.</td></tr>
          <tr><td><b>Connection</b></td><td>The Bluetooth connection that CS runs on: requested connection
          interval range, peripheral latency and supervision timeout.</td></tr>
          <tr><td><b>CS modes</b></td><td>Main mode and sub-mode, Mode-0 steps, main-mode runs, CS_SYNC PHY, RTT
          sequence, antenna configuration, inline PCT transfer (IPT), reflector data and preferred
          T_PM.</td></tr>
          <tr><td><b>Schedule</b></td><td>How steps fill subevents and procedures: subevent length, maximum
          procedure length, procedure spacing and procedure count.</td></tr>
          <tr><td><b>Channels</b></td><td>The channel map (at least 15 channels; <b>All</b>, <b>Even</b>,
          <b>Odd</b>, <b>None</b> presets), map repetition and the channel selection algorithm.</td></tr>
        </table>
        <p>Settings that the selected modes do not use stay at their defaults and are read-only. Values in the
        groups titled <i>Example config values selected by the controller</i> are chosen by the controllers at
        run time; they only shape the illustration and are never sent.</p>

        <h2>Illustrations</h2>
        <p>The numbered tabs on the right draw the plan at five levels: <b>1 Connection</b>, <b>2 Procedures</b>,
        <b>3 Events &amp; subevents</b>, <b>4 Individual step</b> and <b>5 Channels</b>. The line above them shows
        where you are (procedure, event, subevent, step). The status line below the settings summarises the
        plan: whether it is complete or needs attention, fresh steps placed, subevents, CS events and elapsed
        time. When a peer is connected, the Connection illustration uses the negotiated connection interval.</p>

        <h2>Help pane</h2>
        <p><b>About this tab</b> explains the settings tab you are on. <b>Setting details</b> gives the full
        description of the setting you last selected: what it defines, how the controller selects it, what a
        change does and where the Bluetooth Core Specification defines it.</p>

        <h2>Planner actions</h2>
        <ul>
          <li><b>Open…</b> loads a planner JSON file or an exported C file. <b>Save…</b> writes the plan as
          JSON.</li>
          <li><b>Export C configuration…</b> writes <code>cs_generated_config.c</code> for the initiator, the
          reflector or both (one file per role) for the hostless firmware.</li>
          <li><b>Export view…</b> saves the current illustration as PNG. <b>Fit views</b> redraws the
          illustrations to fit. <b>Reset</b> restores the default plan.</li>
        </ul>
        <p>During a run the settings are locked; the views and exports stay available. The client or its peer
        can still reject a setting that its controller does not support: the Controller view under Results then
        lists it under Compatibility. See the <a href="{PLANNER_REFERENCE}">planner reference</a> for the
        planning model.</p>
        """,
    ),
    (
        "results",
        "Reading results",
        """
        <p>The <b>Results</b> tab analyses the current run, the last stopped run or an opened capture. The line
        at its top summarises the data, and the tabs shown depend on the CS modes of the session. Most tabs have
        <b>Plots</b> and <b>Table</b> sub-tabs showing the same data.</p>

        <h2>Tabs</h2>
        <table>
          <tr><th>Tab</th><th>Shows</th></tr>
          <tr><td><b>Controller</b></td><td>Local and remote capabilities, the remote FAE table, connection
          parameters, the configuration complete and procedure enable complete reports next to what was
          requested, and <b>Compatibility</b>: requested settings a controller does not support. Start here
          when a run fails or behaves unexpectedly.</td></tr>
          <tr><td><b>Mode 0 / FFO</b></td><td>The frequency offset measured in Mode-0 steps and the frequency
          compensation reported by the controller, over the last 30 seconds (or around the selected procedure in
          a capture).</td></tr>
          <tr><td><b>PBR per channel</b></td><td>Phase of each channel for one antenna path, wrapped and
          unwrapped, with the fitted lines. A straight unwrapped line means a clean measurement; its slope gives
          the distance.</td></tr>
          <tr><td><b>RTT</b></td><td>Round-trip-time distances of Mode-1 or Mode-3 steps, with accepted and
          rejected steps and their spread.</td></tr>
          <tr><td><b>Estimates</b></td><td>Distance per procedure over time. Use <b>Plot lines</b> to compare RTT
          mean and median, raw PBR, and PBR corrected by the Mode-0 offset or by the reported frequency
          compensation.</td></tr>
        </table>

        <h2>Analysis controls</h2>
        <ul>
          <li><b>Procedure</b>: the procedure shown. During a run it follows the newest; for a stopped run or a
          capture, pick any procedure in the list.</li>
          <li><b>Path</b>: the antenna path used for PBR. The number of paths comes from the antenna
          configuration.</li>
          <li><b>sign + / sign −</b>: the direction in which frequency corrections are applied. The right choice
          depends on the controller; compare both against a known distance.</li>
          <li><b>High-quality tones only</b>: ignore tones that either device marked as low quality.</li>
          <li><b>AA successful only</b> and <b>Max errors</b>: for RTT, accept a step only if both devices found
          the access address, and only up to the given bit error count.</li>
        </ul>
        <p>These controls change only the analysis. Recorded data are never modified.</p>
        """,
    ),
    (
        "session",
        "Session timeline",
        """
        <p>The <b>Session</b> tab lists everything that happened in the open session, in order: commands sent,
        reports received, client log messages, host messages and peer-console lines. Its header says whether you
        are looking at the live run, the last run after Stop, or an opened capture, and counts warnings and
        errors.</p>
        <h2>Browsing</h2>
        <ul>
          <li>During a run the list follows the newest 200 records. <b>Pause</b> stops following so you can read;
          records are still collected.</li>
          <li>After Stop, or for an opened capture, the whole session can be browsed. The type check boxes
          (<b>Subevents</b>, <b>Reports</b>, <b>Client log</b>, <b>Host</b>, <b>Peer</b>, <b>Other</b>), the
          <b>Procedure</b> range and the text filter narrow the list. Warnings and errors are always shown.</li>
        </ul>
        <h2>Record details</h2>
        <p>Click a row to decode it below the list. <b>Selected entry</b> and <b>Record</b> show the record and all
        its fields. For a subevent result, <b>Procedure</b>, <b>Subevents</b> and <b>Steps</b> show both devices'
        reports of that procedure.</p>
        <h2>Keeping the session</h2>
        <p>The session is held in a temporary history while the app is open, whether or not it is recorded.
        <b>Save session…</b> writes it as an HDF5 file; see <a href="help:recording">Recording and export</a>.
        If you close the app with an unsaved session, you can save it, discard it or cancel closing.</p>
        """,
    ),
    (
        "recording",
        "Recording and export",
        """
        <h2>Recording each run</h2>
        <p>In the <b>Recording</b> group, choose a <b>Folder</b> with <b>Browse…</b> and enable <b>Record each
        run</b>. Every run is then written to a new HDF5 file named after the mode and start time, for example
        <code>cs_initiator_14_Sep_2026_13_05_22.h5</code>. Existing files are never overwritten. Type an optional
        <b>Description</b> before starting; after the run a dialog lets you edit the notes, and <b>Describe
        session</b> edits them at any time.</p>
        <p>A recording holds the applied configuration, the reports of the link, every frame in both directions,
        the decoded results and the log messages. A copy of the planner JSON is written next to it.</p>

        <h2>Saving afterwards</h2>
        <p>If a run was not recorded, <b>Save session…</b> (in the Recording group or the Session tab) writes the
        temporary history in the same format. It is kept until the next session starts or the app closes. Its
        size is limited by <b>Session history</b> (2 GB by default, applied from the next session); beyond it the
        oldest part is dropped and the Session tab shows where the kept history starts.</p>

        <h2>Reviewing</h2>
        <p><b>Open capture…</b> on the session toolbar loads a recording (<code>.h5</code>) or another capture
        file into Results and Session. A recording made in CS mode also loads its saved configuration into the
        Configuration tab, so the illustrations match the data. <b>Clear</b> closes it.</p>

        <h2>MATLAB</h2>
        <p><b>Convert last</b> writes the last finished recording as a <code>.mat</code> file next to it;
        <b>Convert file…</b> converts any recording you choose. <b>MAT options…</b> selects the sections to
        include. An existing <code>.mat</code> file is replaced only after confirmation. Very large sections are
        better read in MATLAB with <code>h5read</code> directly from the HDF5 file.</p>
        """,
    ),
    (
        "logs",
        "Logs and the peer console",
        """
        <h2>Client log levels</h2>
        <p>The general controls set how much the client firmware logs:</p>
        <ul>
          <li><b>Console log</b>: messages sent to the client's own debug console (UART).</li>
          <li><b>Host log</b>: messages sent to CS Host. They appear in the Session tab as <i>Client log</i>
          and are recorded.</li>
        </ul>
        <p>Each level (Off, Error, Warning, Info, Debug) includes the more severe ones. The levels are part of
        the applied configuration, so click <b>Apply config</b> after changing them.</p>

        <h2>Peer console</h2>
        <p>The <b>Peer</b> tab of the Serial port group reads a second serial port, usually the reflector's debug
        UART, or the debug UART of the hostless initiator. Its lines appear in the Session tab under <b>Peer</b>,
        with the level taken from the line's <code>&lt;err&gt;</code>, <code>&lt;wrn&gt;</code> or
        <code>&lt;inf&gt;</code> tag, and are recorded with the session.</p>
        <ol>
          <li>Type the port name, for example <code>/dev/cu.usbmodem0010</code> or <code>COM7</code>.</li>
          <li>Choose the baud rate of that firmware's console.</li>
          <li>Click <b>Open peer console</b>. It is also opened automatically for a run when a port is set.</li>
        </ol>
        <p>The peer console is read-only and never part of the client configuration. The nRF54L15 Tag logs over
        RTT instead of a UART, so it needs an SWD probe and an RTT viewer.</p>
        """,
    ),
    (
        "troubleshooting",
        "Troubleshooting",
        f"""
        <table>
          <tr><th>Problem</th><th>What to check</th></tr>
          <tr><td>No client port is listed</td><td>Use a USB data cable on the DK's native USB connector and
          click <b>Refresh</b>. Close other programs that hold the port.</td></tr>
          <tr><td>Connect client fails or times out</td><td>Select the USB CDC ACM port, not the debug UART.
          Make sure the board runs <code>cs_client</code> (or, for CS Hostless, a hostless initiator) and that the
          operation mode matches.</td></tr>
          <tr><td>Scan finds no reflector</td><td>Check that the reflector is powered and advertising, and that
          its name starts with one of the Peripheral prefixes in CS setup (prefixes are case-sensitive). Enable
          <b>Show all</b> to see every peer found.</td></tr>
          <tr><td>Scan or Connect peer is disabled</td><td>Apply or synchronise the configuration first. Disconnect
          an existing peer before scanning again.</td></tr>
          <tr><td>Start session is disabled</td><td>Hover over it: it names the missing step (configuration not in
          sync, no peer scanned, or peer not connected).</td></tr>
          <tr><td>Apply config is rejected</td><td>The message names the rejected setting. Check the Controller
          view's Capabilities and Compatibility for what the boards support, for example the number of
          antennas.</td></tr>
          <tr><td>Results are empty or noisy</td><td>Check the Controller view for the negotiated configuration
          and the Session tab for warnings. For PBR, try another Path or sign; for RTT, relax <b>Max errors</b>.
          </td></tr>
          <tr><td>The client was already running</td><td>CS Host loaded its configuration. Stop the run, or use
          <b>Record from now</b> to keep it.</td></tr>
        </table>
        <p>For build, flash and wiring questions, see the <a href="{HARDWARE_GUIDE}">hardware Getting Started
        guide</a>. For detailed behaviour of every feature, see the <a href="{HOST_REFERENCE}">CS Host
        reference</a>.</p>
        """,
    ),
)

STYLE = """
    body {{ color: #21334b; }}
    h1 {{ font-size: 22px; margin-bottom: 8px; }}
    h2 {{ font-size: 16px; margin-top: 18px; margin-bottom: 4px; }}
    p, li {{ line-height: 135%; }}
    p.lead {{ font-size: 15px; }}
    code, pre {{ font-family: '{mono}', 'Menlo', 'Consolas', 'DejaVu Sans Mono', 'Courier New', monospace; }}
    pre {{ background-color: #eef3f9; }}
    table {{ border-collapse: collapse; margin-top: 6px; margin-bottom: 6px; }}
    th {{ background-color: #eef3f9; text-align: left; }}
    th, td {{ border: 1px solid #cbd8e6; padding: 5px; vertical-align: top; }}
    a {{ color: #146fba; }}
"""


class HelpDialog(W.QDialog):
    """Non-modal help window: topic list on the left, the selected page on the right."""

    def __init__(self, parent=None, topic="about"):
        super().__init__(parent)
        self.setWindowTitle("CS Host Help")
        self.resize(1120, 780)
        layout = W.QVBoxLayout(self)
        splitter = W.QSplitter(self)
        layout.addWidget(splitter, 1)

        self.topics = W.QListWidget()
        self.topics.setStyleSheet("QListWidget { font-size: 14px; } QListWidget::item { padding: 6px; }")
        self.browser = W.QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self.follow_link)
        self.browser.setStyleSheet("QTextBrowser { padding: 12px; font-size: 14px; "
                                   "background: #ffffff; color: #21334b; }")
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont).family()
        self.browser.document().setDefaultStyleSheet(STYLE.format(mono=mono))
        splitter.addWidget(self.topics)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 870])

        self.pages = {}
        for key, title, body in HELP_PAGES:
            item = W.QListWidgetItem(title)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, key)
            self.topics.addItem(item)
            self.pages[key] = f"<h1>{title}</h1>{body}"
        self.topics.currentRowChanged.connect(self.show_row)

        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
        self.show_topic(topic)

    def show_row(self, row):
        item = self.topics.item(row)
        if item is not None:
            self.browser.setHtml(self.pages[item.data(QtCore.Qt.ItemDataRole.UserRole)])

    def show_topic(self, key):
        """Select topic key; an unknown key selects the first topic."""
        keys = [page[0] for page in HELP_PAGES]
        self.topics.setCurrentRow(keys.index(key) if key in keys else 0)

    def follow_link(self, url):
        if url.scheme() == "help":
            self.show_topic(url.path())
        else:
            QtGui.QDesktopServices.openUrl(url)
