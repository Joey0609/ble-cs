# Getting started: hosted and hostless CS

This guide uses the nRF54LM20 DK for the hosted CS client and initiator, and
either the nRF54L15 DK or nRF54LM20 DK for a hostless reflector. The nRF54L15
Tag can be used as a two-antenna reflector. See the board table in the [workspace
README](../README.md) for each kit's console connection.

## Requirements

- nRF Connect SDK v3.4.1 and its matching nRF Connect SDK Toolchain v3.4.1.
- Nordic `west` and the board's J-Link drivers/programmer support.
- One or more supported Nordic development kits and USB cables. For the Tag,
  use an SWD probe for RTT logs.
- Python 3.10+ for the desktop host, with the repository's `.venv` when
  available.

Install the SDK and matching toolchain as a pair using the [Nordic NCS
installation guide](https://nrfconnectdocs.nordicsemi.com/ncs/latest/nrf/installation/install_ncs.html).
For command-line installations, start the matching NCS terminal with:

```sh
nrfutil sdk-manager toolchain launch --ncs-version v3.4.1 --terminal
```

Run firmware `west` commands from the workspace root in that terminal.

## Install and start the desktop host

From the workspace root:

```sh
.venv/bin/python -m pip install -e ./python
cs-app
```

Use the in-memory simulator to explore the interface without boards:

```sh
cs-app --simulate
```

In the desktop app, choose the board's client serial port under **Serial port →
Client**. The `cs_client` Bluetooth firmware exposes its host protocol as USB
CDC ACM. The debug UART is a separate console and carries firmware logs.

## Hosted CS operation

The hosted setup has a computer running `cs-app`, a USB-connected nRF54LM20 DK
running `cs_client`, and a reflector board. The reflector may run
`cs_hostless_reflector` or the connected `cs_reflector_tag` image.

Build and flash the hosted client:

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp \
  -d cs_client/build cs_client
west flash -d cs_client/build
```

Build and flash a hostless reflector. Example for the nRF54L15 DK:

```sh
west build -b nrf54l15dk/nrf54l15/cpuapp \
  -d cs_hostless_reflector/build-nrf54l15dk cs_hostless_reflector
west flash -d cs_hostless_reflector/build-nrf54l15dk
```

For the nRF54LM20 DK reflector, use
`nrf54lm20dk/nrf54lm20b/cpuapp`; for the two-antenna Tag, see the
[Tag reflector instructions](../cs_reflector_tag/README.md), including its
non-sysbuild command and RTT setup.

After the boards boot:

1. Connect `cs-app` to the USB CDC ACM client port and click **Connect client**.
2. Select **CS** mode and choose **Initiator** or **Reflector** in CS setup.
   For the common hostless-reflector arrangement, choose **Initiator**.
3. Apply the configuration. For a central initiator, start scanning, select
   the reflector from the peer list and connect to it. A peripheral reflector
   advertises after its configuration is applied.
4. Start the CS session. Use **Stop** before disconnecting the peer.
5. View capabilities, procedures and measurements in **Results**; recordings
   can be saved from the session controls.

**Radio Test mode is disabled** in this desktop application build. Its firmware
builds are marked work in progress and are not required for CS operation.

## Hostless CS operation

Hostless firmware starts Bluetooth and runs the selected role from its compiled
configuration. It has no host command channel. A planner export is optional;
each application documents its defaults and accepted export sources.

### Hostless initiator

Build and flash the initiator to an nRF54LM20 DK:

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp \
  -d cs_hostless_initiator/build cs_hostless_initiator
west flash -d cs_hostless_initiator/build
```

It scans for a matching reflector and starts CS when connected. By default it
looks for a name prefix `CSTag`; without planner name patterns, it also accepts
devices advertising the Ranging Service UUID. Reports are streamed on its USB
CDC ACM port. Firmware logs go to the DK debug UART and can also appear in
`cs-app` when its USB port is selected in **Serial port → Peer**.

Open `cs-app`, select **CS Hostless**, choose the initiator's USB CDC port as
the Client port, and click **Connect client** to receive reports. Configure the
initiator's debug UART as the Peer port if you also want to view its firmware
logs. Hostless mode is receive-only: configuration and start/stop commands are
controlled by the image's compiled configuration and its firmware behavior.

### Hostless reflector

Build and flash the reflector to the desired supported board. For the nRF54LM20
DK or Tag, use the commands from the [hostless reflector README](../cs_hostless_reflector/README.md).
The standalone hostless reflector uses the device name `CS Hostless Reflector`
by default. The connected Tag image uses the `CSTag` prefix. The reflector emits
logs only; it does not stream protocol reports to a host.

The initiator and reflector connect over Bluetooth. The initiator owns the
connection parameters and CS setup. A reflector log reports advertising,
connection, security, procedures and link state through its debug UART (DK) or
RTT (Tag).

## Build with a planner configuration

The CS planner can export C configuration source for firmware. The firmware
READMEs document each app's `CS_CONFIG_SOURCE` option and in-tree config path.
For example, build a hostless initiator with an exported source file:

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp \
  -d cs_hostless_initiator/build cs_hostless_initiator -- \
  -DCS_CONFIG_SOURCE=/path/to/cs_generated_config.c
```

Use matching CS role and antenna settings at both peers. The Tag has two local
antennas; the nRF54LM20 DK and nRF54L15 DK default to one. A successful build
does not verify Bluetooth or RF operation. Consult the project README for
hardware verification status and board-specific requirements.
