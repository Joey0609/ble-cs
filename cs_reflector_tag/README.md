# nRF54L15 Tag CS reflector

Connected Bluetooth Channel Sounding reflector for
`nrf54l15tag/nrf54l15/cpuapp`, using both on-board antennas and the Ranging
Service (RAS) responder. It advertises as **CSTag** (or the name of a linked
planner export) with spaces removed and its identity address appended as 12
upper-case hex digits, most significant byte first, for example
`CSTagC3A1B2D4E5F6`, so Tags built from one image have different names.

Connection, CS and RAS sequencing is the shared `common/libs/cs_roles` library
(`CONFIG_APP_CS_ROLES_REFLECTOR`), as in `cs_hostless_reflector` and
`cs_client`: the role thread owns the link and role state, control events are
never dropped, and a lost or failed link is restarted after
`CONFIG_APP_CS_ROLES_LINK_RESTART_DELAY_MS`. The application keeps the Tag
specifics: the unique name, the antenna checks against the controller and the
configuration dump at boot. After five consecutive link failures in a row it
cold-reboots rather than going silent, since it has no button to recover it.
Logs use RTT through an external SWD probe; the Tag has no native USB. Ranging
data is delivered to the initiator over RAS.

The RGB LED 1 shows the state: blue is on while connected, and green is on
while CS procedures are running (both lit read as cyan). Green turns off when
the procedures stop or the role reports an error; both turn off when the link
is lost or disconnected. The red channel and LED 2 are not used.

## Board and antenna switch

