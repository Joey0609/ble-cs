# Stored planner configurations

Planner JSON configurations saved from the CS view of `ble-channel-sounding`
with **Save…** (schema version 1), plus copies of the C examples in the
repository-root `configs/` directory. Each JSON file holds the scenario
(connection, CS configuration, procedure) and the Host settings, so it is a
complete configuration. Load one with **Open…** in the CS view, or in the
standalone planner from the `python` directory:

```sh
python -m ble_channel_sounding_planner configs/cs-plan-initiator-mode3-a1b1-2m-sub25ms-ras.json
```

**Open…** starts in this directory in a source checkout. Installed host and
planner packages include the JSON and C examples with this README in their
bundled `configs/` directory, which **Open…** uses after installation.

## C examples copied from the repository root

These files are unchanged copies of the firmware examples in `configs/` at
the repository root. C files open through the embedded planner JSON; the
applications do not interpret their C setter calls.

| File | Role | Summary | Planner import |
| --- | --- | --- | --- |
| [initiator_mode3_a1b2_2m_sub16ms_ras_cstag.c](initiator_mode3_a1b2_2m_sub16ms_ras_cstag.c) | Initiator | Mode 3, A1:B2, 2M PHY, one 16 ms subevent, RAS real-time, `CSTag` peers | Does not open: its hand-written embedded plan is not valid planner input |
| [reflector_a1b1_sub5ms.c](reflector_a1b1_sub5ms.c) | Reflector | A1:B1, 5 ms subevents | Opens in the standalone planner; the integrated host supports initiator configurations only |

The files are not a matched pair: their antenna paths and subevent lengths
differ. The initiator example is intended for a Tag reflector running A1:B2
defaults. Its C record is the firmware configuration; the hand-written
embedded plan is only an approximation and has explanatory text before its
JSON that the importer cannot parse.

For firmware settings and build commands in a source checkout, see
[the root configurations README](../../configs/README.md). When a root C
example changes, copy it here again so the installed examples stay in sync.

## File names

```
cs-plan-<role>-mode<N>-a<A>b<B>-<phy>-sub[<count>x]<length>ms-<reflector data>.json
```

| Part | Meaning | JSON field |
| --- | --- | --- |
| `initiator` | Operation mode of the plan | `configuration.role` |
| `mode<N>` | CS main mode: 2 is PBR, 3 is RTT and PBR in every step | `configuration.mode` |
| `a<A>b<B>` | Tone antenna configuration, A initiator antennas and B reflector antennas (`a1b2` is two antenna paths) | `procedure.tone_antenna_config_selection` |
| `1m`, `2m` | CS_SYNC PHY. Not the reference PHY of the Host settings, which only sets the reference for the TX power delta | `configuration.cs_sync_phy` |
| `sub<length>ms` | Subevent length; `sub2x16ms` is two 16 ms subevents per CS event | `procedure.subevent_len`, `subevents_per_event` |
| `ras`, `noras` | Reflector data: RAS real-time, or none (initiator only, which needs IPT) | `host_settings.peer_data` |

The name states what tells one plan from another. The tables below have the
rest.

## Plans

All five use all 72 channels with channel selection 3b, two mode-0 steps, no
sub-mode, unlimited procedures, and a 4 s supervision timeout. The mode-3 plans
time RTT from the access address only.

| File | Mode | Antennas | Subevents per event | Reflector data | IPT | Loads |
| --- | --- | --- | --- | --- | --- | --- |
| `cs-plan-initiator-mode2-a1b1-2m-sub37ms-ras.json` | 2 | A1:B1 | 1 × 37 ms | RAS real-time | Off | No, see below |
| `cs-plan-initiator-mode2-a1b2-2m-sub2x16ms-ras.json` | 2 | A1:B2 | 2 × 16 ms | RAS real-time | Off | Yes, incomplete schedule, see below |
| `cs-plan-initiator-mode2-a1b1-2m-sub20ms-noras.json` | 2 | A1:B1 | 1 × 20 ms | None | Requested | Yes |
| `cs-plan-initiator-mode3-a1b1-2m-sub25ms-noras.json` | 3 | A1:B1 | 1 × 25 ms | None | Requested | Yes |
| `cs-plan-initiator-mode3-a1b1-2m-sub25ms-ras.json` | 3 | A1:B1 | 1 × 25 ms | RAS real-time | Off | Yes |

