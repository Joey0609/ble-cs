# CS configuration management

The common library manages two caller-owned configuration types:

| Type | Stored settings |
| --- | --- |
| `struct cs_reflector_config` (36 bytes) | Header, ACL connection parameters, local CS defaults, procedure parameters |
| `struct cs_initiator_config` (60 bytes) | Header, ACL connection parameters, local CS defaults, procedure parameters, CS creation parameters and creation context, preferred T_PM |

Both are self-contained, byte-packed records. `cs_config.h` includes no Zephyr
header: every field is a fixed-width integer holding the HCI encoding of its
setting (`CS_CONFIG_*` constants), so a record can be stored or sent over a
serial link as raw bytes. Like `struct cs_capabilities`, a record starts with
`role` and `size`, followed by `config_id` and a reserved byte. Multi-byte
fields are host-endian (little-endian on nRF targets).

Values implied by the record are not stored. The role enable flags of the
default settings, the creation role, and the procedure/creation configuration
IDs are derived from `role` and `config_id` when the record is applied. The
Zephyr parameter structures are built only inside the apply helpers, and
`cs_config.c` asserts at build time that every `CS_CONFIG_*` encoding matches
its Zephyr counterpart.

Each role has its own default generator and setters. Initialize one record,
then pass that same record to its setters. There is no global mutable state or
allocation.

## Reflector

```c
#include <cs_utils/cs_config.h>
#include <errno.h>

/* conn is a valid connected struct bt_conn *. */
struct cs_reflector_config config;
int err = cs_reflector_config_get_default(&config);
if (err) {
    return err;
}

struct cs_config_connection connection = config.connection;
connection.interval_min = 12; /* 15 ms */
connection.interval_max = 12;
err = cs_reflector_config_set_connection(&config, &connection);
if (err) {
    return err;
}

struct cs_config_default_settings settings = config.defaults;
settings.max_tx_power = 0;
err = cs_reflector_config_set_default_settings(&config, &settings);
if (err) {
    return err;
}
/* Apply when the connection is ready. The application decides whether a
 * rejected ACL update is fatal; the existing reflector logs it and continues. */
err = cs_reflector_config_apply_connection(&config, conn);
if (err && err != -EALREADY) {
    return err;
}
err = cs_reflector_config_apply_default_settings(&config, conn);
if (err) {
    return err;
}
err = cs_reflector_config_apply_procedure(&config, conn);
if (err) {
    return err;
}
```

The reflector stores the settings it applies locally. The connected peer
supplies the shared measurement/channel configuration through CS configuration
exchange. Use `cs_reflector_config_set_config_id()` to select that configuration.
The existing reflector application uses this type in `src/reflector_config.c`.

## Initiator

```c
#include <cs_utils/cs_config.h>

struct cs_initiator_config config;
int err = cs_initiator_config_get_default(&config);
if (err) {
    return err;
}

err = cs_initiator_config_set_config_id(&config, 1);
if (err) {
    return err;
}

uint8_t channels[CS_CONFIG_CHANNEL_MAP_SIZE] = {0};
for (uint8_t channel = 26; channel < 62; channel++) {
    channels[channel / 8] |= 1U << (channel % 8);
}
err = cs_initiator_config_set_channel_map(&config, channels);
if (err) {
    return err;
}

struct cs_config_procedure procedure = config.procedure;
procedure.max_procedure_count = 10;
err = cs_initiator_config_set_procedure(&config, &procedure);
if (err) {
    return err;
}
/* Apply local settings, then cs_initiator_config_apply_creation() at the
 * appropriate point in the connection flow.
 * Security and procedure enablement remain application operations.
 */
```

## IPT

