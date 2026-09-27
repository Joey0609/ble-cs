# Host link

The client side of the CS protocol over a UART: USB CDC ACM or a hardware UART
(command rules: `common/libs/cs_protocol/README.md`).
The application registers a handler table; the library owns the session, the
command rules, the staged and applied configuration and its CRC, and sends every
response.

Enable with `CONFIG_APP_HOST_LINK=y` in an application whose `Kconfig` sources
`common/libs/Kconfig`, and choose the UART as `app,host-link-uart`:

```dts
/ { chosen { app,host-link-uart = &cdc_acm_uart0; }; };   /* USB CDC ACM */
/ { chosen { app,host-link-uart = &uart30; }; };          /* hardware UART */
```

- **USB CDC ACM** needs the USB device stack (`CONFIG_USB_DEVICE_STACK_NEXT`) and the
  CDC ACM class. `CONFIG_APP_HOST_LINK_DTR` then defaults on: DTR tells whether a host
  has the port open.
- **Hardware UART** needs no USB. It has no DTR, so leave `CONFIG_APP_HOST_LINK_DTR`
  off and enable the instance's interrupt-driven API (e.g.
  `CONFIG_UART_30_INTERRUPT_DRIVEN=y`).

`libs.cmake` then builds the sources below. The build also needs Channel Sounding
or `APP_LIBS_RADIO_TEST`, since every mode is one or the other.

| File | Responsibility |
| --- | --- |
| `host_link.c/.h` | Host link thread: parser, DTR tracking (CDC ACM), frame size per command, session, BUSY / LINK_ACTIVE rules, `GET_CONFIG` replay, `START` CRC check, responses; the `app_log` protocol consumer and the log levels at `APPLY_CONFIG` |
| `host_link_handlers.h` | Handler table: `client_state`, `link_active`, `validate_config`, `apply`, `start`, `stop`, `interrupt` (session ended while running; `stop` covers the other busy states), `link_disconnect` (also while running), `session_changed`, `response_sent` (reports that must follow a response) |
| `host_link_config_store.c/.h` | Staging area, applied configuration and CRC on raw payloads, including the optional device name, reflector data (`SET_PEER_DATA`: CS initiator only, value none only, none without IPT rejected at `APPLY_CONFIG`), preferred T_PM (`SET_T_PM`: CS initiator only, 20 or 40 µs) and log levels (`SET_LOG_CONFIG`: every mode, levels 0–4, not both defaults); no Zephyr headers |
| `host_link_config.c/.h` | Payload → `cs_initiator_config` / `cs_reflector_config` (cs_utils setters) and → `radio_test_mode_config`; `host_link_config_set_to_initiator()` also applies `SET_PEER_DATA` and `SET_T_PM` and runs `cs_initiator_config_check_peer_data()` |
| `host_link_reports.c/.h` | `CLIENT_STATE`, `CS_FAE_TABLE`, `RAS_DATA_LOST`, `RADIO_TEST_STATS`, `CS_PROCEDURES_COMPLETE`, `CS_PEER_DATA`, negotiated `CONNECTION_PARAMETERS`, cs_utils records, pre-built frames; subevent results streamed step by step (`host_link_report_cs_subevent_begin/step/end`) |
| `host_link_frame.c/.h` | A frame written in pieces with an incremental CRC, byte-identical to an encoded frame; a short frame gets an invalid CRC. No Zephyr kernel headers |
| `host_link_transport.c/.h` | Interrupt-driven UART RX/TX ring buffers, DTR when `CONFIG_APP_HOST_LINK_DTR`; whole frames are queued atomically, including streamed frames (room reserved at begin) |
| `host_link_types.h` | `struct host_link_result`, `struct host_link_config_set`, payload sizes |

## Threads

Handlers run on the host link thread, one at a time, and may block until their
operation completes (for example `STOP` waiting for the last RAS data) as long as
they return within the host timeout. Reports may be sent from any thread; they
are dropped and counted without a host session, or when there is no transmit room
within `CONFIG_APP_HOST_LINK_REPORT_TIMEOUT_MS`. Bluetooth and radio callbacks
must hand their data to a thread before reporting, except the streamed subevent
results: `cs_roles` calls `host_link_report_cs_subevent_begin()` / `_step()` /
`_end()` from Bluetooth context. Begin checks room for the whole frame once and
never waits; without room the subevent is dropped before any byte is queued and
counted, and the loss is logged as a warning once the host link thread runs. No subevent is copied: each step is encoded straight into the transmit
ring buffer.

