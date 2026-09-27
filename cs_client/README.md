# CS client

> **Work in progress:** the radio-test build is still being developed and has
> not been verified on hardware. This status applies to the radio-test build;
> it is disabled in the desktop application's mode selector and is not for
> deployment. See the Bluetooth build status below for its separate scope.

The firmware the `ble-channel-sounding` host talks to: a CS protocol client
(`common/libs/host_link`) on USB CDC ACM in the Bluetooth build and on uart30 in
the radio test build. The host connects, applies a configuration, and starts
and stops the client (`common/libs/cs_protocol/README.md`). Its log
(`common/libs/app_log`) goes to the debug UART (uart20, 921600 baud), never mixed with
the protocol stream, and as `LOG_MESSAGE` frames to the host. `SET_LOG_CONFIG` sets
both levels at `APPLY_CONFIG`; the defaults are info on the UART and warning to the
host.

## Builds

One source tree, two builds, because the radio test driver cannot share the
radio with the Bluetooth stack:

| Build | Command | `supported_modes` | Host port | Configuration |
| --- | --- | --- | --- | --- |
| Bluetooth | `west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_client` | CS initiator, CS reflector | USB CDC ACM (nRF USB connector) | `prj.conf` + `common.conf`, `app.overlay` |
| Radio test | `west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_client -- -DFILE_SUFFIX=radio_test` | Radio test | uart30, 921600 baud, hardware flow control (DK virtual COM port) | `prj_radio_test.conf` + `common.conf`, `app_radio_test.overlay` |

`FILE_SUFFIX` makes Zephyr use `prj_radio_test.conf` and `app_radio_test.overlay`
instead of `prj.conf` and `app.overlay`; `CMakeLists.txt` adds `common.conf` (host
link, logging) to both. Bluetooth and USB settings live only in `prj.conf`, so the
radio test build has no Bluetooth Kconfig assignments to warn about and needs no USB
device controller.

The radio test build's host port has no DTR, so a closed port does not end the host
session: `ble-channel-sounding` ends it with `CLOSE_SESSION`, and if the host disappears without
it, the test keeps running and the next `CONNECT` attaches to it.

| File | Content |
| --- | --- |
| `prj.conf` | Bluetooth: central + peripheral, CS with both SoftDevice Controller roles, mode 3, 4 antenna paths, RAS responder (no automatic instance allocation) and requestor, ATT MTU 498 with the exchange started on connection, LL Extended Feature Set for IPT; USB device stack (next) with CDC ACM for the host link |
| `prj_radio_test.conf` | Radio test: no Bluetooth, MPSL or USB, nrfx timer / GPPI, entropy, FEM abstraction headers, interrupt-driven uart30 for the host link |
| `common.conf` | `CONFIG_APP_HOST_LINK` (selects `CONFIG_APP_LOG`), deferred Zephyr logging on uart20, which also carries the `app_log` console through `printk` |
| `app.overlay` | Bluetooth build: `cdc_acm_uart0` on `zephyr_udc0`, chosen as `app,host-link-uart`; uart20 at 921600 |
| `app_radio_test.overlay` | Radio test build: uart30 (921600, hardware flow control) chosen as `app,host-link-uart`; uart20 at 921600 |
| `Kconfig` | Sources `common/libs/Kconfig`; `RADIO_TEST_RX_TIMEOUT` for the NCS radio test driver |
| `VERSION` | Reported as `firmware_version` = `APPVERSION` (`0xMMmmpp00`, e.g. 0.1.0 = `0x00010000`) |

## Sources

