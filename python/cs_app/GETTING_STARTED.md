# CS Host: Getting Started

CS Host (`cs-app`) is the desktop application for measuring distance between two Bluetooth devices with Bluetooth Channel Sounding (CS). It controls a CS client board over USB, plans and applies the CS configuration, runs measurements, shows phase-based (PBR) and round-trip-time (RTT) results as they arrive, and records every session to HDF5 for later analysis or MATLAB export. It can also receive the report stream of hostless initiator firmware and export a planned configuration as C source for that firmware.

You can explore the interface with its built-in simulator before connecting hardware. Inside the app, **Help → Help topics…** (or the **Help** action at the right end of the session toolbar) opens with an overview of what the application does, followed by task-based topics.

## Install and open the app

CS Host requires Python 3.10 or newer. When the package is available on PyPI, install and launch it with:

```sh
python -m pip install cs-app
cs-app
```

You can also start it with `python -m cs_app`. If `cs-app` is not found, use the Python environment where you installed the package, or activate that environment first.

Run `cs-app --help` to see command-line options and examples.

For the current source checkout, install the workspace package in editable mode from the repository root:

```sh
.venv/bin/python -m pip install -e ./python
```

On Windows, the equivalent command is:

```powershell
.venv\Scripts\python.exe -m pip install -e .\python
```

## Try it without boards

Start CS Host with the in-memory client preselected:

```sh
cs-app --simulate
```

Or open the app normally and choose **Simulator — in-memory client** in **Serial port → Client**, then click **Connect client**. To replay an existing HDF5 capture through the simulator, pass its path:

```sh
cs-app --simulate path/to/session.h5
```

The simulator is useful for exploring controls, session flow, plots and recordings. Its generated measurements are synthetic and do not model radio accuracy. A capture is replayed from its recorded reports; it is not a live RF measurement.

## Use Bluetooth hardware

The host application does not flash or configure firmware on the boards. For the documented hosted setup, use an nRF54LM20 DK running the workspace's `cs_client` firmware and a separate Bluetooth CS reflector. A reflector can run the hostless reflector firmware (advertised as `CS Hostless Reflector` by default) or the Tag reflector image (name prefix `CSTag`). The full board setup, build commands and connections are in the [hardware Getting Started guide](https://github.com/Sens-Wear/ble-cs/blob/main/docs/GETTING_STARTED.md).

Firmware builds in this workspace use nRF Connect SDK (NCS) v3.4.1 and its matching toolchain. The client board exposes the host connection over USB CDC ACM; its debug UART is a different port. Use the client protocol implementation described in the [host protocol reference](https://github.com/Sens-Wear/ble-cs/blob/main/common/libs/cs_protocol/README.md).

## Run a hosted CS session

1. Connect the client board by USB. In **Serial port → Client**, select its USB CDC ACM port and click **Connect client**. The status bar shows the host connection state.
2. In **Configuration**, choose **CS** mode. Under **CS setup**, the CS role is **Initiator**, the only role the client supports. Set the **GAP role** to **Central** to scan for a reflector, and make sure **Peripheral prefixes** contains the start of the reflector's advertised name; the scan lists only matching peers. Peripheral remains supported for saved configurations, but cannot be selected in the UI.
3. Configure the measurement and click **Apply config**. The **Synchronise** action can load configuration from the client or apply the host's current settings.
4. For GAP **Central**, click **Scan**, select a matching reflector, then click **Connect peer**. If a loaded configuration already has GAP **Peripheral**, click **Advertise** and let the central device connect. The Bluetooth link must be established before a session can start.
5. Click **Start session**. Explore live data in **Results** and the event timeline in **Session**. Click **Stop session** when finished.

The Start action remains unavailable while the client is disconnected, the configuration is not synchronized, or the peer link is missing. The tooltip on the action describes the unmet requirement.

## Receive a hostless stream

A `cs_hostless_initiator` board measures on its own from its compiled configuration and streams its reports over USB. Select **CS Hostless** as the operation mode, choose the board's USB CDC ACM port in **Serial port → Client** and click **Connect client**. CS Host only listens in this mode: configuration, discovery and run commands are disabled, and the Configuration tab shows what the firmware reports.

## Save and reopen data

To save each run automatically, enable **Record each run** in the **Recording** panel and choose an output folder. Each run is written to a new HDF5 (`.h5`) file; existing files are not overwritten. Add an optional description before a run or with **Describe session**.

The app also keeps a temporary session history while you work. Use **Save session…** to keep a session that was not recorded automatically. Use **Open capture…** to load an HDF5 session for review, and **Convert file…** in the Recording panel to export supported recordings to MATLAB format.

## If something does not work

- **No client port appears:** check the USB data cable and select the board's USB CDC ACM client interface, not its debug UART. Close other programs that may have the port open.
- **Connect client fails:** confirm the board is running compatible `cs_client` firmware and that the selected port is the host protocol port.
- **The reflector is not listed:** check that the GAP role is **Central**, a **Peripheral prefixes** line matches the start of the advertised name (case-sensitive), and the reflector is advertising. **Show all** can reveal peers outside the configured name prefixes.
- **Start session is disabled:** hover over it for the current prerequisite. Usually the configuration needs to be applied or the Bluetooth peer needs to connect.
- **You only need to try the UI:** choose the simulator; NCS and hardware are not needed.

Radio Test mode is disabled in this desktop application build. For detailed application behavior and configuration options, see the [CS Host reference](https://github.com/Sens-Wear/ble-cs/blob/main/python/cs_app/README.md).
