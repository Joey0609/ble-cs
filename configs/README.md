# Stored CS configurations

C configuration sources that can be compiled into the hostless and Tag
firmware instead of their built-in defaults. Each file implements
`common/libs/cs_generated_config/cs_generated_config.h` for one CS role, in the
format the planner's *Export C configuration…* writes. Nothing here is built
unless a build names it.

| File | Role | Summary |
| --- | --- | --- |
| [initiator_mode3_a1b2_2m_sub16ms_ras_cstag.c](initiator_mode3_a1b2_2m_sub16ms_ras_cstag.c) | Initiator | Mode 3, two antenna paths, 2M PHY, one 16 ms subevent per procedure, RAS real-time, connects to `CSTag` reflectors |
| [reflector_a1b1_sub5ms.c](reflector_a1b1_sub5ms.c) | Reflector | One antenna path, 5 ms subevents |

The two files are not a matched pair: they differ in antenna paths and
subevent length. The initiator file is meant for a Tag reflector running its
own `TEST_*` defaults (A1:B2).

## File names

```
<role>[_mode<N>]_a<A>b<B>[_<phy>]_sub<length>ms[_<reflector data>][_<peer>].c
```

| Part | Meaning | Record field |
| --- | --- | --- |
| `initiator`, `reflector` | CS role the file configures | `cs_generated_config_<role>()` |
| `mode<N>` | CS main mode. Initiator only: the reflector receives the mode from the initiator | `creation.mode` |
| `a<A>b<B>` | Tone antenna configuration, A initiator antennas and B reflector antennas (`a1b2` is two antenna paths) | `procedure.tone_antenna_config_selection` |
| `1m`, `2m` | CS_SYNC PHY. Initiator only: the reflector receives it from the initiator. Not `procedure.phy`, which only sets the reference for the TX power delta | `creation.cs_sync_phy` |
| `sub<length>ms` | Subevent length | `procedure.min_subevent_len`, `max_subevent_len` |
| `ras`, `noras` | Reflector data: RAS real-time, or none (initiator only, needs IPT). Initiator only | `cs_initiator_config_set_peer_data()` |
| `<peer>` | Lower-case name pattern the initiator scans for. Initiator only; left out when the file has no patterns | `cs_generated_config_patterns()` |

The name states what tells one configuration from another. Everything else is
in the tables below and in the file.

## initiator_mode3_a1b2_2m_sub16ms_ras_cstag.c

For `cs_hostless_initiator` on an nRF54LM20 DK, with `cs_reflector_tag` as the
peer. Hand-written on 2026-09-24 for the stack high-water-mark measurement: it
is the heaviest configuration this pair of boards runs. The header comment of
the file gives the reason for each value and the values the controller
rejected; `implementation_plan.md` §15 has the results.

| Property | Value |
| --- | --- |
| Peer | First connectable device whose name starts with `CSTag` |
| Connection interval | 30 ms, fixed; latency 0, supervision timeout 4 s |
| Main mode | Mode 3 (RTT and tones in every step), no sub-mode |
| RTT type | Access address only |
| Mode-0 steps | 3 |
| Antenna paths | A1:B2, one initiator antenna and both Tag antennas; preferred peer antennas 1 and 2 |
| PHY | CS_SYNC PHY 2M; reference PHY for the TX power delta 2M |
| Channels | All 72, map repeated once, channel selection 3b |
| Subevent | 16 ms, one per procedure (`max_procedure_len` 26, 16.25 ms) |
| Procedure interval | 2 to 4 connection events, unlimited procedures |
| T_PM | 10 µs |
| IPT | Requested |
| Reflector data | RAS real-time |
| TX power | At most 20 dBm, no power delta, SNR control not used |
| Log levels | Console info, host (USB) debug |
| Boot line value | `0x5A6F0001`, a hand-written marker and not a CRC over the record |

The reflector needs two antennas, so the peer is a Tag. `cs_reflector_tag`
without an export already requests A1:B2 and advertises as `CSTag`.

Run on hardware on 2026-09-24 with that pair: 114 steps per procedure, 16.7
procedures/s, no aborted or partial subevents, and RAS data lost for about
1.5% of procedures (`implementation_plan.md` §15.3).

The planner plan embedded at the end of the file was updated by hand and was
not produced by the planner, and the planner cannot open this file. The C
record above it is what runs.

## reflector_a1b1_sub5ms.c

Planner export of 2026-09-15 (ble-channel-sounding 0.1.0) for a reflector with
one antenna: `cs_hostless_reflector`, or `cs_reflector_tag` using one of its
two antennas. CRC-32 `0x03e36c1c`.

| Property | Value |
| --- | --- |
| Connection interval | 7.5 to 62.5 ms accepted; latency 0, supervision timeout 4 s. The initiator chooses the interval |
| Antenna paths | A1:B1; preferred peer antenna 1 |
| Subevent | 5 ms |
| Reference PHY | 1M, for the TX power delta only |
| Procedure | At most 10 ms (`max_procedure_len` 16), every connection event, unlimited procedures |
| TX power | At most 20 dBm, no power delta, SNR control not used |
| Name patterns | None; a reflector does not scan |
| Device name | None; the application's default name is advertised |
| Log levels | Not set; the firmware defaults apply |

A reflector record holds only its local settings. The mode, RTT type, channel
map and IPT come from the initiator when it creates the CS configuration. The
plan this file was exported from, embedded at the end of the file, was mode 2
with IPT, all 72 channels, CS_SYNC PHY 2M, 2 mode-0 steps and three 5 ms
subevents per event on a 25 ms connection interval. An initiator paired with
this reflector should request A1:B1.

No hardware run is recorded for this export.

## Building with a configuration

Name the file with `-DCS_CONFIG_SOURCE`. A relative path is resolved against
the application directory:

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp \
  -d cs_hostless_initiator/build cs_hostless_initiator -- \
  -DCS_CONFIG_SOURCE=../configs/initiator_mode3_a1b2_2m_sub16ms_ras_cstag.c

west build -b nrf54lm20dk/nrf54lm20b/cpuapp \
  -d cs_hostless_reflector/build cs_hostless_reflector -- \
  -DCS_CONFIG_SOURCE=../configs/reflector_a1b1_sub5ms.c
```

The CMake output names the linked file (`Planner configuration: ...`). The
value is cached in the build directory: pass `-DCS_CONFIG_SOURCE=` or build
pristine to return to the application's defaults. Alternatively copy a file to
`<application>/config/cs_generated_config.c`, which is compiled whenever it
exists.

At boot the firmware logs `Planner configuration, CRC-32 0x...` with the value
from the file. A record that a `cs_*_config_set_*()` helper rejects halts the
application with no radio activity. See the application READMEs for the
details:
[cs_hostless_initiator](../cs_hostless_initiator/README.md),
[cs_hostless_reflector](../cs_hostless_reflector/README.md),
[cs_reflector_tag](../cs_reflector_tag/README.md).

## Adding a configuration

The planner writes `cs_generated_config.c`, or `cs_generated_config_initiator.c`
and `cs_generated_config_reflector.c` when both roles are exported. Rename the
export after its properties as described above before adding it here, set the
`Configuration name:` line in its header to the same name, and add it to the
table and a section to this file. To see or change the plan of a planner
export, open the file in the planner from the `python` directory:

```sh
python -m ble_channel_sounding_planner ../configs/reflector_a1b1_sub5ms.c
```

Plans saved as JSON are in [python/configs](../python/configs/README.md).
