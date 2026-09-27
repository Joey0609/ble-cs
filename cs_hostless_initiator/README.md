# CS hostless initiator

A CS initiator with no command host. It scans for a
reflector, connects, encrypts the link and runs the initiator role
of `common/libs/cs_roles`: RAS discovery and real-time subscription (unless
the configuration selects reflector data none), capabilities, FAE table, configuration, CS security and procedures. After a
lost link or a failed setup it scans again. CS reports use the existing binary
protocol on a report-only USB CDC ACM port; the host command link is never
initialized.

## Peer selection

- With name patterns in the planner export (`cs_generated_config_patterns()`),
  the first connectable device whose advertised name starts with a pattern.
- Without patterns, the first connectable device advertising the Ranging
  Service UUID.

The initiator is always the GAP central and requests the configuration's
connection parameters.

## Configuration

`config/cs_generated_config.c` when it exists, or `-DCS_CONFIG_SOURCE=<path>.c`.
The application checks for the generated export before starting Bluetooth. If
none is linked, it initializes the library record and overwrites it with the
hostless application's explicit defaults (including the `CSTag`
scan prefix, matching every Tag reflector); a rejected configuration halts the application with no radio
activity. The fallback selects all 72 usable CS channels, unlimited
procedures, a 17.5 ms ACL interval and mode 2 only: each procedure is one
16 ms subevent in one ACL event (72 PBR steps and one mode-0 step), and
procedures repeat every 3 ACL events (52.5 ms) so the two events in between
carry the reflector's RAS real-time data. With only one event in between, the
reflector sometimes misses it and the late RAS traffic aborts the next
procedure. The ATT MTU is exchanged on connection so
that data fits in that one event. Generated configuration values remain
authoritative when present.

The fallback prefers reflector antennas 1 and 2 (`preferred_peer_antenna` 3),
the two Tag antennas. `cs_*_config_set_procedure()` rejects a mask with fewer
bits than the tone antenna configuration's reflector antennas, so an export
with A1:B2 needs 3 as well. A bit above the reflector's reported antenna count
(for example 4, antenna 3, on the two-antenna Tag) is not sent: the setup fails
at remote capabilities, the application logs an error, disconnects and stops,
as for a missing IPT below. The Tag's controller would switch to that antenna
unchecked and fault on the missing antenna GPIO.

### Preferred T_PM

A planner export can select a preferred T_PM of 20 or 40 µs
(`cs_initiator_config_set_t_pm()`); the default is 10 µs. It goes to the
controller before each configuration is created. Boot logs it with the
reflector data setting, and each `CS configuration` log line shows the T_PM in
use: a reflector without support for it gets one both devices support.

### Reflector data

A planner export with IPT requested can select reflector data none
(`cs_initiator_config_set_peer_data(config, CS_CONFIG_PEER_DATA_NONE)`). The
initiator then skips RAS discovery and subscription and reports only its own
subevents; the IPT phase carries the two-way phase. Without the RAS
notifications between procedures, the procedure interval can drop to 1 ACL event:
17.5 ms per procedure instead of 52.5 ms with the fallback timing. The fallback
defaults keep RAS real-time, mode 2 and no IPT.

- Boot logs the reflector data setting with the configuration CRC. An export
  that selects none without IPT is rejected at boot like any other invalid
  export.
- `CS_PEER_DATA` follows each successful `CS_CONFIGURATION` on USB CDC and is
  resent with the cached link records when the host opens the port, so a host
  that connects later knows that no reflector subevents will come.
- If the Tag does not support IPT in the reflector, or the created
  configuration does not enable it, the application logs an error, disconnects
  and stops: no automatic reconnection, no radio activity until reset.
- The periodic statistics leave out the RAS subevent and RAS data lost
  counters.

## Build

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_hostless_initiator
west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_hostless_initiator -- \
    -DCS_CONFIG_SOURCE=/path/to/cs_generated_config.c
```

The image contains the Ranging Service requestor only
(`CONFIG_APP_CS_ROLES_INITIATOR`, `CONFIG_BT_CTLR_SDC_CS_ROLE_INITIATOR_ONLY`).

USB CDC carries binary protocol configuration, negotiated ACL connection
parameters, capabilities, FAE, procedure, subevent, and completion reports.
Reports are discarded while DTR is low, but scanning and ranging continue
regardless of USB state. The latest interval, latency, supervision timeout and
ATT MTU are cached and resent when the host opens USB.

## Log output

The log (`common/libs/app_log`) goes to the debug UART and, as `LOG_MESSAGE` frames, to
USB CDC, where `cs-app` in hostless mode shows it with the reports. The planner export
sets both levels (`cs_generated_config_log()`), applied at boot before Bluetooth starts;
without an export they are info on the UART and warning on USB.

At info:

- Every state change, including a completed `max_procedure_count`.
- The configuration, capabilities, each procedure enable/disable, FAE table,
  and every decoded local/reflector subevent are written to USB CDC as reports.
- Every `CONFIG_CS_HOSTLESS_STATS_INTERVAL_S` seconds (default 10): completed
  procedures, local and RAS subevents, aborted and partial subevents, steps and
  RAS data lost (without RAS: procedures, subevents, aborted and partial
  subevents, steps). Subevents are counted from their headers; steps are not decoded.

At debug, also one line per subevent header (role, event, subevent, procedure,
steps, status). Logged from Bluetooth context at every subevent, it can fill the
log queue at short procedure intervals; dropped messages are counted in one warning.

## Status

Builds for the nRF54LM20 DK; not yet run on hardware.
