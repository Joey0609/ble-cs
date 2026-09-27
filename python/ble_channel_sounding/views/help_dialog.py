"""User help for the BLE Channel Sounding Host desktop application: a topic list beside the selected page."""

from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets as W


HARDWARE_GUIDE = "https://github.com/Sens-Wear/ble-cs/blob/main/docs/GETTING_STARTED.md"
HOST_REFERENCE = "https://github.com/Sens-Wear/ble-cs/blob/main/python/ble_channel_sounding/README.md"
PLANNER_REFERENCE = "https://github.com/Sens-Wear/ble-cs/blob/main/python/ble_channel_sounding_planner/README.md"
SCREENSHOTS = {
    "main-window": ("The main window", "main-window.png"),
    "configuration": ("Configuration overview", "configuration.png"),
    "results": ("Results overview", "results.png"),
    "config-cs-setup": ("Configuration — CS setup", "config-cs-setup.png"),
    "config-connection": ("Configuration — Connection", "config-connection.png"),
    "config-cs-modes": ("Configuration — CS modes", "config-cs-modes.png"),
    "config-schedule": ("Configuration — Schedule", "config-schedule.png"),
    "config-channels": ("Configuration — Channels", "config-channels.png"),
    "planner-connection": ("Planner illustration — Connection", "planner-connection.png"),
    "planner-procedures": ("Planner illustration — Procedures", "planner-procedures.png"),
    "planner-events": ("Planner illustration — Events and subevents", "planner-events-subevents.png"),
    "planner-step": ("Planner illustration — Individual step", "planner-individual-step.png"),
    "planner-channels": ("Planner illustration — Channels", "planner-channels.png"),
    "results-controller": ("Results — Controller", "results-controller.png"),
    "results-mode0": ("Results — Mode 0 / FFO", "results-mode-0-ffo.png"),
    "results-pbr": ("Results — PBR per channel", "results-pbr-per-channel.png"),
    "results-rtt": ("Results — RTT", "results-rtt.png"),
    "results-estimates": ("Results — Estimates", "results-estimates.png"),
}