The transport never blocks without a bound: its locks are spinlocks, and the only
wait, for transmit room, ends at a build-time deadline
(`CONFIG_APP_HOST_LINK_RESPONSE_TIMEOUT_MS` for responses,
`CONFIG_APP_HOST_LINK_REPORT_TIMEOUT_MS` for reports, both range-limited in
Kconfig and checked with `BUILD_ASSERT`). Callers cannot pass their own timeout.

## Log messages

`host_link` is the protocol consumer of `app_log` (`common/libs/app_log/README.md`): it
registers itself when a host session opens and removes itself when the session ends, so
without a session protocol messages are not even formatted. The report-only transport
(`host_link_report_only_init()`) registers it for good. Each message is one
`LOG_MESSAGE` frame, sent from the log thread with the report timeout. A `LOG_MESSAGE`
lost for transmit room counts as a dropped report but is not announced, because the
announcement would itself be a log message.

`APPLY_CONFIG` sets the `app_log` levels from the staged `SET_LOG_CONFIG`, or to the
defaults without it, after the application's `apply` handler succeeds. The
report-only transport never receives `SET_LOG_CONFIG`: its application sets the levels.

## Session end

`CLOSE_SESSION` and a dropped host port (DTR low without `CLOSE_SESSION`) end the
session the same way, and stop the client in every busy state, since no host is left to
receive the results:

- `RUNNING`: the `interrupt` handler stops the operation, reported as
  `CLIENT_STATE(STOPPED, INTERRUPTED, -ECANCELED)` for `CLOSE_SESSION` and `-ENOTCONN`
  for a dropped port.
- `SCANNING`, `ADVERTISING`, `LINK_CONNECTING`: the `stop` handler cancels discovery or
  the connection attempt, as `STOP` does.
- `LINK_CONNECTED`, `RAS_READY`: the `stop` handler cancels a CS setup in progress,
  reported as `CLIENT_STATE(STOPPED, INTERRUPTED, -ECANCELED)`. On an idle link it does
  nothing.

The applied configuration and an established Bluetooth link are retained for the next
`CONNECT`. The session is closed before the handler runs, so a report with an error has
nowhere to go and is sent again right after the next `CONNECT_RESPONSE`. The
`cs_roles` role and event threads run above the host link thread, so a stop they report
has been attempted, and kept, by the time the handler returns; the next `CONNECT`
cannot overtake it. A dropped port is logged as a warning on the console only: the
session, and with it the protocol log consumer, has already ended.

`LINK_DISCONNECT` is accepted while running: the `link_disconnect` handler stops the
operation first, so the host needs no `STOP` before it.

Without `CONFIG_APP_HOST_LINK_DTR` (hardware UART) a dropped port cannot be seen: only
`CLOSE_SESSION` ends the session. If the host disappears without it, the session, the
applied configuration and a running operation are kept, and the next `CONNECT`
attaches to them (the response reports the configuration and client state).

## Tests

`tests/host_link/run.sh` builds natively with sanitizers: the configuration store
(shared CRC vectors, staging and apply rules, pattern checks, reflector data), names, discovery
packets, antenna checks, and the frame writer (streamed frame equals the encoded
frame, refused frames write nothing, short frames are discarded by the host).
`test_commands.c` includes `host_link.c` with the transport, `app_log` and the application
stubbed, and feeds it host frames: every command status (`NOT_CONNECTED`, `BUSY`, `LINK_ACTIVE`,
`MODE_MISMATCH`, `MISSING_CONFIG`, `MISSING_PATTERNS`, `CONFIG_MISMATCH`, `INVALID_FRAME`,
`VERSION`, `UNSUPPORTED`), staging and apply, the log levels applied, `GET_CONFIG` replay (the
replayed frames give the same CRC), `START`, `LINK_DISCONNECT` while running, session end
(interrupt while running, stop while discovering or in setup, nothing when idle) and report
counting.

`tests/cs_roles/run.sh` (needs `ZEPHYR_BASE`) compares a streamed subevent frame
(`host_link_report_cs_subevent_begin/step/end()`) with the frame built from a
`cs_subevent_parse()` record for every step type, both roles, every RTT type and 1–4 antenna
paths: they are the same bytes.
