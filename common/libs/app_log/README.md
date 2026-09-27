# Application log

Every application and library in this repository logs through `app_log`. A message
goes to each **consumer** whose level admits it, and the levels are part of the
applied configuration: they change at runtime, without rebuilding.

| Consumer | Output | Registered by |
| --- | --- | --- |
| console | `printk` of `[s.mmm] <lvl> module: text`. With `CONFIG_LOG_PRINTK` (the default) it passes through the deferred Zephyr log with the subsystem messages, to the debug UART or RTT | `app_log` at boot |
| protocol | `LOG_MESSAGE` frame with `<lvl> module: text` | `host_link`: while a host session is open (`cs_client`), or with the report-only transport (`cs_hostless_initiator`) |

## Where messages go

| Producer | Consumers |
| --- | --- |
| `host_link`, `cs_roles`, `cs_client`, both hostless apps, `cs_reflector_tag` (`APP_LOG_*`) | Console at or below `console_level`; `LOG_MESSAGE` at or below `protocol_level` while a protocol consumer is registered. In `ble-channel-sounding`: *Session log* view (category "client log"), Results *Log* tab, HDF5 `/log` and MAT |
| Queue-full notices (`host_link` reports, `cs_roles` role and event queues, `cs_client` scan reports, `app_log` itself) | Warnings through the same consumers (they were console-only `printk` before) |
| Record dumps (`cs_*_print()`) | Caller buffer; the caller logs it. `cs_reflector_tag` logs its configuration one line per message |
| Zephyr/NCS subsystems (Bluetooth host, SDC, USB) | Zephyr log backend, set at build time (`CONFIG_LOG`) |

Reflector images have no protocol consumer, so their `protocol_level` has no effect.

## Levels

Zephyr numbering: 0 off, 1 error, 2 warning, 3 info, 4 debug. A consumer at a level
receives that level and the ones below it.

| Where the levels come from | When |
| --- | --- |
| Defaults: console info, protocol warning | At boot, and while no configuration is held |
| `SET_LOG_CONFIG` (`0x0111`, `cs_protocol/README.md`) | `cs_client`, at `APPLY_CONFIG`, in every operation mode. A configuration without it restores the defaults |
| `cs_generated_config_log()` in a planner export | Hostless apps and `cs_reflector_tag`, at boot, before Bluetooth starts. The weak default returns the defaults with `-ENOENT` |

With the protocol at warning, the host keeps receiving abnormal situations. State
changes need no text at info: `CLIENT_STATE` frames describe them.

## API (`app_log.h`)

```c
APP_LOG_MODULE(cs_roles);                 /* once per file; files of one library share it */

APP_LOG_WRN("Setup stage %u timed out", stage);
APP_LOG_DBG("Command 0x%04x, %u bytes", type, len);   /* arguments not evaluated when filtered */
```

- `APP_LOG_ERR/WRN/INF/DBG(fmt, ...)`: printf rules (Zephyr `cbprintf`). The level is
  checked before the arguments are evaluated: nothing is formatted when every consumer
  filters the message out.
- `app_log_configure()`, `app_log_config_get()`, `app_log_defaults()`: consumer levels.
  `app_log_configure()` rejects a level above 4 with `-EINVAL`.
- `app_log_sink_register(sink, write)`: registers or (with `NULL`) removes a consumer.
- `app_log_flush()`: writes every queued message from the calling thread. The Tag calls
  it before rebooting.
- `app_log_dropped()`: messages dropped for a full queue since boot.

## Threads

Callers check the level, format the message into a record and queue it. They never
block, so Bluetooth callbacks and work items may log. ISR context is not supported
(`__ASSERT`). The log thread writes each record to the consumers; the protocol consumer
waits up to `CONFIG_APP_HOST_LINK_REPORT_TIMEOUT_MS` for transmit room.

A message that finds the queue full is dropped and counted. Once the log thread frees
a record, it logs the count as one warning:
`<wrn> app_log: N messages dropped: queue full`. A `LOG_MESSAGE` lost for transmit room
is counted in the host link report statistics but not announced: the announcement
would itself be a log message.

## Kconfig

Kconfig only sizes the library; it never selects consumers. `CONFIG_APP_CS_ROLES` and
`CONFIG_APP_HOST_LINK` select `CONFIG_APP_LOG`, and an application without them enables it
directly.

| Option | Default | |
| --- | --- | --- |
| `CONFIG_APP_LOG_MESSAGE_MAX` | 256 | Longest message, prefix included; longer ones are truncated. Also the longest `LOG_MESSAGE` text |
| `CONFIG_APP_LOG_QUEUE_DEPTH` | 16 | Records waiting for the log thread (`cs_reflector_tag`: 32, for its configuration dump at boot) |
| `CONFIG_APP_LOG_THREAD_STACK_SIZE` | 1536 | |
| `CONFIG_APP_LOG_THREAD_PRIORITY` | 12 | Below the Bluetooth, role and host link threads |

## Tests

`sh tests/app_log/run.sh` builds `app_log.c` and `app_log_console.c` natively with a
test-only kernel subset (`tests/app_log/include/`), with strict warnings, AddressSanitizer
and UndefinedBehaviorSanitizer. It covers per-consumer thresholds, arguments that are not
evaluated when filtered, the prefix and module format, truncation, the full queue with
its single warning, a missing protocol consumer and the console format.