The wiring follows the installed NCS v3.4.1 Tag board definition and
`nrf/samples/bluetooth/channel_sounding/ras_reflector/boards/nrf54l15tag_nrf54l15_cpuapp.overlay`.
See also the [Nordic antenna specification](https://docs.nordicsemi.com/r/bundle/ug_nrf54l15_tag/page/ug/nrf54l15_tag/antennas.html)
and [Zephyr board documentation](https://docs.zephyrproject.org/latest/boards/nordic/nrf54l15tag/doc/index.html).

| RF switch U6 (SKY13348) | P1.09 / V1 | P1.10 / V2 |
| --- | --- | --- |
| ANT1 | High | Low |
| ANT2 | Low | High |

The board overlay defines `cs_antenna_switch` using
`nordic,bt-cs-antenna-switch`, with active-high GPIOs in ANT1/ANT2 order and
`multiplexing-mode = <0>` (one control line per antenna). It removes the
`sky13348` node and both default antenna GPIO hogs, which otherwise hold ANT1
selected. The SoftDevice Controller owns switching during CS; application
code must not toggle these pins.

The board configuration selects **2 local antennas** and **4 maximum antenna
paths**. The latter supports a two-antenna peer (2 × 2); it does not imply four
physical antennas on the Tag. RAS is also sized for four paths. The controller's
Extended Feature Set is enabled so the reflector can participate in IPT
configurations requested by the initiator.
`CONFIG_BT_CTLR_SDC_CS_NUM_ANTENNAS=2` automatically enables the SDK's multiple
antenna support and GPIO switch callback.

## Stored configuration and peer setup

The configuration comes from one of two sources:

- **Planner export** (`config/cs_generated_config.c` when it exists, or
  `-DCS_CONFIG_SOURCE=<path>.c`, see below): a reflector
  source exported by `ble-channel-sounding`, implementing
  `common/libs/cs_generated_config/cs_generated_config.h`. Its record, and its
  device name when it has one, replace everything below. Boot logs
  `Planner configuration, CRC-32 0x...`, which matches the CRC `ble-channel-sounding` shows
  for the same configuration. Name patterns in the export are ignored: the Tag
  is always a GAP peripheral.
- **`TEST_*` values** in [src/test_cfg.c](src/test_cfg.c), when no export is
  linked. Boot logs `No planner configuration linked: TEST_* values`. The
  application starts from `cs_reflector_config_get_default()` and defines every
  configuration section with the `cs_reflector_config_set_*()` helpers.

Either way a setter rejecting a value stops the application before Bluetooth
starts. The packed record is kept in a static `cs_reflector_config` in RAM and
printed with `cs_reflector_config_print()`, one log message per line. Settings are compiled into the
firmware and reconstructed on boot; there is no flash settings store or runtime
editor.

After `bt_enable()` the application checks that the controller matches the
board configuration (`CONFIG_BT_CTLR_SDC_CS_NUM_ANTENNAS`, `..._MAX_ANTENNA_PATHS`)
and that the record fits it: the tone antenna configuration's reflector
antennas and paths, and a fixed CS_SYNC antenna. A record that does not fit
stops the application before advertising.

`cs_roles` advertises with extended advertising, which carries the whole
configured name; the name is still capped at 22 bytes (10 bytes of base name).
A scanner that does not receive extended advertising reports, such as
`tests/cs_initiator_test`, no longer finds the Tag; `cs_client` and
`cs_hostless_initiator` both scan with `CONFIG_BT_EXT_ADV`.

Once the link is encrypted, `cs_roles` runs the reflector role: RAS responder
instance, local CS defaults and remote capabilities, then the initiator's
configuration, whose actual ID is stored with the setter before the procedure
parameters are applied. The ACL connection parameters are the initiator's
(GAP central): `cs_roles` uses the record's connection section only when it
creates the connection itself, so the Tag no longer sends the parameter update
request the standalone image did. The initiator
creates the shared mode, RTT type and channel map, enables security, and starts
the procedures. When it disables them the Tag logs `stopped` (stop reason peer)
and waits for the next run on the same link.

## Default configuration

A build without a planner export runs the configuration below. The fixed
settings apply to every build; the `TEST_*` values come from
[src/test_cfg.c](src/test_cfg.c) and are replaced by a planner export.

### Fixed settings

These come from [prj.conf](prj.conf), the board files and
[src/main.c](src/main.c), and a planner export does not change them (apart from
the name).

| Setting | Value |
| --- | --- |
| Device name | `CSTag` (`CONFIG_BT_DEVICE_NAME`) + identity address, e.g. `CSTagC3A1B2D4E5F6`; a planner export's name replaces the base, which may be at most 10 bytes without spaces (the build fails for a longer Kconfig name, boot stops for a longer export name) |
| GAP role | Peripheral, one connection (`CONFIG_BT_MAX_CONN=1`) |
| Advertising | Extended, connectable, 100–150 ms (`cs_roles`); flags, RAS UUID and the complete name (at most 22 bytes) |
| After disconnection | `cs_roles` advertises again after `CONFIG_APP_CS_ROLES_LINK_RESTART_DELAY_MS` (1 s); reboots after five consecutive link failures |
| Link encryption | Paired, not bonded (`CONFIG_BT_BONDABLE=n`); CS security needs no stored bond |
| CS role | Reflector only (`CONFIG_BT_CTLR_SDC_CS_ROLE_REFLECTOR_ONLY`) |
| Step modes | Mode 3 supported, so the initiator can choose any mode |
| Antennas | 2 local antennas, up to 4 antenna paths |
| Extended Feature Set | Enabled, so the reflector can take part in IPT |
| Ranging data | RAS responder (RRSP), one connection, one procedure buffer, up to 4 antenna paths |
| ATT MTU / ACL buffers | 498 / 502 bytes, as in the NCS `ras_reflector` sample |
| Status LED | LED 1 blue (P2.09) while connected, LED 1 green (P2.10) while CS procedures run; both off without a link |
| Logs | `app_log` console on RTT, deferred; output is dropped when no viewer keeps up. Level from the planner export (`cs_generated_config_log()`), info without one. Counters every `CONFIG_CS_REFLECTOR_TAG_STATS_INTERVAL_S` seconds (default 5) |

### `TEST_*` values

The initiator creates the shared CS configuration: mode, RTT type, channel map
and step counts. The values below are the reflector's local settings.

| Group | Setting | `TEST_*` macro | Default |
| --- | --- | --- | --- |
| ACL connection (not applied: the initiator chooses) | Interval | `TEST_CONN_INTERVAL_MIN` / `_MAX` | 6–40 (7.5–50 ms) |
| | Peripheral latency | `TEST_CONN_LATENCY` | 0 |
| | Supervision timeout | `TEST_CONN_TIMEOUT` | 400 (4 s) |
| CS configuration | Expected ID | `TEST_CONFIG_ID` | 0; the ID the initiator actually creates replaces it |
| CS default settings | CS_SYNC antenna | `TEST_SYNC_ANTENNA` | Repetitive (`CS_CONFIG_SYNC_ANTENNA_REPETITIVE`) |
| | Maximum TX power | `TEST_MAX_TX_POWER_DBM` | 20 dBm |
| Procedure | Maximum procedure length | `TEST_MAX_PROCEDURE_LEN` | 10 (6.25 ms) |
| | Procedure interval | `TEST_PROCEDURE_INTERVAL_MIN` / `_MAX` | 1–10 ACL events |
| | Procedure count | `TEST_MAX_PROCEDURE_COUNT` | 0 (runs until disabled) |
| | Subevent length | `TEST_SUBEVENT_LEN_MIN_US` / `_MAX_US` | 6–60 ms |
| | Tone antenna configuration | `TEST_TONE_ANTENNA` | **A1:B2** (`CS_CONFIG_TONE_ANTENNA_A1_B2`, index 4) |
| | PHY | `TEST_PHY` | 2M |
| | TX power delta | `TEST_TX_POWER_DELTA` | None (`CS_CONFIG_TX_POWER_DELTA_NONE`) |
| | Preferred peer antennas | `TEST_PEER_ANTENNA` | Antenna 1 (`CS_CONFIG_PEER_ANTENNA_1`), the initiator's antenna |
| | SNR control, initiator / reflector | `TEST_SNR_CONTROL_INITIATOR` / `_REFLECTOR` | Not used |

In A1:B2, A is the initiator and B is this reflector. With these defaults the
Tag uses both of its antennas and one initiator antenna: two antenna paths.
Build-time checks reject a configuration ID above 3 and a minimum above its
maximum; the setters validate the rest at boot.

### Initiator requirements

The initiator must request A1:B2 as well, prefer reflector antennas 1 and 2
(`CS_CONFIG_PEER_ANTENNA_1 | CS_CONFIG_PEER_ANTENNA_2`), and configure its
controller and RAS buffers for at least two paths. In the existing
`cs_initiator_test`, these are edits to `src/test_cfg.c` and `prj.conf`.
A peer left at A1:B1 will not exercise both Tag antennas. For A2:B2, change
both endpoints' procedure selection and peer masks to use two antennas and
allow four paths throughout the initiator's processing chain.

## Build and verify

From an NCS terminal with v3.4.1 (or a compatible SDK containing the Tag
board and CS switch binding), at the repository root:

```sh
west build --no-sysbuild -b nrf54l15tag/nrf54l15/cpuapp \
  -d cs_reflector_tag/build cs_reflector_tag
west flash -d cs_reflector_tag/build
```

To run a planner export, copy it to `cs_reflector_tag/config/cs_generated_config.c`,
which is compiled whenever it exists, or name it on the build command; that works
with and without sysbuild, a relative path is resolved against `cs_reflector_tag/`,
and it takes precedence over `config/`:

```sh
west build --no-sysbuild -b nrf54l15tag/nrf54l15/cpuapp \
  -d cs_reflector_tag/build cs_reflector_tag \
  -- -DCS_CONFIG_SOURCE=/path/to/reflector_config.c
```

The CMake output names the linked export (`Planner configuration: ...`). The
`-DCS_CONFIG_SOURCE` value is cached in the build directory: pass
`-DCS_CONFIG_SOURCE=` or build pristine to return to `config/` or the `TEST_*`
values.

### Build with `CONF_FILE` set, and the antennas disappear

`boards/nrf54l15tag_nrf54l15_cpuapp.conf` is what selects two antennas, four
paths and the Extended Feature Set. Zephyr merges `<app>/boards/*.conf` **only
when `CONF_FILE` is undefined** — in
`zephyr/cmake/modules/configuration_files.cmake` the board lookup sits inside
`if(NOT DEFINED CONF_FILE)`. A build that sets `CONF_FILE` explicitly drops all
three silently. The VS Code nRF Connect extension does set it, so a build
configured there and a build configured with the `west` line above are not the
same image.

The symptom reads as a hardware fault rather than a build one, because the
board *overlay* is passed separately through `DTC_OVERLAY_FILE` and still
applies: the device tree has the `cs_antenna_switch` node while the controller
reports one antenna. The Tag then fails its own capability check and stops
before advertising:

```
nRF54L15 Tag CS reflector: 1 antennas
Controller: 1 antennas, 1 antenna paths
Antenna configuration A1:B2 needs more than 1 antennas, 1 paths
TEST FAIL configuration does not fit the controller
```

Check `nRF54L15 Tag CS reflector: 2 antennas` and
`Controller: 2 antennas, 4 antenna paths` in the boot log before trusting a
run. To confirm from the build directory instead:

```sh
grep -E "CONFIG_BT_CTLR_SDC_CS_(NUM_ANTENNAS|MAX_ANTENNA_PATHS)=" \
  cs_reflector_tag/build/zephyr/.config
```

Step mode 3 and the ATT MTU / buffers of the NCS `ras_reflector` sample are
enabled, so any mode the initiator's configuration selects can run.

Connect an external SWD debug probe and open its RTT viewer. Startup logs the
configuration source, the requested antenna configuration and the controller's
antennas and paths, then every `cs_roles` state change (advertising, connected,
encrypted, waiting for the initiator, running, stopped, link lost, error with
its failure stage). Connect a configured RAS initiator and check that procedure
enablement reports the requested antenna configuration (a different one is
logged as a warning), for the defaults index **4** (A1:B2), followed by an increasing two-path
subevent count and completed procedure count. For A2:B2 the index is **7** and
the four-path count should increase. Investigate any aborted procedures.

Disconnect and reconnect to verify that `cs_roles` restarts advertising and
applies the configuration again. Logs are deferred and drop output if the RTT viewer cannot keep up;
no attached viewer is required for operation. The counters are cumulative
since boot. Hardware ranging and the electrical switch signals require an
on-board test; a successful firmware build alone cannot verify RF behavior.
