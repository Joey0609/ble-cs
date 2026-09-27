# BLE Channel Sounding

This workspace contains Bluetooth Channel Sounding firmware for Nordic nRF54
boards, a desktop host and planner, shared C libraries, and test applications.
The main hardware setup is a USB connected **CS Client** controlled by the
desktop app, paired with a CS reflector. For operation without a command host,
use the hostless initiator and reflector images.

Bluetooth Channel Sounding has many configuration options, and testing them
well requires careful validation and a detailed understanding of the procedure.
This repository provides end-to-end tools to make that work easier to learn and
repeat. The planner and desktop application let users configure and inspect a
CS exchange from connection parameters down to individual CS steps. The
Python-based PC application provides the user interface and interacts with
Nordic development kits running client firmware. The primary host connection
is USB CDC ACM on the DK, such as the nRF54LM20 DK. A debug serial connection
may also work for slower configurations, but has not been tested.

Hostless operation stores the configuration in firmware flash at build time.
The PC software can still receive reports for visualization and session
recording, but it does not configure or control the hostless firmware.

## Shared firmware libraries

[`common/libs/`](common/libs/) is the shared firmware software layer used by
the applications in this workspace. It provides reusable components that let
firmware projects build on the same Nordic development tools and board support
without reimplementing their core plumbing. Components cover CS configuration,
Bluetooth roles and results, the host protocol and USB/serial link, generated
configuration handling, and application session and logging management. This
gives application firmware a common path for setup, host interaction, session
state and diagnostics across the hosted and hostless projects.

## PC application responsibilities

The `ble-channel-sounding` PC software supports the experiment workflow:

- Generate and visualize configurations, and save or load them for reuse.
- Check configuration time budgets and explain parameters with reference to
  Bluetooth Core Specification version 6.3.
- Scan for reflectors and help establish a complete ranging link between an
  initiator and reflector.
- Receive negotiated connection parameters, the completed CS configuration,
  and enabled procedure parameters from the controller.
- Show controller status and capabilities.
- Visualize PBR and RTT step data associated with each procedure.
- Manage experiment sessions with a complete event history, a temporary live
  session, session saving, and replay.

**Radio Test is disabled in the desktop app for this deployment.** Its firmware
images and implementation are retained for later re-enablement, but are work in
progress and are not part of the supported deployment flow.

Start with the [Getting Started guide](docs/GETTING_STARTED.md). It covers the
hosted CS workflow, hostless CS workflow, board roles, build and flash commands,
and starting the desktop app.

## Projects

| Project | Purpose | Documentation |
| --- | --- | --- |
| `cs_client` | USB-hosted Bluetooth CS client. The desktop host configures it and starts initiator or reflector operation. | [cs_client/README.md](cs_client/README.md) |
| `cs_hostless_initiator` | Standalone Bluetooth CS initiator. Scans for and connects to a reflector; streams reports over USB CDC without accepting host commands. | [cs_hostless_initiator/README.md](cs_hostless_initiator/README.md) |
| `cs_hostless_reflector` | Standalone Bluetooth CS reflector for the nRF54LM20 DK, nRF54L15 DK, and nRF54L15 Tag. | [cs_hostless_reflector/README.md](cs_hostless_reflector/README.md) |
| `cs_reflector_tag` | Connected nRF54L15 Tag reflector using its two switched antennas. | [cs_reflector_tag/README.md](cs_reflector_tag/README.md) |
| `cs_radio_test_client` | Standalone radio-test host-link firmware. **Work in progress; disabled for deployment.** | [cs_radio_test_client/README.md](cs_radio_test_client/README.md) |
| `cs_tag_modulated_tx` | nRF54L15 Tag modulated transmit utility for RF experiments. | [cs_tag_modulated_tx/README.md](cs_tag_modulated_tx/README.md) |
| `python/ble_channel_sounding` | Desktop configuration, live CS results, logs and session recording application (`ble-channel-sounding`). | [Getting Started](python/ble_channel_sounding/GETTING_STARTED.md), [reference](python/ble_channel_sounding/README.md) |
| `python/ble_channel_sounding_planner` | Standalone CS planner frontend and C configuration export support. | [python/ble_channel_sounding_planner/README.md](python/ble_channel_sounding_planner/README.md) |
| `common/libs` | Shared protocol, configuration, host link, CS roles, logging and radio-test support libraries. | [Protocol](common/libs/cs_protocol/README.md), [CS configuration](common/libs/cs_utils/README.md), [host link](common/libs/host_link/README.md), [logging](common/libs/app_log/README.md), [radio-test helpers](common/libs/radio_test_utils/README.md) |
| `tests` | Firmware test applications and native C tests for shared libraries. | [Initiator](tests/cs_initiator_test/README.md), [reflector](tests/cs_reflector_test/README.md), [radio test](tests/radio_test/src/README.md), [USB ACM rate test](tests/usb_acm_rate_test/README.md) |

## Development kits

| Kit | Projects and role | Host connection / output |
| --- | --- | --- |
| nRF54LM20 DK (`nrf54lm20dk/nrf54lm20b/cpuapp`) | Primary board for `cs_client`, `cs_hostless_initiator`, and `cs_hostless_reflector`. Use one as the hosted client or hostless initiator and a second as a reflector when needed. | `cs_client` uses native USB CDC ACM for the host protocol. Debug logs use the DK debug UART. The hostless initiator sends reports over USB CDC ACM. |
| nRF54L15 DK (`nrf54l15dk/nrf54l15/cpuapp`) | Supported hostless reflector board; one CS antenna. | Debug UART at 921600 baud. |
| nRF54L15 Tag (`nrf54l15tag/nrf54l15/cpuapp`) | Two-antenna reflector target for `cs_reflector_tag`; the hostless reflector also has a Tag build. | RTT over an external SWD probe for logs; no native USB or debug UART bridge. |

The Tag's two antennas use its SKY13348 RF switch. See the [Tag reflector
README](cs_reflector_tag/README.md) for board wiring and antenna constraints.

## SDK and tool versions

The firmware's documented baseline is **nRF Connect SDK (NCS) v3.4.1** with
its matching **nRF Connect SDK Toolchain v3.4.1**. Install the SDK release and
matching toolchain together using the [Nordic installation guide](https://nrfconnectdocs.nordicsemi.com/ncs/latest/nrf/installation/install_ncs.html),
then build from that NCS terminal with `west`.
The repository does not contain an NCS west manifest or lock the NCS component
revisions, so use the same release across all firmware builds. The host app
requires Python 3.10 or newer; see [python/README.md](python/README.md) for the
host setup.

## Licensing

Project software is MIT licensed. Project-authored documentation and design
materials are CC BY 4.0; third-party standards and references retain their own
terms. See [LICENSE](LICENSE), [LICENSE-DOCS.md](LICENSE-DOCS.md), and
[LICENSING.md](LICENSING.md) for scope and Zephyr/NCS notes.

## Quick start

From the repository root, in the matching NCS terminal:

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp \
  -d cs_client/build cs_client
west flash -d cs_client/build
```

Then install and launch the desktop host:

```sh
.venv/bin/python -m pip install -e ./python
ble-channel-sounding
```

For detailed connection, role selection, hostless operation and configuration
export steps, see [Getting Started](docs/GETTING_STARTED.md). Component build
options and board-specific behavior are described in each project's README.
