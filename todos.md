# Remaining TODOs

Derived from [`implementation_plan.md`](implementation_plan.md), updated 2026-09-24. The step
lists in the plan's own sections are the progress record and win on any disagreement; this file
is a working view of what is open, grouped by the hardware it needs. Completed implementation
and test work is omitted.

## Decisions

- 2026-09-25: The integrated client keeps the CS role fixed to Initiator in every operation mode.
  Reflector mode remains unavailable until it is supported.

## Code work

Added 2026-09-24 from §15, none of it needing hardware either: the stack resize (§10 item 10),
Tag diagnosability — the silent `return 0` from `main()`, a boot reset-cause line, and the
`CONF_FILE` trap in the Tag README (§10 item 11) — and the planner's handling of capabilities
the controller rejects (§9 item 14).

The `host_link` work below is the rest of it. Verifying that on a real link does need
`cs_client`, which is the separate bullet in the blocked list.

- [ ] `end_session()` in `common/libs/host_link/host_link.c` stops clients in scanning,
  advertising, connecting and CS setup, not only during RUNNING (§10 item 9).
- [ ] Remove or adjust the RUNNING `LINK_DISCONNECT` BUSY guard, checking the radio-test
  handler (`cs_client/src/radio_session.c`) for the same assumption.
- [ ] Confirm an interrupt report raised during teardown is delivered on the next session.
- [ ] Add native tests for CLOSE_SESSION in scanning/advertising/setup and LINK_DISCONNECT
  while running.
- [ ] Update the `host_link` README's session-change/end-of-session documentation.

## Runnable now (hostless initiator and Tag are flashed)

- [ ] Confirm `cs_hostless_reflector` on `nrf54lm20dk` reports IPT support (§1.9 step 9). The
  Tag half is done (2026-09-23).
- [x] IPT + reflector-data-none in Mode 2 (2026-09-23), and then Mode 3 + RAS real-time + two
  antenna paths (2026-09-24, §15.3): 16.7 procedures/s at 114 steps per procedure, zero aborted
  or partial, `RAS data lost` about 1%. Procedure interval 1 is reachable — see
  implementation_plan.md §1.9; the earlier note here saying otherwise was stale.
- [ ] Compare three same-position runs: IPT + none, IPT + RAS, and no IPT + RAS.
- [ ] Confirm a peer without IPT reports `PEER_IPT_UNSUPPORTED` without a reconnect loop.
- [ ] Confirm Mode 3 with reflector data none keeps PBR working while showing RTT as
  unavailable, and that an unsubscribed Tag RAS responder does not affect procedures.
- [ ] Exercise runtime logging at debug level on both consumers during a four-path Mode 3 run;
  record the drop count and confirm no procedure aborts or RAS data loss (§2.7 step 7).
- [x] Verify Tag console over RTT does not block with no viewer attached. The hostless
  initiator's log now reaches `ble-channel-sounding` at the configured level (2026-09-23, `protocol_level`
  raised to INF in the planner export).
- [ ] Two open RAS loss faults (§3.3). The unexplained Tag reboot recorded here is closed
  (§15.5): it was a reflash into a build without the board conf, and the Tag has not reset on
  its own since. Still open:
  (a) the responder can latch into `Failed to allocate buffer for procedure N` and never
  recover — seen once at 1 buffer, not since `RD_BUFFERS_PER_CONN=4`, and not yet proven fixed
  because a 1-buffer session also ran clean; connect/disconnect cycles are what would tell;
  (b) sporadic `RAS_DATA_LOST`, which survives 4 buffers and is therefore a different fault.
  Measured at 0.5-1% in mode 2 with one path and about 1.5% sustained in mode 3 with two paths
  (2026-09-24, §15.3), so it appears to scale with RAS payload per procedure. Needs the
  reflector's view of the same procedures.
- [ ] Measure short-interval RAS behavior and document the minimum safe procedure interval per
  configuration size (the RAS procedure buffer holds one procedure).
- [ ] Verify STOP during RAS notifications, link loss during STOP, the STOP timeout path
  (`RAS_DATA_LOST` + OK/`_STOP_TIMEOUT`), and finite `max_procedure_count` completion.