Use `cs_initiator_config_enable_ipt(&config)` before
`cs_initiator_config_apply_creation(&config, conn)` to request Inline Phase
Correction Term Transfer in the reflector. Use
`cs_initiator_config_disable_ipt(&config)` to clear the request before creating
a subsequent configuration. Both return `0`, or `-EINVAL` for NULL input,
and change only `CS_CONFIG_ENHANCEMENTS_1_IPT` in `creation.cs_enhancements_1`. Defaults keep IPT off.
Replacing the entire creation struct with `set_creation` also replaces this bit.

The reflector receives the IPT setting through the peer's configuration
exchange, so there is no reflector-local enable function. These helpers only
edit stored parameters; they do not change a running configuration or check
capabilities. Ensure the peer advertises `cs_ipt_reflector` and both controllers
support the requested configuration. Nordic controllers require
`CONFIG_BT_CTLR_EXTENDED_FEAT_SET=y` for CS enhancements, as used by the SDK's
IPT initiator and reflector samples.

### Reflector data

With IPT the initiator's phase correction terms already carry the full two-way
phase, so the initiator can run without the reflector's data. The initiator
record's `peer_data` byte (the former reserved byte)
selects it:

| `peer_data` | Value | Meaning |
| --- | --- | --- |
| `CS_CONFIG_PEER_DATA_RAS_REALTIME` | 0 | Default. Reflector subevents through RAS real-time |
| `CS_CONFIG_PEER_DATA_NONE` | 1 | Initiator subevents only, no RAS. Requires IPT |

- `cs_initiator_config_set_peer_data(&config, peer_data)` returns `-EINVAL` for
  NULL or an unknown value. It does not look at the IPT bit, because
  `set_creation` and `disable_ipt` can still change it.
- `cs_initiator_config_check_peer_data(&config)` returns `-EINVAL` for none
  without `CS_CONFIG_ENHANCEMENTS_1_IPT` (or an unknown value). Call it on the
  finished record; `host_link` and `cs_role_start_initiator()` both do.
- The reflector has no setting: its RAS responder sends nothing while no
  initiator subscribes. Records written before the field existed have 0 there
  and keep meaning RAS real-time.

### Preferred T_PM

The initiator record's last byte, `t_pm_us`, is the preferred phase measurement
period of mode-2 and mode-3 tones: `CS_CONFIG_T_PM_10_US` (default),
`CS_CONFIG_T_PM_20_US` or `CS_CONFIG_T_PM_40_US`.

- `cs_initiator_config_set_t_pm(&config, t_pm_us)` returns `-EINVAL` for NULL or
  any other value; `cs_initiator_config_apply_creation()` returns `-EINVAL` for a
  record with another value.
- `cs_utils` does not send it. It is a SoftDevice Controller vendor setting (CS
  Params Set), which the initiator role (`common/libs/cs_roles/cs_role_controller.c`)
  sets right before every `cs_initiator_config_apply_creation()`, so an earlier
  run's value never carries over. The controller uses it when both devices support
  it, otherwise a T_PM both support; the configuration-complete event reports the
  one in use.

## Setters and invariants