# (key, title, body). Links to "help:<key>" open another topic in the dialog.
HELP_PAGES = (
    (
        "about",
        "About BLE Channel Sounding Host",
        f"""
        <p class="lead">BLE Channel Sounding Host (<code>ble-channel-sounding</code>) is the desktop application for measuring distance between
        two Bluetooth devices with <b>Bluetooth Channel Sounding (CS)</b>. It controls a CS client board over
        USB, plans and applies the CS configuration, runs measurements, and shows results as they arrive. Enable
        recording for each run or save the session history to keep data for later analysis.</p>

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

        <h2>What you can do with BLE Channel Sounding Host</h2>
        <table>
          <tr><th>Task</th><th>How BLE Channel Sounding Host helps</th></tr>
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
        <p>In the usual <b>hosted</b> setup, BLE Channel Sounding Host talks to one board and that board measures against a second
        one:</p>
        <pre>                              BLE Channel Sounding Host
                                        │
                                  USB (CDC ACM)
                                        │
                              nRF54LM20 DK running cs_client
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
          <li>BLE Channel Sounding Host does not build or flash firmware. Use the <a href="{HARDWARE_GUIDE}">hardware Getting
          Started guide</a> for that.</li>
          <li>The integrated client's CS role is fixed to <i>Initiator</i>; a loaded configuration with another
          CS role is normalized to Initiator. <i>Peripheral</i> is disabled in the GAP role selector, but a
          Peripheral value loaded from a saved configuration is preserved and can still advertise for a central
          peer. New configurations use selectable GAP Central.</li>
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
        <p>Hover over any control for its tooltip. The command <code>ble-channel-sounding-planner</code> opens the configuration
        planner on its own, without a client connection.</p>
        """,
    ),
    (
        "quickstart",
        "First steps with the simulator",
        """
        <p>The simulator is an in-memory client that answers every command like a real board. It needs no
        hardware, so it is the quickest way to learn the workflow. Start the app with <code>ble-channel-sounding --simulate</code>
        to select it automatically, or select it by hand as described below.</p>
        <ol>
          <li><b>Select the simulator.</b> In the <b>Serial port</b> group, on the <b>Client</b> tab, choose
          <b>Simulator — in-memory client</b> as the Port. If the Serial port group is hidden, click the summary
          bar at the top of the window to expand it.</li>
          <li><b>Connect.</b> Click <b>Connect client</b> on the session toolbar. The status bar shows the firmware
          version and the session state.</li>
          <li><b>Synchronise.</b> BLE Channel Sounding Host now compares its configuration with the client's. When they differ, the
          <b>Synchronise configuration</b> dialog opens: choose <b>Apply host configuration to client</b> to send
          the settings shown in the Configuration tab, or <b>Get configuration from client</b> to load supported
          settings into the app. The integrated client fixes the CS role to Initiator.</li>
          <li><b>Find the reflector.</b> Click <b>Scan</b>. Matching peers appear in the list next to the session
          toolbar. Select one and click <b>Connect peer</b>.</li>
          <li><b>Start.</b> Click <b>Start session</b>. Results arrive in the <b>Results</b> tab; every record
          appears in the <b>Session</b> tab.</li>
          <li><b>Stop.</b> Click <b>Stop session</b>. The peer stays connected, so you can start another run with
          the same configuration. To change settings, edit them, click <b>Apply config</b>, reconnect the peer,
          then start again.</li>
        </ol>
        <p>To try the recording features, enable <b>Record each run</b> in the Recording group before starting,
        or use <b>Save session…</b> after stopping. See <a href="help:recording">Recording and export</a>.</p>
        <p>To replay a recording through the simulator, start the app with
        <code>ble-channel-sounding --simulate path/to/recording.h5</code>. The simulator then sends the recorded reports
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
          that BLE Channel Sounding Host controls.</li>
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
          <li>Adjust the measurement in the other Configuration tabs, then click <b>Apply config</b>. BLE Channel Sounding Host
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
          <li><b>Apply config</b> while a peer is connected disconnects the peer first; BLE Channel Sounding Host asks before it
          does. Connect the peer again after applying.</li>
          <li><b>Disconnect peer</b> drops the Bluetooth link and opens a fresh client session, ready to scan for
          another device.</li>
          <li><b>Disconnect client</b> ends the client session and the peer link, but keeps the serial port.</li>
        </ul>
        <p>If BLE Channel Sounding Host connects to a client that is already running a measurement, it loads the client's
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
        itself, and streams its reports over USB. BLE Channel Sounding Host can receive and decode that stream.</p>
        <ol>
          <li>Set <b>Operation mode</b> to <b>CS Hostless</b>.</li>
          <li>In <b>Serial port → Client</b>, choose the hostless initiator's USB CDC ACM port.</li>
          <li>Click <b>Connect client</b>. Reports appear in Results and Session as they arrive.</li>
        </ol>
        <p>In this mode BLE Channel Sounding Host only listens:</p>
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
        <p class="screenshot"><img src="main-window.png" alt="BLE Channel Sounding Host main window"></p>
        <p><i>BLE Channel Sounding Host connected to the simulator after a run. No hardware is connected.</i>
        <a href="screenshot:main-window">View full-size screenshot</a></p>
        <ol>
          <li><b>General controls:</b> operation mode, Console log and Host log. See
          <a href="help:logs">Logs and the peer console</a> for what the log levels control.</li>
          <li><b>Session toolbar:</b> connect, configure, scan, connect to a peer, run, record and open help.
          The peer selector and <b>Show all</b> are between <b>Scan</b> and <b>Connect peer</b>.</li>
          <li><b>Summary bar:</b> port, baud rate, operation mode, GAP role, recording and connection state;
          click it to show or hide the settings panel.</li>
          <li><b>Serial port:</b> choose the client board's USB port. The Peer tab is disabled in this build.</li>
          <li><b>Recording:</b> choose a folder and record each run, or save session history afterwards.</li>
          <li><b>Main tabs:</b> Configuration, Results and Session.</li>
          <li><b>Status bar:</b> client information on the left; session, sync and link state and counters on
          the right.</li>
        </ol>
        <p>The window is arranged from top to bottom:</p>
        <table>
          <tr><th>Area</th><th>Contents</th></tr>
          <tr><td>Summary bar</td><td>One line with the port, baud rate, operation mode, GAP role, recording
          state and connection state. Click it (or ▲/▼) to show or hide the settings panel below it.</td></tr>
          <tr><td>Settings panel</td><td><b>Serial port</b> (the Client tab; Peer is disabled in this build) and
          <b>Recording</b> side by side.</td></tr>
          <tr><td>General controls</td><td><b>Operation mode</b> (CS or CS Hostless; Radio Test is disabled) and
          the client log levels <b>Console log</b> and <b>Host log</b> (see
          <a href="help:logs">Logs and the peer console</a>).</td></tr>
          <tr><td>Session toolbar</td><td>Connection, configuration, peer, run and record actions, and
          the Help icon. The peer selector and <b>Show all</b> sit between <b>Scan</b> and <b>Connect peer</b>. See
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
        <p>Action availability changes with operation mode, connection, configuration sync, peer link and run
        state. Check the status bar and the live tooltip on disabled actions for the current prerequisite. In
        <b>CS Hostless</b> mode, the app only receives reports; see <a href="help:hostless">Hostless mode</a>.</p>
        <table>
          <tr><th>Action</th><th>What it does</th></tr>
          <tr><td><b>Connect client</b></td><td>Opens the selected port and starts a client session. While the
          handshake is pending it reads <i>Cancel connection</i>; once connected it becomes <b>Disconnect
          client</b>, which ends the session and peer link but keeps the port open.</td></tr>
          <tr><td><b>Apply config</b></td><td>Validates the Configuration tab and sends it to the client. A
          connected peer is disconnected first, after confirmation.</td></tr>
          <tr><td><b>Synchronise</b></td><td>Compares host and client configuration and lets you get the
          client's or apply the host's.</td></tr>
          <tr><td><b>Scan</b></td><td>Searches for advertising peers and fills the peer list. A new scan clears
          the list.</td></tr>
          <tr><td><b>Connect peer</b></td><td>Connects the peer selected in the list, scanning first if nothing is
          listed. Becomes <b>Disconnect peer</b> while linked.</td></tr>
          <tr><td><b>Start session</b></td><td>Starts CS procedures and a new session.</td></tr>
          <tr><td><b>Stop session</b></td><td>Ends the run and its recording; keeps the link. Also stops an
          active scan or connection attempt.</td></tr>
          <tr><td><b>Record from now</b></td><td>Records the rest of a run that is not being recorded. The file
          is marked partial.</td></tr>
          <tr><td><b>Describe session</b></td><td>Edits the notes kept with the session and written to its
          recording.</td></tr>
          <tr><td><b>Open capture…</b></td><td>Loads a recording or capture file into Results and Session for
          review.</td></tr>
          <tr><td><b>Clear</b></td><td>Removes the shown results, the open capture and the session timeline.
          </td></tr>
          <tr><td><b>Help icon</b></td><td>Opens these topics.</td></tr>
        </table>
        <p>The peer selector and <b>Show all</b> sit between <b>Scan</b> and <b>Connect peer</b>. The selector
        shows each scanned peer's name, address and signal strength (RSSI). By default it lists only names that
        start with a configured prefix. <b>Show all</b> lists every peer, including unnamed ones. If a loaded
        configuration uses GAP role Peripheral, the peer discovery controls are replaced by an
        <b>Advertise</b> button in the configuration panel; the client advertises and waits for a central to
        connect.</p>
        """,
    ),
    (
        "configuration",
        "Configuring a measurement",
        f"""
        <p class="screenshot"><img src="configuration.png" alt="BLE Channel Sounding Host configuration screen"></p>
        <p><i>Configuration view with the simulator connected; no hardware is connected.</i>
        <a href="screenshot:configuration">View full-size screenshot</a></p>
        <ol>
          <li><b>Planner actions:</b> open, save, export C configuration, export view, fit views and reset.</li>
          <li><b>Settings tabs:</b> CS setup, Connection, CS modes, Schedule and Channels.</li>
          <li><b>Settings form:</b> edit the values of the selected tab here.</li>
          <li><b>Help pane:</b> explanations for the current tab or the selected setting.</li>
          <li><b>Position line:</b> the procedure, event, subevent and step shown in the illustrations.</li>
          <li><b>Illustration tabs:</b> switch among connection, procedures, events, steps and channels.</li>
          <li><b>Illustration:</b> what the settings produce, with an explanation above it.</li>
          <li><b>Status footer:</b> plan validity and summary such as steps, subevents and elapsed time. Click
          the <b>▼</b> at its right end to expand detailed validation results, errors and suggested corrections.</li>
        </ol>
        <p>The <b>Configuration</b> tab is a planner: the left side holds the settings, the right side draws what
        those settings produce, and the pane below explains the selected setting. Nothing reaches the client
        until you click <b>Apply config</b>.</p>

        <h2>Settings tabs</h2>
        <table>
          <tr><th>Tab</th><th>Settings</th></tr>
          <tr><td><b>CS setup</b></td><td>Bluetooth name of the client, CS role (fixed to Initiator), GAP role
          (Central is selectable; a loaded Peripheral value is preserved), Peripheral prefixes (the scan filter),
          CS_SYNC antenna, maximum TX power, reference PHY, TX power delta, preferred peer antennas, SNR control
          and creation context.</td></tr>
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
        run time; they only shape the illustration and are never sent. The screenshots below use
        <i>Mode 2 + sub-mode 1</i>; forms longer than the pane scroll.</p>

        <h3>CS setup</h3>
        <p class="screenshot"><img src="config-cs-setup.png" alt="CS setup settings tab"></p>
        <p><a href="screenshot:config-cs-setup">View full-size screenshot</a></p>
        <ol>
          <li><b>CS role:</b> fixed to Initiator for the integrated client.</li>
          <li><b>Bluetooth name and GAP role:</b> the client's advertised name and its Bluetooth role.</li>
          <li><b>Radio:</b> CS_SYNC antenna, maximum TX power, reference PHY and TX power delta.</li>
          <li><b>Preferred peer antenna:</b> the reflector antennas to use for tones.</li>
          <li><b>SNR control:</b> initiator and reflector SNR output. Peripheral prefixes and creation context
          follow further down the form.</li>
        </ol>

        <h3>Connection</h3>
        <p class="screenshot"><img src="config-connection.png" alt="Connection settings tab"></p>
        <p><a href="screenshot:config-connection">View full-size screenshot</a></p>
        <ol>
          <li><b>Requested interval:</b> the minimum and maximum connection interval.</li>
          <li><b>Latency and timeout:</b> peripheral latency and supervision timeout.</li>
          <li><b>Example values selected by the controller:</b> selected interval, ACL activity, ATT MTU and CS
          offset from the anchor.</li>
        </ol>

        <h3>CS modes</h3>
        <p class="screenshot"><img src="config-cs-modes.png" alt="CS modes settings tab"></p>
        <p><a href="screenshot:config-cs-modes">View full-size screenshot</a></p>
        <ol>
          <li><b>Mode combination:</b> the main mode and optional sub-mode.</li>
          <li><b>Step counts:</b> Mode-0 prefix, main-mode repetition and the minimum and maximum main-mode
          run.</li>
          <li><b>CS_SYNC PHY and RTT sequence.</b></li>
          <li><b>Antenna configuration and inline PCT transfer (IPT).</b></li>
          <li><b>Reflector data:</b> how the reflector returns its results. Preferred T_PM and the example
          timing values follow further down the form.</li>
        </ol>

        <h3>Schedule</h3>
        <p class="screenshot"><img src="config-schedule.png" alt="Schedule settings tab"></p>
        <p><a href="screenshot:config-schedule">View full-size screenshot</a></p>
        <ol>
          <li><b>Subevent budget:</b> the subevent length, with the calculated minimum for one fresh step.</li>
          <li><b>Procedure:</b> procedure budget, procedure spacing and procedure count.</li>
          <li><b>Example values selected by the controller:</b> fresh-step workload, subevents per event,
          subevent spacing, CS event spacing and preview instances.</li>
        </ol>

        <h3>Channels</h3>
        <p class="screenshot"><img src="config-channels.png" alt="Channels settings tab"></p>
        <p><a href="screenshot:config-channels">View full-size screenshot</a></p>
        <ol>
          <li><b>Presets:</b> All, Even, Odd and None.</li>
          <li><b>Channel switches:</b> click a channel to enable or disable it; greyed channels are reserved.</li>
          <li><b>Channel map:</b> the map as hexadecimal text and the number of enabled channels.</li>
          <li><b>Map repetition.</b></li>
          <li><b>Channel selection:</b> the channel selection algorithm (CSA #3b or #3c).</li>
        </ol>

        <h2>Illustrations</h2>
        <p>The tabs on the right draw the plan at five levels: <b>1 Connection</b>, <b>2 Procedures</b>,
        <b>3 Events &amp; subevents</b>, <b>4 Individual step</b> and <b>5 Channels</b>. The status footer below
        summarises the plan: whether it is complete or needs attention, fresh steps placed, subevents, CS events
        and elapsed time. When a peer is connected, the Connection illustration uses the negotiated connection
        interval. Click a block or marker to inspect it; hover over it for its timing.</p>
        <p>In every illustration screenshot, <b>1</b> is the position line (procedure, event, subevent and step),
        <b>2</b> is the explanation of the current view, and the last callout is the status footer's <b>▼</b>,
        which expands detailed validation results, errors and correction guidance.</p>

        <h3>1 Connection</h3>
        <p class="screenshot"><img src="planner-connection.png" alt="Connection illustration"></p>
        <p><a href="screenshot:planner-connection">View full-size screenshot</a></p>
        <ol>
          <li>Position line.</li>
          <li>Explanation: interval, latency, procedure repetition and RAS transfer.</li>
          <li><b>RAS (reflector):</b> the reflector's real-time data on the ACL events after the procedure.</li>
          <li><b>Selected CS:</b> CS events placed after the ACL anchors.</li>
          <li><b>ACL anchors:</b> connection events of the central and an example peripheral.</li>
          <li><b>Supervision timeout:</b> how long the link survives without a valid reception.</li>
          <li>Status footer <b>▼</b>.</li>
        </ol>

        <h3>2 Procedures</h3>
        <p class="screenshot"><img src="planner-procedures.png" alt="Procedures illustration"></p>
        <p><a href="screenshot:planner-procedures">View full-size screenshot</a></p>
        <ol>
          <li>Position line.</li>
          <li>Explanation: CS event spacing, procedure spacing and budget.</li>
          <li><b>RAS (reflector):</b> reflector data after each procedure.</li>
          <li><b>ACL anchors.</b></li>
          <li><b>CS events:</b> the events of each procedure; click one to inspect it.</li>
          <li><b>Procedure instances:</b> the repeated procedures; click one to inspect it.</li>
          <li>Status footer <b>▼</b>.</li>
        </ol>

        <h3>3 Events &amp; subevents</h3>
        <p class="screenshot"><img src="planner-events-subevents.png" alt="Events and subevents illustration"></p>
        <p><a href="screenshot:planner-events">View full-size screenshot</a></p>
        <ol>
          <li>Position line.</li>
          <li>Explanation: start, end and duration of the event.</li>
          <li><b>Steps by mode:</b> Mode-0 steps first in each subevent, then the main-mode and sub-mode
          steps.</li>
          <li><b>Occupied:</b> the time the steps use in each subevent.</li>
          <li><b>Reserved subevent:</b> the subevent budget.</li>
          <li>Status footer <b>▼</b>.</li>
        </ol>

        <h3>4 Individual step</h3>
        <p class="screenshot"><img src="planner-individual-step.png" alt="Individual step illustration"></p>
        <p><a href="screenshot:planner-step">View full-size screenshot</a></p>
        <ol>
          <li>Position line.</li>
          <li>Explanation: mode, timing, antenna paths and example channel of the step.</li>
          <li><b>Initiator TX:</b> what the initiator transmits.</li>
          <li><b>Reflector TX:</b> what the reflector transmits.</li>
          <li><b>Timing:</b> gaps such as T_IP1 between the transmissions.</li>
          <li>Status footer <b>▼</b>.</li>
        </ol>

        <h3>5 Channels</h3>
        <p class="screenshot"><img src="planner-channels.png" alt="Channels illustration"></p>
        <p><a href="screenshot:planner-channels">View full-size screenshot</a></p>
        <ol>
          <li>Position line.</li>
          <li>Explanation: an example hop sequence and how it is built.</li>
          <li><b>Hop sequence:</b> the channel of each step in the procedure, by mode.</li>
          <li><b>CS channels:</b> enabled and disabled channels across the band; click one to toggle it.</li>
          <li><b>Wi-Fi reference:</b> Wi-Fi channels 1, 6 and 11 for comparison.</li>
          <li>Status footer <b>▼</b>.</li>
        </ol>

        <h2>Help pane</h2>
        <p><b>About this tab</b> explains the settings tab you are on. <b>Setting details</b> gives the full
        description of the setting you last selected: what it defines, how the controller selects it, what a
        change does and where the Bluetooth Core Specification defines it.</p>

        <h2>Planner actions</h2>
        <ul>
          <li><b>Open…</b> loads a planner JSON file or an exported C file. <b>Save…</b> writes the plan as
          JSON.</li>
          <li><b>Export C configuration…</b> writes <code>cs_generated_config.c</code> for the initiator, the
          reflector or both (one file per role) for the hostless firmware. This export supports both CS roles
          even though the integrated client configuration is fixed to Initiator.</li>
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
        <p class="screenshot"><img src="results.png" alt="BLE Channel Sounding Host results screen"></p>
        <p><i>Synthetic sample data for illustration; this is not a live RF measurement.</i>
        <a href="screenshot:results">View full-size screenshot</a></p>
        <ol>
          <li><b>Results:</b> select the main results view.</li>
          <li><b>Result tabs:</b> choose available analyses, which depend on the session's CS modes.</li>
          <li><b>Analysis selectors:</b> choose procedure and antenna path, and set analysis options.</li>
          <li><b>Plot lines:</b> show or hide the distance estimates to compare.</li>
          <li><b>Graph:</b> inspect estimates across procedures.</li>
          <li><b>Summary:</b> review the selected session's data summary.</li>
        </ol>
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
          unwrapped, with the fitted lines. A consistent unwrapped trend supports ranging; the estimate also
          depends on the selected sign and frequency-offset correction, so compare it with a known distance.</td></tr>
          <tr><td><b>RTT</b></td><td>Round-trip-time distances of Mode-1 or Mode-3 steps, with accepted and
          rejected steps and their spread.</td></tr>
          <tr><td><b>Estimates</b></td><td>Distance per procedure over time. Use <b>Plot lines</b> to compare RTT
          mean and median, raw PBR, and PBR corrected by the Mode-0 offset or by the reported frequency
          compensation.</td></tr>
        </table>
        <p>The screenshots below come from a simulator run with <i>Mode 2 + sub-mode 1</i>, so every tab is
        shown. Their values are synthetic and do not represent radio accuracy.</p>

        <h3>Controller</h3>
        <p class="screenshot"><img src="results-controller.png" alt="Controller results tab"></p>
        <p><a href="screenshot:results-controller">View full-size screenshot</a></p>
        <ol>
          <li><b>Capabilities:</b> local and remote controller capabilities.</li>
          <li><b>Remote FAE table:</b> the reflector's frequency actuation error per channel.</li>
          <li><b>Connection parameters:</b> requested and negotiated.</li>
          <li><b>Configuration complete:</b> the CS configuration the controllers agreed.</li>
          <li><b>Procedure enable complete:</b> the procedure parameters the controllers agreed.</li>
          <li><b>Compatibility:</b> requested settings a controller does not support.</li>
          <li><b>Summary:</b> sources and the number of compatibility issues.</li>
        </ol>

        <h3>Mode 0 / FFO</h3>
        <p class="screenshot"><img src="results-mode-0-ffo.png" alt="Mode 0 and FFO results tab"></p>
        <p><a href="screenshot:results-mode0">View full-size screenshot</a></p>
        <ol>
          <li><b>Mode-0 measured offset:</b> the mean offset of the Mode-0 steps in each report.</li>
          <li><b>Frequency compensation:</b> the compensation the controller reported.</li>
          <li><b>Summary:</b> the latest report and the time window shown.</li>
        </ol>

        <h3>PBR per channel</h3>
        <p class="screenshot"><img src="results-pbr-per-channel.png" alt="PBR per channel results tab"></p>
        <p><a href="screenshot:results-pbr">View full-size screenshot</a></p>
        <ol>
          <li><b>Analysis selectors:</b> procedure, antenna path, sign and high-quality tones only.</li>
          <li><b>Amplitude:</b> initiator and reflector PCT magnitude per channel.</li>
          <li><b>Wrapped phase:</b> reflector and product phase per channel, raw and corrected.</li>
          <li><b>Unwrapped product phase:</b> raw and corrected phase with their fitted lines.</li>
          <li><b>Summary:</b> step pairs, offsets and the slope distance of each correction.</li>
        </ol>

        <h3>RTT</h3>
        <p class="screenshot"><img src="results-rtt.png" alt="RTT results tab"></p>
        <p><a href="screenshot:results-rtt">View full-size screenshot</a></p>
        <ol>
          <li><b>Analysis selectors:</b> procedure, AA successful only and Max errors.</li>
          <li><b>Distance by CS channel:</b> accepted and rejected steps with the mean and median.</li>
          <li><b>Distance distribution:</b> a histogram of the accepted steps.</li>
          <li><b>Summary:</b> accepted step pairs, mean, median and spread.</li>
        </ol>

        <h3>Estimates</h3>
        <p class="screenshot"><img src="results-estimates.png" alt="Estimates results tab"></p>
        <p><a href="screenshot:results-estimates">View full-size screenshot</a></p>
        <ol>
          <li><b>Analysis selectors:</b> the PBR and RTT options that the estimates use.</li>
          <li><b>Plot lines:</b> show or hide each estimate.</li>
          <li><b>Distance estimates:</b> one point per procedure over time.</li>
          <li><b>Summary:</b> the latest procedure's estimates and the time window shown.</li>
        </ol>

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
          <li><b>Host log</b>: messages sent to BLE Channel Sounding Host. They appear in the Session tab as <i>Client log</i>
          and are recorded.</li>
        </ul>
        <p>Each level (Off, Error, Warning, Info, Debug) includes the more severe ones. The levels are part of
        the applied configuration, so click <b>Apply config</b> after changing them.</p>

        <h2>Peer console</h2>
        <p>The Peer tab for the second serial port is disabled in this build, so the peer console cannot be
        configured or opened from the app. Existing recordings can still contain peer-console lines; they appear
        in the Session tab under <b>Peer</b>. The nRF54L15 Tag logs over RTT instead of a UART and needs an SWD
        probe and an RTT viewer.</p>
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
          <tr><td>Scan or Connect peer is disabled</td><td>Use hosted CS mode with GAP Central, connect the client,
          synchronise the configuration, and disconnect any existing peer before scanning again.</td></tr>
          <tr><td>Start session is disabled</td><td>Hover over it: it names the missing step (configuration not in
          sync, no peer scanned, or peer not connected).</td></tr>
          <tr><td>Apply config is rejected</td><td>The message names the rejected setting. Check the Controller
          view's Capabilities and Compatibility for what the boards support, for example the number of
          antennas.</td></tr>
          <tr><td>Results are empty or noisy</td><td>Check the Controller view for the negotiated configuration
          and the Session tab for warnings. For PBR, try another Path or sign; for RTT, relax <b>Max errors</b>.
          </td></tr>
          <tr><td>The client was already running</td><td>BLE Channel Sounding Host loaded its configuration. Stop the run, or use
          <b>Record from now</b> to keep it.</td></tr>
        </table>
        <p>For build, flash and wiring questions, see the <a href="{HARDWARE_GUIDE}">hardware Getting Started
        guide</a>. For detailed behaviour of every feature, see the <a href="{HOST_REFERENCE}">BLE Channel Sounding Host
        reference</a>.</p>
        """,
    ),
)