- [x] Measure stack high-water marks with `CONFIG_THREAD_ANALYZER` (2026-09-24, §15.4). The
  result inverts the premise: no application thread exceeds 29% (`cs_role` 880/3072,
  `cs_role_events` 568/2048, `app_log_thread` 360/1536, `sysworkq` 328/2048), while two Zephyr
  Bluetooth stacks at their defaults are near the edge — `BT LW WQ` 1864/2104 (88%, during link
  setup), `MPSL Work` 768/1024 (75%, on the reflector only) and `bt_tx_processor` 744/904 (82%,
  once RAS flows). `APP_HOST_LINK_THREAD_STACK_SIZE` stays unmeasured: report-only mode starts
  no such thread.
- [x] Resize the stacks from that measurement (2026-09-24, §10 item 10). Application stacks cut
  in `common/libs/Kconfig`; the three upstream ones raised there as `configdefault` gated on
  `APP_CS_ROLES`. Both applications rebuilt; the Tag sits at 46.00% of 256 KB. Not yet run on
  hardware with the new sizes.
- [ ] Averaging experiments across T_PM values (§8.4 step 3). Yours; no analysis tool here.

## Blocked on flashing `cs_client`

One flash unblocks all of these; none of them can run on the hostless pair.

- [ ] Drive T_PM through `SET_T_PM` at 20 and 40 µs over the host link from `ble-channel-sounding`, and from
  a planner hostless export; then 10 µs again after a 40 µs run **without reflashing** (§10
  item 4). The no-reflash half only works over the host link — a hostless export bakes T_PM
  into the image — and it is what shows CS Params Set is issued before every Create Config.
- [x] Confirm the Controller tab reports ATT MTU 498 on a hosted link, and that a
  `cs_client`-to-`cs_client` link stays healthy when both ends request the exchange (§10 item 8).
- [ ] Verify the §10 item 9 teardown on hardware once the firmware change above is written.
- [ ] Run the full `ble-channel-sounding` workflow against `cs_client`: connect, sync, apply,
  start/stop, recording and MAT conversion (§9 item 6, first bullet).
- [ ] Exercise the hosted role pairs: `cs_client` initiator ↔ `cs_hostless_reflector`, and
  `cs_client` reflector ↔ `cs_hostless_initiator`.
- [ ] Test peer discovery and failure cases: two peers with identical names, a 32-byte
  configured name, unnamed peers, cancel while connecting, encryption failure, host loss, scan
  congestion with many nearby advertisers, and retry after a failure.
- [x] Test a single-antenna `cs_client` against a multi-antenna peer (4 paths), and that
  selections beyond the local antennas are rejected at `SET_*_CONFIG`.
- [x] Mode 1 only after the zero-antenna-path fix (2026-10-01, §18, §10 item 12): works on
  hardware, without the `RAS_DATA_LOST` on every procedure. `cs_hostless_initiator` carries
  the same fix from its next build.
- [ ] Exercise Radio Test RX and RX-sweep `RADIO_TEST_STATS` (baseline, periodic, final)
  against a known transmitter, and verify uart30 as the DK's second virtual COM port with
  hardware flow control at 921600 baud.

## Already confirmed on hardware

Recorded so the runs are not repeated:

- T_PM 10, 20 and 40 µs all reach configuration complete on `cs_hostless_initiator` ↔
  `cs_reflector_tag` through the controller's preferred T_PM (2026-09-19, §8.4 step 1, §8.5).
  Those runs selected T_PM at build time and predate `SET_T_PM`, so they confirm the mechanism
  and the values but not the host-link path above.

## Deferred future work

Intentionally unscheduled in §11 of the implementation plan:

- Task watchdog for a host-link thread stalled by an asserted DTR.
- Decide and implement the large-report TX-buffer/slow-host policy, based on hardware
  throughput measurements.
- Revisit allowing the reflector to create the CS configuration; the initial hardware attempt
  returned Unsupported LL Parameter Value (0x20).
- Add quantitative RAS drain-rate modeling to the planner after hardware measurements;
  MTU/notification/LL-PDU calculations and the air-time floor are already implemented.
