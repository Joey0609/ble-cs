# Connected CS initiator test

A Channel Sounding initiator configured and reported entirely through
[cs_utils](../../common/libs/cs_utils/README.md). It is the counterpart of
[cs_reflector_test](../cs_reflector_test/README.md): it scans for a Ranging
Service advertiser, connects and pairs, creates a compiled-in CS configuration
on both controllers, starts procedures, and streams every CS report to a host
as text.

The initiator does not use the Ranging Service itself. Each side reports its
own local subevent results; run both tests to capture initiator and reflector
steps.

## Two output channels

| Channel | Carries |
| --- | --- |
| Native USB CDC ACM (`cdc_acm_uart0`) | Report text only, formatted by the cs_utils printers |
| Debug UART (`uart20`, 921600 baud) | Deferred log: status, errors, statistics, `TEST PASS`/`TEST FAIL` |

Logs never enter the CDC stream, and report text never goes to the UART. The
UART setup (deferred logging, asynchronous backend, UARTE DMA) matches
[usb_acm_rate_test](../usb_acm_rate_test/README.md).

## Connection sequence

`main.c` drives the setup one step at a time. Bluetooth callbacks only post an
event; the next command is issued from the main thread.

1. Scan passively for a connectable advertiser listing the Ranging Service
   UUID (and `TEST_PEER_NAME`, if set).
2. Connect with the ACL parameters from the configuration.
3. Pair to security level 2 (encryption, no bond).
4. Apply local CS default settings, then read the remote CS capabilities.
5. Read the remote FAE table. A failure is logged and the sequence continues.
6. Create the CS configuration locally and on the reflector.
7. Enable CS security.
8. Apply the procedure parameters and enable procedures.

A failure at any other step logs `TEST FAIL <stage>` and disconnects. After a
disconnect or failed connection, scanning resumes once the connection object is
released.

## Data flow

```
BT RX thread                        report printer thread            CDC workqueue
cs_capabilities_pack ──┐            record_queue_get                  uart_fifo_fill
cs_config_complete_pack┤              └► cs_*_print(text) ──► cdc_out_write ──► host
cs_procedure_enable_pack┼► record_queue    (subevent: header,
cs_subevent_parse ─────┤   (packed          then one cs_step_print
FAE table copy ────────┘    records)        call per step)
```

- `cs_events.c` callbacks only pack or parse with cs_utils and copy the packed
  record into `record_queue.c`, then report setup step completion to main.
  They never format text or wait. A full queue drops the record and counts it.
- `report_printer.c` is the only place text is produced. It runs below the
  Bluetooth threads and blocks on USB, so a slow host costs queue space, never
  CS timing.
- `cdc_out.c` moves text into the CDC ACM FIFO from its transmit callback.
- While no host holds the port open (DTR low), records are discarded and
  counted. When a host opens it, the applied `cs_initiator_config` and the
  local `cs_capabilities` are printed first, then live reports follow.

On the CDC port the host receives, in order: the initiator configuration, local
capabilities, then per connection the remote capabilities, FAE table, CS
configuration complete, procedure enable complete, and one subevent header
plus its steps per subevent report.

## Configuring a test

Edit the `TEST_*` block at the top of [src/test_cfg.c](src/test_cfg.c), then
rebuild and flash. Values go through `cs_initiator_config_set_*()`, so a value
a setter rejects stops the test with `TEST FAIL configuration rejected`. Unlike
the reflector, the initiator owns the shared configuration: mode, step counts,
RTT type, sync PHY, channel map and channel selection.

`TEST_PEER_NAME` defaults to `"CS Reflector Test"`, the name
[cs_reflector_test](../cs_reflector_test/README.md) advertises. Set it to `""`
to connect to any Ranging Service advertiser, such as the NCS
`channel_sounding_ras_reflector` sample.

`TEST_EXPECTED_PROCEDURES` sets when the verdict is logged: once that many
procedures have completed or aborted, the UART shows `TEST PASS` if none
aborted, otherwise `TEST FAIL procedures`. Setup failures log
`TEST FAIL <stage>` immediately.

Buffer sizes, printer priority and the statistics interval are Kconfig options
in [Kconfig](Kconfig).

## Building and running

```sh
west build -b nrf54lm20dk/nrf54lm20b/cpuapp -d tests/cs_initiator_test/build tests/cs_initiator_test
west flash -d tests/cs_initiator_test/build
```

Open the debug UART at 921600 baud, and the native USB port with any terminal
(for example `python3 -m serial.tools.miniterm /dev/cu.usbmodem* 115200`).

The debug UART prints statistics every
`CONFIG_CS_INITIATOR_TEST_STATS_INTERVAL_MS` while idle, in this format (values
illustrative):

```
CS: subevents 812, procedures 203 complete / 0 aborted, truncated 0, parse errors 0
Reports: queued 1024, dropped 0, high water 5120/32768, printed 1022, discarded 0, format errors 0
USB CDC: host attached, 2911340 bytes, aborted writes 0
```

A growing `dropped` count means the host or USB link is slower than the report
rate. Raise `CONFIG_CS_INITIATOR_TEST_RECORD_QUEUE_SIZE` or reduce the procedure
rate.