| File | Responsibility |
| --- | --- |
| `src/main.c` | Session init, `host_link_init()` with the session's handler table |
| `src/client_state.c/.h` | Client state and applied mode; every change is reported as `CLIENT_STATE`, and one with an error that had no session is reported again after the next `CONNECT` |
| `src/session.h` | Interface implemented by the build's session |
| `src/radio_session.c` | Radio test build: validate / apply / start / stop through `radio_test_utils`; a finished finite test reports `CLIENT_STATE(STOPPED, TEST_COMPLETE)`; `STOP` before it finishes, `CLOSE_SESSION` while running reports `CLIENT_STATE(STOPPED, INTERRUPTED, -ECANCELED)` (the radio test host port has no DTR, so a closed port is not detected); RX and RX sweep tests send `RADIO_TEST_STATS` (baseline after the `START` response, every `CONFIG_CS_CLIENT_RADIO_TEST_STATS_INTERVAL_MS`, final before `STOPPED`) |
| `src/cs_session.c` | Bluetooth build: validates/applies CS configurations and connects host-link commands and reports to `cs_roles`. Stop reasons map to `CLIENT_STATE(STOPPED)`: completed `max_procedure_count` → `TEST_COMPLETE`; `STOP` → `INTERRUPTED, -ECANCELED`; a reflector stopped by its initiator → `INTERRUPTED, -ECONNABORTED` (it then reports `RAS_READY` and waits for the next run). An initiator `STOP` whose last RAS data does not arrive answers `OK` with reason `STOP_TIMEOUT` after `RAS_DATA_LOST`. The initiator applies `SET_PEER_DATA` with the configuration and sends `CS_PEER_DATA` after each successful `CS_CONFIGURATION`; with reflector data none it skips RAS (no `RAS_READY`, no reflector subevents, no `STOP_TIMEOUT`), and a peer or configuration without IPT ends in `CLIENT_STATE(ERROR, PEER_IPT_UNSUPPORTED)`. A `preferred_peer_antenna` bit above the reflector's reported antenna count ends the setup at remote capabilities in `CLIENT_STATE(ERROR, CS_CONFIG_FAILED, -ERANGE)`, before any procedure could make the reflector switch to an antenna it lacks. `SET_T_PM` (20 or 40 µs, 10 without it) goes to the controller before every CS configuration is created; `CS_CONFIGURATION` reports the T_PM in use |
| `src/peer_discovery.c/.h` | Bluetooth build: discovery commands → `cs_role_link_*`, scan reports → `SCAN_RESULT` |

The Bluetooth session caches the negotiated ACL interval, latency, supervision
timeout and ATT MTU from `cs_roles` and sends them as `CONNECTION_PARAMETERS`
when the USB host session opens and when either negotiated value changes.

## Status

- Radio test build: complete against the protocol (connect, configure, get
  configuration, start, stop, test completion). Not yet run on hardware.
- Bluetooth build: host connect/configure/get, scan reports with peer names, explicit
  selected-peer connection, advertising with the configured name, L2 security and
  failure reports. `STOP` cancels discovery; `LINK_DISCONNECT` cancels/disconnects, and
  stops running procedures first, so the host sends no `STOP` before it.
  Measurement `START` runs the configured initiator or reflector role on the selected peer.
  Discovery runs independently through SCAN_START / ADVERTISE_START / PEER_CONNECT.

The boot state is `IDLE` with no radio activity; discovery requires
`APPLY_CONFIG` followed by an explicit discovery command. `CLOSE_SESSION`, or a
dropped USB port in the Bluetooth build, interrupts a running operation, stops
scanning, advertising or a connection attempt, and cancels a CS setup, but keeps
the applied configuration, configured device name and established Bluetooth link.
The next `CONNECT` reports that configuration and state, followed by an
interruption the previous host session could not receive.

### Board antenna count

`CONNECT_RESPONSE.num_antennas_supported` reports
`CONFIG_APP_HOST_LINK_NUM_ANTENNAS` from the compiled configuration. It defaults
to `CONFIG_BT_CTLR_SDC_CS_NUM_ANTENNAS` for Bluetooth builds and 1 for radio-only
builds. Set it in the board `.conf` for a radio-only board with multiple antennas.
Python displays this count in the serial connection details immediately after
connecting. This is the local antenna count, separate from the maximum number
of antenna paths. Firmware and Python must both use the current protocol version.

See `common/libs/cs_protocol/README.md` → Peer discovery for wire details, timing,
selection, cancellation and failure behavior. `src/peer_discovery.c/.h` converts
discovery commands to `cs_role_scan_start()` / `cs_role_link_start()` /
`cs_role_link_disconnect()` and scan reports to `SCAN_RESULT` frames; scanning,
advertising, connection and link encryption live in `common/libs/cs_roles`
(`cs_role_link.c`), shared with the hostless applications.