STYLE = """
    body {{ color: #21334b; }}
    h1 {{ font-size: 22px; margin-bottom: 8px; }}
    h2 {{ font-size: 16px; margin-top: 18px; margin-bottom: 4px; }}
    p, li {{ line-height: 135%; }}
    p.screenshot {{ line-height: 100%; }}
    p.lead {{ font-size: 15px; }}
    img {{ border: 1px solid #cbd8e6; }}
    code, pre {{ font-family: '{mono}', 'Menlo', 'Consolas', 'DejaVu Sans Mono', 'Courier New', monospace; }}
    pre {{ background-color: #eef3f9; }}
    table {{ border-collapse: collapse; margin-top: 6px; margin-bottom: 6px; }}
    th {{ background-color: #eef3f9; text-align: left; }}
    th, td {{ border: 1px solid #cbd8e6; padding: 5px; vertical-align: top; }}
    a {{ color: #146fba; }}
"""


class HelpBrowser(W.QTextBrowser):
    """Text browser that scales page images to the viewport width whenever it is resized.

    The width is set in code so it does not depend on how the installed Qt handles CSS max-width.
    """

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_images()

    def fit_images(self):
        document = self.document()
        available = self.viewport().width() - 2 * document.documentMargin() - 4
        images = []
        block = document.begin()
        while block.isValid():
            fragments = block.begin()
            while not fragments.atEnd():
                fragment = fragments.fragment()
                if fragment.charFormat().isImageFormat():
                    images.append(fragment)
                fragments += 1
            block = block.next()
        for fragment in images:
            image = fragment.charFormat().toImageFormat()
            source = document.resource(QtGui.QTextDocument.ResourceType.ImageResource, QtCore.QUrl(image.name()))
            if not isinstance(source, (QtGui.QPixmap, QtGui.QImage)) or source.isNull():
                continue
            width = max(1, min(available, source.width()))
            if abs(image.width() - width) < 1:
                continue
            image.setWidth(width)
            image.setHeight(width * source.height() / source.width())
            cursor = QtGui.QTextCursor(document)
            cursor.setPosition(fragment.position())
            cursor.setPosition(fragment.position() + fragment.length(), QtGui.QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(image)


class HelpDialog(W.QDialog):
    """Non-modal help window: topic list on the left, the selected page on the right."""

    def __init__(self, parent=None, topic="about"):
        super().__init__(parent)
        self.setWindowTitle("BLE Channel Sounding Host Help")
        self.resize(1360, 920)
        layout = W.QVBoxLayout(self)
        splitter = W.QSplitter(self)
        layout.addWidget(splitter, 1)

        self.topics = W.QListWidget()
        self.topics.setStyleSheet("QListWidget { font-size: 14px; } QListWidget::item { padding: 6px; }")
        self.browser = HelpBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setSearchPaths([str(Path(__file__).resolve().parent.parent / "assets" / "help")])
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
            self.browser.fit_images()

    def show_topic(self, key):
        """Select topic key; an unknown key selects the first topic."""
        keys = [page[0] for page in HELP_PAGES]
        self.topics.setCurrentRow(keys.index(key) if key in keys else 0)

    def follow_link(self, url):
        if url.scheme() == "help":
            self.show_topic(url.path())
        elif url.scheme() == "screenshot":
            self.open_screenshot(url.path())
        else:
            QtGui.QDesktopServices.openUrl(url)

    def open_screenshot(self, key):
        entry = SCREENSHOTS.get(key)
        if entry is None:
            return
        title, filename = entry
        dialog = ScreenshotDialog(self, title, Path(__file__).resolve().parent.parent / "assets" / "help" / filename)
        dialog.exec()


class ScreenshotDialog(W.QDialog):
    """Show a help screenshot with fit and pixel-scale viewing options."""

    def __init__(self, parent, title, image_path):
        super().__init__(parent)
        self.setWindowTitle(f"BLE Channel Sounding Host Help — {title}")
        self.resize(1450, 950)
        self.setMinimumSize(800, 600)
        self.source = QtGui.QPixmap(str(image_path))

        layout = W.QVBoxLayout(self)
        controls = W.QHBoxLayout()
        controls.addWidget(W.QLabel(f"{self.source.width()} × {self.source.height()} px, captured at 2× scale"))
        controls.addStretch(1)
        fit_button = W.QPushButton("Fit to window")
        half_button = W.QPushButton("50% (app scale)")
        full_button = W.QPushButton("100% (pixel scale)")
        close_button = W.QPushButton("Close")
        controls.addWidget(fit_button)
        controls.addWidget(half_button)
        controls.addWidget(full_button)
        controls.addWidget(close_button)
        layout.addLayout(controls)

        self.scroll = W.QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.image = W.QLabel()
        self.image.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.image)
        layout.addWidget(self.scroll, 1)

        fit_button.clicked.connect(self.fit_to_window)
        half_button.clicked.connect(lambda: self.show_scale(0.5))
        full_button.clicked.connect(lambda: self.show_scale(1.0))
        close_button.clicked.connect(self.accept)
        QtCore.QTimer.singleShot(0, lambda: self.show_scale(0.5))

    def fit_to_window(self):
        viewport = self.scroll.viewport().size()
        if self.source.isNull() or viewport.isEmpty():
            return
        factor = min(viewport.width() / self.source.width(), viewport.height() / self.source.height())
        self.show_scale(factor)

    def show_scale(self, factor):
        if self.source.isNull():
            self.image.setText("Screenshot could not be loaded.")
            return
        size = QtCore.QSize(round(self.source.width() * factor), round(self.source.height() * factor))
        scaled = self.source.scaled(size, QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                                    QtCore.Qt.TransformationMode.SmoothTransformation)
        self.image.setPixmap(scaled)
        self.image.resize(scaled.size())