Both roles provide `get_default`, `set_connection`, `set_default_settings`,
`set_procedure` and `set_config_id` under their `cs_<role>_config_*` prefix.
The initiator additionally provides `set_creation`, `set_channel_map`,
`set_creation_context`, `set_peer_data` (with `check_peer_data`, see
[Reflector data](#reflector-data)) and `set_t_pm` (see [Preferred T_PM](#preferred-t_pm)).

- Default-settings setters copy antenna/power settings and require a maximum
  TX power of -127 to 20 dBm. Role flags are not stored; apply enables only
  the record's role.
- The single `config_id` is used for creation and procedure parameters, so
  there is nothing to keep in sync. The creation role is always initiator.
- Connection setters check ACL parameter ranges and the supervision timeout
  relationship. IDs must be 0-3. Channel maps require at least 15 enabled
  channels and exclude 0, 1, 23, 24, 25, 77, 78 and 79. Creation contexts must
  be `CS_CONFIG_CREATION_CONTEXT_LOCAL_ONLY` or `_LOCAL_AND_REMOTE`.
- Procedure setters require a defined tone antenna configuration and a
  `preferred_peer_antenna` mask of peer antennas 1-4 (bits 0-3, non-zero) with
  at least as many bits as the configuration's peer side: B for an initiator,
  A for a reflector. For A1:B2 an initiator needs two bits, for example
  `CS_CONFIG_PEER_ANTENNA_1 | CS_CONFIG_PEER_ANTENNA_2`. Whether the peer has
  those antennas is checked by `cs_roles` once its capabilities are read.
- Every setter copies its input and returns `0` on success or `-EINVAL` on
  invalid input. A rejected update leaves the entire instance unchanged.
- Use setters for changes to preserve these invariants. Direct field writes
  bypass the checks. Other PHY, power, step/timing and capability constraints
  are the application's/controller's responsibility.

## Applying an instance

Both roles provide `apply_connection`, `apply_default_settings` and
`apply_procedure` under their `cs_<role>_config_*` prefix. Each takes the stored
record and a connected `struct bt_conn *`, builds the Zephyr parameter
structure from the stored fields, and propagates the return code. NULL arguments return `-EINVAL`.
They leave the stored instance unchanged and retain no pointer to it.

The initiator also provides `cs_initiator_config_apply_creation(&config, conn)`.
It submits `config_id`, the initiator role and the stored creation parameters and context through
`bt_le_cs_create_config()`. Wait for successful `le_cs_config_complete`, perform
CS security setup and await its completion, then apply procedure parameters
and enable procedures at the appropriate point in the application flow.

ACL updates and CS creation have asynchronous completion. A successful apply
call does not mean negotiation or creation has finished. Individual helpers
allow the application to respect that ordering. No helper rolls back earlier
operations. Security and procedure enablement remain explicit application
operations. The existing reflector uses the three reflector apply helpers and
preserves its policy of logging a rejected ACL update while continuing to
apply local CS settings.

## Formatting records as text

Every cs_utils printer formats into a caller-provided buffer and writes nothing
to a console. The caller decides where the text goes (USB CDC, a log backend,
a file) and when, so formatting can run in a low-priority thread instead of a
Bluetooth callback.

```c
char text[CS_REFLECTOR_CONFIG_PRINT_SIZE];
int len = cs_reflector_config_print(text, sizeof(text), &config);

if (len > 0) {
    output(text, len);
}
```

All printers share one contract:

- Signature `int <name>_print(char *buf, size_t size, const T *record)`.
- Returns the number of characters written, excluding the terminating NUL.
- `-EINVAL` for a NULL buffer or record, or a zero size; nothing is written.
- `-ENOSPC` when the text did not fit. `buf` then holds the NUL-terminated
  prefix that did fit.
- Lines end in `\n`. Encoded values are written numerically with timing and
  power units where they apply.
- Each printer has a `*_PRINT_SIZE` macro; a buffer of that size is never
  truncated.

| Printer | Buffer size macro |
| --- | --- |
| `cs_reflector_config_print()` | `CS_REFLECTOR_CONFIG_PRINT_SIZE` |
| `cs_initiator_config_print()` | `CS_INITIATOR_CONFIG_PRINT_SIZE` |
| `cs_fae_table_print()` | `CS_FAE_TABLE_PRINT_SIZE` |
| `cs_capabilities_print()` | `CS_CAPABILITIES_PRINT_SIZE` |
| `cs_config_complete_print()` | `CS_CONFIG_COMPLETE_PRINT_SIZE` |
| `cs_procedure_enable_complete_print()` | `CS_PROCEDURE_ENABLE_COMPLETE_PRINT_SIZE` |
| `cs_subevent_header_print()` | `CS_SUBEVENT_HEADER_PRINT_SIZE` |
| `cs_step_print()` | `CS_STEP_PRINT_SIZE` |

The initiator configuration text also includes all creation fields, context,
raw channel-map bytes and enabled channel indices.

`cs_fae_table_print()` takes the `CS_FAE_TABLE_ENTRIES` (72) signed entries
rather than `struct bt_conn_le_cs_fae_table`, so a callback can copy the table
and format it later. It writes them eight per row with table-index labels.

A subevent is formatted one piece at a time: `cs_subevent_header_print()` for
the header, then `cs_step_print()` for each step walked with
`cs_step_first()`/`cs_step_next()`. One step fits in `CS_STEP_PRINT_SIZE`,
while a whole 160-step subevent would need tens of kilobytes.

## Controller results

`cs_results.h` captures what the controller settled on, as opposed to the
requested settings in `cs_config.h`. Like the config records it includes no
Zephyr header.

| Record | Size | Source callback |
| --- | --- | --- |
| `struct cs_config_complete` | 40 bytes | `le_cs_config_complete` |
| `struct cs_procedure_enable_complete` | 31 bytes | `le_cs_procedure_enable_complete` |

Each record starts with `type` (`CS_RESULT_TYPE_*`) and `size`, then the
connection index, the callback's HCI status and a GRTC timestamp. Fields hold
HCI encodings; interpret them with the `CS_CONFIG_*` constants. Fill a record
from the callback with `cs_config_complete_pack()` or
`cs_procedure_enable_complete_pack()`, passing the status as well. On a
non-zero status the parameters may be NULL, and everything after the header is
zero. A procedure enable complete with `state` disabled keeps only `config_id`
and `state`; the controller's other parameters are ignored by the Core
specification (Vol 4, Part E, §7.7.65.43) and left zero. Format them with `cs_config_complete_print()` and
`cs_procedure_enable_complete_print()`.

## Subevent results

`cs_reports.h` turns a subevent report into byte-aligned step records.
`cs_subevent_parse()` writes a whole subevent into one buffer
(`CS_SUBEVENT_BUF_SIZE(160)`, several kilobytes). For streaming without that
buffer, walk the step data with `cs_step_data_read()` (does not consume the
buffer) and decode one step at a time with `cs_step_decode()` into
`CS_STEP_MAX_SIZE` bytes; with a NULL destination it only validates the step and
returns the record size, so a first pass can size the output and a second pass
decode it. `cs_subevent_parse()` is built on the same two functions. RAS data
carries no abort step: use `CS_SUBEVENT_ABORT_STEP_NONE`.

## Defaults

Both roles use the existing local baseline: 7.5 ms ACL interval, no latency,
4 s timeout, repetitive sync antenna selection, maximum allowed CS TX power,
configuration ID 0, 6.25 ms maximum procedure duration, 1-4 ACL events between
procedures, unlimited procedures, 6 ms subevents, A1:B1 antennas, 1M procedure
PHY, no TX power delta recommendation and no SNR controls.

The initiator also gets mode 2/submode 1, 2-10 main-mode steps, no main-mode
repetition, one mode-0 step, AA-only RTT, 1M sync PHY, channels 26-61
(2428-2463 MHz), one channel-map repetition and selection 3b. Inactive selection
3c fields use hat shape/jump 2. Enhancements are zero. Creation context defaults
to local-and-remote. Reflector data is RAS real-time. These measurement settings match the checked-in initiator
example; scheduling uses the common baseline above.

## Build integration

Link `app_libs` from `common/libs/libs.cmake` with
`CONFIG_BT_CHANNEL_SOUNDING=y`. Both configuration APIs are compiled into the
same common library; the actual enabled controller role remains a build and
hardware capability. Generating an initiator object does not enable initiator
support on a reflector-only controller.

`libs.cmake` validates the shared CRC dependency and CS host/controller build
requirements. SDK Kconfig validates its ranges and choices. Runtime settings
are requests, not negotiated results. Default generators and setters perform no
Bluetooth operations; apply helpers explicitly issue their corresponding Zephyr
commands.
