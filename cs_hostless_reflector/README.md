# CS hostless reflector

A CS reflector for a board with no host connection. It
advertises with the Ranging Service UUID, accepts one initiator, encrypts the
link and runs the reflector role of `common/libs/cs_roles`. After a lost link
or a failed setup it advertises again. Output is log messages only: no USB, no
host link, no protocol frames.

## Configuration

The configuration comes from a planner export (`cs_generated_config.h`, see
`python/cs_app`):

- `config/cs_generated_config.c`, compiled when it exists; or
- `-DCS_CONFIG_SOURCE=<path>.c` (with or without sysbuild).

Without an export the weak default in `common/libs/cs_generated_config` is
linked: the application logs a warning and runs the `cs_utils` default
reflector configuration with the procedure parameters of the hostless
initiator (one 16 ms subevent in a 17.5 ms procedure every 3 ACL events). A generated configuration that a setter rejects is
logged and the application halts with no radio activity. A generated device
name is applied before advertising.

The reflector is always the GAP peripheral. Connection parameters are chosen by
the initiator (GAP central).

## Build

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_hostless_reflector
west build -b nrf54lm20dk/nrf54lm20b/cpuapp cs_hostless_reflector -- \
    -DCS_CONFIG_SOURCE=/path/to/cs_generated_config.c
west build -b nrf54l15dk/nrf54l15/cpuapp cs_hostless_reflector
west build -b nrf54l15tag/nrf54l15/cpuapp cs_hostless_reflector
```

| Board | Output | Antennas |
| --- | --- | --- |
| nRF54LM20 DK | Debug UART | 1 |
| nRF54L15 DK (`boards/`) | Debug UART at 921600 baud; no USB, no RTT | 1 |
| nRF54L15 Tag (`boards/`) | RTT (SWD probe); deferred, drops without a viewer | 2, SKY13348 switch as in `cs_reflector_tag` |

The image contains the Ranging Service responder only
(`CONFIG_APP_CS_ROLES_REFLECTOR`, `CONFIG_BT_CTLR_SDC_CS_ROLE_REFLECTOR_ONLY`),
with automatic RRSP instance allocation.

## Log output

The log (`common/libs/app_log`) goes to the console: the debug UART on the DKs, RTT on
the Tag. The planner export sets the console level (`cs_generated_config_log()`, info
without an export); its protocol level has no effect, since the image has no host
link.

- Every state change (advertising, connected, encrypted, waiting for the
  initiator, running, stopped, link lost, error with failure stage, HCI status
  and error).
- The initiator's configuration and each procedure enable/disable.
- Every `CONFIG_CS_HOSTLESS_STATS_INTERVAL_S` seconds (default 10): completed
  procedures, subevents, aborted and partial subevents, steps. Subevents are
  counted from their headers; steps are not decoded.

When the initiator stops the procedures the reflector logs `stopped` (stop
reason peer) and waits for the next run on the same link.

## Status

Builds for all three boards. Run on hardware on the nRF54L15 DK with
`cs_hostless_initiator` on an nRF54LM20 DK (2026-09-19: step timings and T_PM,
8 procedures/s without aborts). The nRF54LM20 DK and Tag builds are not yet run
on hardware.