Timing, in the same order (`sub37ms`, `sub2x16ms`, `sub20ms`, `sub25ms-noras`,
`sub25ms-ras`):

| Plan | Connection interval | Procedure interval | Maximum procedure length | T_IP1 / T_IP2 / T_FCS / T_PM | ATT MTU |
| --- | --- | --- | --- | --- | --- |
| `sub37ms` | 37.5 ms | 2 events, 75 ms | 41.25 ms | 30 / 20 / 60 / 40 µs | 498 |
| `sub2x16ms` | 56.25 ms (50 to 56.25 requested) | 2 events, 112.5 ms | 16.25 ms | 145 / 145 / 150 / 40 µs | 23 |
| `sub20ms` | 25 ms | 1 event, 25 ms | 20 ms | 30 / 20 / 60 / 40 µs | 498 |
| `sub25ms-noras` | 35 ms | 2 events, 70 ms | 24.375 ms | 30 / 20 / 60 / 10 µs | 498 |
| `sub25ms-ras` | 42.5 ms | 2 events, 85 ms | 25 ms | 30 / 20 / 60 / 10 µs | 498 |

Host settings:

| Plan | Peer name patterns | Preferred peer antennas | Reference PHY | Maximum TX power | TX power delta | Device name | Source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `sub37ms` | `CSTag` | 1 | 1M | 20 dBm | -121 dB | None | Client report |
| `sub2x16ms` | `CSTag` | 1 and 2 | 1M | 20 dBm | -121 dB | `CSInitiator` | Planner only |
| `sub20ms` | `CS` | 2 | 2M | 15 dBm | None | None | Client report |
| `sub25ms-noras` | `CS` | 1 | 2M | 15 dBm | None | None | Planner only |
| `sub25ms-ras` | `CS` | 1 | 2M | 15 dBm | None | `CSClient` | Client report |

The pattern `CSTag` matches only Tag reflectors. `CS` also matches
`cs_hostless_reflector`, which advertises as `CSReflector` followed by its
address. The A1:B2 plan needs a reflector with two antennas, which is the Tag.

"Client report" means the plan was saved after a client reported its
configuration, so the controller fields are the reported ones and the file
keeps the requested record and the record with the reported values
(`_requested_wire`, `_negotiated_wire`). "Planner only" plans were never applied. Neither says that
the plan was run on hardware: the built-in simulator reports a configuration
too.

In two plans the reported subevent length is shorter than the requested one,
and the name states the reported length:

- `sub20ms`: 24 ms requested, 20 ms reported.
- `sub25ms-ras`: 40 ms requested, 25 ms reported.

## Plans that need attention

**`cs-plan-initiator-mode2-a1b1-2m-sub37ms-ras.json` does not open.** The
planner now requires a CS event to be at least 1000 µs shorter than the
connection interval, because the controller refuses the procedure start
otherwise, and this plan puts a 37 ms subevent in a 37.5 ms interval. It was
saved before that check existed. A subevent of at most 36.5 ms, or a connection
interval of at least 38.75 ms (31 × 1.25 ms), passes the check.

**`cs-plan-initiator-mode2-a1b2-2m-sub2x16ms-ras.json` opens but its schedule
is incomplete.** The maximum procedure length (16.25 ms) ends the procedure
before the second subevent, which starts 38.125 ms after the first. The planner
predicts one subevent with 27 of the 72 main-mode steps. A maximum procedure
length of 40 ms (64 × 0.625 ms) or more lets the procedure go on.

The other three plans open without errors and the planner predicts all 72
main-mode steps in one subevent: 19.0 ms for `sub20ms` and 15.5 ms for the two
mode-3 plans.

## Adding a plan

**Save…** suggests `cs-plan.json`. Rename the file after its properties as
described above, and add a row to each table.
