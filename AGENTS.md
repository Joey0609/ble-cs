# AGENTS.md

## Scope

These instructions apply to the whole `BLE_CS` workspace. There are currently
no more-specific `AGENTS.md` files in subdirectories.

## Repository overview

This workspace contains Bluetooth Channel Sounding firmware for Nordic
nRF54L15/nRF54LM20 boards, the PyQt6 desktop host and planner, shared C
libraries, and firmware/native test applications. Firmware uses Zephyr and
Nordic Connect SDK through `west`/CMake. The host application requires Python
3.10+ and PyQt6. The documented firmware baseline is NCS v3.4.1 with its
matching nRF Connect SDK Toolchain v3.4.1. There is no workspace-level NCS west
manifest or lockfile; use the same NCS release across firmware projects.

The main deployment is `cs_client` connected to `ble-channel-sounding` over USB CDC ACM,
paired with a Bluetooth CS reflector. The `cs_hostless_*` applications run
without host commands and use a compiled/default configuration. Radio Test is
currently disabled in the desktop application; the radio-test firmware paths
remain in the repository as work in progress.

See the workspace [README](README.md) for project summaries and development kit
mapping, and [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) for build,
flash, hosted operation and hostless operation.

Important areas:

- `common/libs/`: common firmware software used by the application projects.
  It provides reusable CS configuration/results, protocol and host-link,
  Bluetooth role, generated-configuration, session-state and logging
  components so firmware can share the same integration with Nordic's
  development tools and boards.
- `cs_client/`: connected USB-hosted CS client with initiator/reflector and
  radio-test variant (WIP; Radio Test is disabled in the desktop app).
- `cs_radio_test_client/`: separate standalone radio-test host-link image
  (WIP; not part of deployment).
- `cs_hostless_initiator/`, `cs_hostless_reflector/`: standalone firmware
  applications.
- `cs_reflector_tag/`: nRF54L15 Tag reflector application and antenna-switch
  board overlay.
- `cs_tag_modulated_tx/`: Tag modulated-transmit utility for RF experiments.
- `tests/`: firmware applications and native C tests for shared libraries.
- `python/ble_channel_sounding/`: Python host application, protocol, simulator, recording,
  analysis, and Qt views.
- `python/ble_channel_sounding_planner/`: standalone planner frontend and C-export support.
- `python/tests/`: Python unit and optional offscreen GUI tests.
- `configs/`: generated/configuration-related C sources.
- `docs/`: Bluetooth Channel Sounding references and project technical notes.
- `implementation_plan.md`: current implementation status and design record.

## Tools and getting started

- Firmware: install NCS v3.4.1 and its matching toolchain; use the NCS terminal
  with `west`, CMake, and the installed J-Link support. Build from the workspace
  root using the board target documented by the relevant app. Keep build output
  under the app directory or another ignored/out-of-tree location.
- Host app: from the workspace root, install and launch with
  `.venv/bin/python -m pip install -e ./python` and `ble-channel-sounding`. Use
  `ble-channel-sounding --simulate` to explore without hardware.
- Main hosted route: flash `cs_client` to an nRF54LM20 DK, connect its native
  USB CDC ACM host port to `ble-channel-sounding`, and pair over Bluetooth with a reflector.
- Hostless route: use `cs_hostless_initiator` and `cs_hostless_reflector` with
  the configuration compiled into their firmware; the initiator streams reports
  over USB CDC ACM. The Tag uses RTT through an SWD probe for logs.

For the full procedure and example commands, read [Getting Started](docs/GETTING_STARTED.md)
before preparing a hardware setup. For the board matrix, see [README.md](README.md).

Read the nearest component README before changing behavior. The protocol and
wire-format contract is documented in `common/libs/cs_protocol/README.md`; the
configuration record and validation contract is in
`common/libs/cs_utils/README.md`.

Project-authored software is MIT; project-authored documentation is CC BY 4.0.
Preserve third-party licenses and notices when copying code or redistributing
firmware. See `LICENSING.md` for the Zephyr and nRF Connect SDK boundary.

## Working conventions

- Preserve existing user changes. Do not use destructive commands such as
  `git reset --hard` or `git checkout --` to clean the worktree.
- Keep changes narrowly scoped. Do not edit build directories, `.cache`
  directories, virtual environments, recordings, or generated compile
  databases unless the task explicitly requires it.
- For firmware changes, keep shared behavior in `common/libs/` and keep
  application-specific wiring/configuration in the relevant application
  directory.
- Keep the C and Python protocol implementations synchronized. Changes to
  `common/libs/cs_protocol/cs_protocol_packets.h` normally require matching
  updates in `python/ble_channel_sounding/protocol/` and the relevant tests.
- Treat packed record sizes, enum values, field order, CRC ordering, and
  protocol versioning as compatibility-sensitive. Update both native C and
  Python tests when changing them.
- Use the existing `cs_*_config_set_*()` validation helpers instead of writing
  parallel validation logic in applications.
- Do not claim hardware or RF behavior has been verified from a successful
  firmware build; hardware verification requires the board, peer, and logging
  setup described by the component README.

## Python setup and tests

Run Python commands from `python/` so package imports and test discovery match
the repository layout. The workspace includes a Python virtual environment at
`.venv/`; use `.venv/bin/python` from the repository root (or
`../.venv/bin/python` from
`python/`); it contains the optional Qt and HDF5 test dependencies.

Install the editable package when dependencies are not already installed:

```sh
cd python
../.venv/bin/python -m pip install -e .
```

Run the full Python test suite, including offscreen Qt tests where available:

```sh
cd python
QT_QPA_PLATFORM=offscreen ../.venv/bin/python -m unittest discover -s tests -v
```

For a focused test, use the same working directory, for example:

```sh
cd python
../.venv/bin/python -m unittest tests.test_protocol -v
```

GUI tests may be skipped if PyQt6/pyqtgraph are unavailable. Logic outside
`views/`, `app.py`, `qt_session.py`, and serial transport is intended to remain
Qt-free and should be covered by non-GUI unit tests.

## Firmware builds

Use an activated Nordic Connect SDK terminal with a compatible NCS/Zephyr
installation. Build directories should remain outside tracked source files or
use the component-specific `build/` path already documented by that component.

Typical application builds from the repository root are:

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_client
west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_hostless_initiator
west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_hostless_reflector
west build --no-sysbuild -b nrf54l15tag/nrf54l15/cpuapp \
  -d cs_reflector_tag/build cs_reflector_tag
```

Use `west flash -d <build-directory>` only when hardware flashing is
explicitly needed. Check the application README for board names, planner
configuration exports, overlays, and serial/RTT requirements before flashing.

## Native C tests

Several native tests are executable directly from the repository root:

```sh
tests/app_log/run.sh
tests/cs_generated_config/run.sh
tests/cs_roles/run.sh
tests/host_link/run.sh
```

The CS utility tests use the real Zephyr headers and require `ZEPHYR_BASE` to
point to the NCS Zephyr directory:

```sh
ZEPHYR_BASE=/path/to/ncs/zephyr tests/cs_utils/run.sh
```

Firmware test applications under `tests/` are built with `west` according to
their individual README files; they are not all host-native tests.

## Change verification

After modifying Python logic, run the narrowest affected tests first and then
the full Python suite when practical. After modifying shared C libraries or
protocol structures, run all applicable native scripts and at least one
representative firmware build. For firmware-only configuration or board
changes, build the affected application and inspect the generated Kconfig and
device-tree output when the change touches them.

Before handing off, review `git diff` and `git status --short`. Do not include
unrelated pre-existing modifications in the change summary.
