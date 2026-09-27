# CS protocol

A byte-frame wrapper and self-contained wire definitions. The protocol does not
select hardware roles, apply settings, convert utility records, or manage a
configuration state machine. Those operations belong to the application.

## Wire format

Every frame uses little-endian integers, without padding:

```
sync:u16 | size:u16 | type:u16 | message fields | crc32:u32 | end_sync:u16
```

- `sync` = `0x5AA5`; `end_sync` = `0xA55A`.
- `size` is the entire frame size, including header and footer: 12–65535 bytes.
- `crc32` covers `size`, `type`, and the message fields. Sync markers are excluded.
- CRC-32/IEEE uses reflected polynomial `0xEDB88320`, initial value `0xFFFFFFFF`,
  and final XOR `0xFFFFFFFF`. The check value for `123456789` is `0xCBF43926`.

`cs_protocol_packets.h` declares each fixed frame in full: the common
`struct cs_protocol_header_t header`, individual message fields, and the common
`struct cs_protocol_footer_t footer` (both defined in `cs_protocol.h`). It does not embed utility structs or
separate payload wrappers. All fields in these structs are wire-order values.
Use little-endian writes for multi-byte fields on platforms that need conversion.

Variable-length log and subevent frames declare their fixed fields and a flexible
array. C cannot put a footer after a flexible array: the CRC and end sync follow
the actual data at `size - 6` and `size - 2`. The declared `sizeof` is only the
fixed prefix for these frames; allocate room for the data and six-byte footer.

## Messages

Type names below omit `CS_PROTOCOL_PACKET_`.

| Type | Value | Message fields | Complete size |
| --- | --- | --- | --- |
| SET_OPERATION_MODE | 0x0100 | mode: u8; 0 initiator, 1 reflector, 2 radio test | 13 |
| SET_CS_INITIATOR_CONFIG | 0x0101 | GAP role, config ID, ACL settings, CS defaults, procedure and creation settings | 69 |
| SET_CS_REFLECTOR_CONFIG | 0x0102 | GAP role, config ID, ACL settings, CS defaults and procedure settings | 46 |
| SET_RADIO_TX_TEST_CONFIG | 0x0103 | Test type, PHY, channel, power, pattern, packet count, sweep, duty cycle, sleep and FEM settings | 37 |
| SET_PERIPHERAL_PATTERNS | 0x0104 | count: u8, lengths: u8[8], patterns: u8[8][32] | 277 |
| APPLY_CONFIG | 0x0105 | No message fields | 12 |
| CONNECT | 0x0106 | protocol_version: u16 | 14 |
| START | 0x0107 | config_crc32: u32 (the configuration the host expects to run) | 16 |
| STOP | 0x0108 | No message fields | 12 |
| CLOSE_SESSION | 0x0109 | No message fields; ends the host session and stops the client (running operation, discovery, CS setup) | 12 |
| GET_CONFIG | 0x010A | No message fields | 12 |
| LINK_DISCONNECT | 0x010B | No message fields; stops a running operation, disconnects the link, stops scanning/advertising | 12 |
| CS_CAPABILITIES | 0x0001 | source (local/remote), conn_index, CS capability fields | 49 |
| CS_CONFIGURATION | 0x0002 | Negotiated CS configuration fields | 40 |
| CS_PROCEDURE_ENABLE_COMPLETE | 0x0003 | Procedure completion fields | 31 |
| CS_INITIATOR_SUBEVENT_RESULT | 0x0004 | Result fields, decoded steps and tones | variable |
| CS_REFLECTOR_SUBEVENT_RESULT | 0x0005 | Result fields, decoded steps and tones | variable |
| LOG_MESSAGE | 0x0006 | Text bytes without a terminating NUL: `<lvl> module: text` | variable |
| CONNECT_RESPONSE | 0x0007 | status: u8, protocol_version: u16, supported_modes: u8, firmware_version: u32, max_frame_size: u16, config_valid: u8, operation_mode: u8, config_crc32: u32, client_state: u8, num_antennas_supported: u8 | 30 |
| COMMAND_RESPONSE | 0x0008 | request_type: u16, status: u8, reason: u8, error: i32, config_crc32: u32 | 24 |
| CS_FAE_TABLE | 0x0009 | hci_status: u8, lsb_denominator: u8, entries: i8[72] | 86 |
| CLIENT_STATE | 0x000A | state: u8, operation_mode: u8, reason: u8, hci_status: u8, error: i32 | 20 |
| RAS_DATA_LOST | 0x000B | ranging_counter: u16, error: i16 | 16 |
| RADIO_TEST_STATS | 0x000C | packets_received: u32, crc_errors: u32, rssi_dbm: i8 (127 = none), channel: u8 | 22 |
| CS_PROCEDURES_COMPLETE | 0x000E | procedures_completed: u16 | 14 |
| CS_PEER_DATA | 0x000F | peer_data: u8; 0 RAS real-time, 1 none (initiator only) | 13 |
| CONNECTION_PARAMETERS | 0x0010 | negotiated ACL interval: u16 (1.25 ms), latency: u16 (events), supervision timeout: u16 (10 ms), ATT MTU: u16 (bytes) | 20 |
| SET_PEER_DATA | 0x0110 | peer_data: u8; only 1 (none) is accepted | 13 |
| SET_LOG_CONFIG | 0x0111 | console_level: u8, protocol_level: u8; 0 off … 4 debug, not both defaults | 14 |
| SET_T_PM | 0x0112 | t_pm_us: u8; only 20 or 40 are accepted | 13 |

The header gives the exact order, widths, units and encodings of individual
fields. Sub-event messages contain `num_steps_reported` records; each record
has a 22-byte fixed portion followed by `num_tones` eight-byte tone entries.

The host sends the operation mode, the matching configuration, peripheral name
patterns when the CS device is GAP central, and an apply command. GAP role is
independent of CS role: 0 = central, 1 = peripheral. Name patterns are 1–8
case-sensitive prefixes of 1–32 bytes, combined with OR. They contain no NUL;
unused lengths, slots and padding are zero. Pattern matching and validation
are application work. Radio callbacks and utility record bookkeeping fields
are never transmitted.

Session encodings (`cs_protocol_packets.h`):

- `CS_PROTOCOL_VERSION` = `0x000B` (adds the ATT MTU to the negotiated
  `CONNECTION_PARAMETERS` report; update firmware and host together). Version 10 added
  the report itself; version 9 added `SET_T_PM`.
  Version 8 added `SET_LOG_CONFIG`. Version 7 added `SET_PEER_DATA`, `CS_PEER_DATA` and
  `PEER_IPT_UNSUPPORTED`. Version 4 added the board
  antenna count to `CONNECT_RESPONSE`. Version 2 had no `CLIENT_STATE.error`; a 16-byte
  `CLIENT_STATE` decodes with `error = 0`, so older captures stay readable.
- `status`: 0 OK, 1 REJECTED (see `reason`), 2 UNSUPPORTED, 3 BAD_STATE,
  4 INVALID_FRAME, 5 VERSION, 6 FAILED (see `error`), 7 CONFIG_MISMATCH.
- `reason`: 0 NONE, 1 NOT_CONNECTED, 2 MODE_MISMATCH, 3 VALUE_OUT_OF_RANGE,
  4 NONZERO_PADDING, 5 MISSING_CONFIG, 6 MISSING_PATTERNS, 7 BUSY, 8 LINK_ACTIVE,
  9 STOP_TIMEOUT, 10 RAS_NO_REALTIME, 11 TEST_COMPLETE, 12 INTERRUPTED, 13 SCAN_FAILED,
  14 ADVERTISE_FAILED, 15 CONNECT_FAILED, 16 SECURITY_FAILED, 17 RAS_DISCOVERY_FAILED,
  18 CS_CONFIG_FAILED, 19 CS_SECURITY_FAILED, 20 PEER_IPT_UNSUPPORTED.
- `error`: negative Zephyr errno, 0 on success. `CLIENT_STATE.error` is non-zero only when
  the change ended an operation abnormally (`-ECANCELED` = -140, `-ENOTCONN` = -128).
- `state` / `client_state`: 0 IDLE, 1 CONFIGURED, 2 SCANNING, 3 ADVERTISING,
  4 LINK_CONNECTED, 5 RAS_READY, 6 RUNNING, 7 STOPPED, 8 LINK_LOST,
  9 LINK_DISCONNECTED, 10 ERROR.
- `supported_modes`: bit n = operation mode n (`CS_PROTOCOL_MODE_BIT`).
  `operation_mode` is `CS_PROTOCOL_MODE_NONE` (0xFF) when no configuration is applied.
- `CS_FAE_TABLE` entries are in HCI table order; ppm = entry / `lsb_denominator`.
  Entries are zero when `hci_status` is not 0.

## Configuration CRC

The client holds exactly one applied configuration (operation mode, matching
configuration frame, and the optional patterns, device name, reflector data, preferred
T_PM and log levels), in RAM
until reset.
`config_crc32` is `cs_protocol_crc32()` over the concatenated **payloads**, without
headers or footers, in this order:

1. `SET_OPERATION_MODE` payload (1 byte)
2. `SET_CS_INITIATOR_CONFIG`, `SET_CS_REFLECTOR_CONFIG` or `SET_RADIO_TX_TEST_CONFIG` payload
3. `SET_PERIPHERAL_PATTERNS` payload, only if patterns are part of the applied configuration
4. `SET_DEVICE_NAME` payload, only if a device name is part of the applied configuration
5. `SET_PEER_DATA` payload, only if reflector data is part of the applied configuration
6. `SET_T_PM` payload, only if a preferred T_PM is part of the applied configuration
7. `SET_LOG_CONFIG` payload, only if log levels are part of the applied configuration

`GET_CONFIG` replays the frames in the same order. A configuration without an optional
payload keeps the CRC it had before that payload existed.

- The client stores the payload bytes exactly as received; it never re-serialises them.
- Pattern frames with non-zero bytes after a pattern's length, or in unused slots, are
  rejected (`NONZERO_PADDING`), so equal pattern sets always have equal bytes.
- `SET_*` commands fill a staging area. `APPLY_CONFIG` validates the staged set as a
  whole, replaces the applied configuration and clears the staging area. A rejected
  `APPLY_CONFIG` leaves the applied configuration unchanged. Patterns not staged since
  the last apply are not part of the new configuration.
- No applied configuration: `config_valid = 0`, `config_crc32 = 0`.
- `tests/host_link/test_config_store.c` and `python/tests/test_protocol.py` share the test
  vectors: initiator configuration + two patterns → `0xB61D36F1`; the same configuration
  with `creation_cs_enhancements_1` = 1 (IPT), the two patterns and `SET_PEER_DATA(1)` →
  `0x8252106B`; the first configuration and patterns with `SET_LOG_CONFIG(4, 3)` →
  `0x7EA17539`; the first configuration and patterns with `SET_T_PM(40)` → `0x2DBB98CB`,
  and with `SET_LOG_CONFIG(4, 3)` after it → `0x6A66BE09`.

## Command rules and sequences

- Every host → client command gets exactly one response: `CONNECT_RESPONSE` for
  `CONNECT`, `COMMAND_RESPONSE` with `request_type` = the command ID for all others
  (including `SET_*` and `APPLY_CONFIG`). The host sends one command at a time.
- Commands other than `CONNECT` before a successful connect → `BAD_STATE / NOT_CONNECTED`.
- `SET_*` and `APPLY_CONFIG` while running → `BAD_STATE / BUSY`; while a Bluetooth
  link, scanning or advertising is active → `BAD_STATE / LINK_ACTIVE`.
- `LINK_DISCONNECT` is confirmed after the disconnect (or immediately without a link),
  followed by `CLIENT_STATE(LINK_DISCONNECTED)`. While CS procedures run it stops them
  first, like `STOP` (`CLIENT_STATE(STOPPED, INTERRUPTED, -ECANCELED)`), so no `STOP` is
  needed before it. The radio test build has no link: it answers `OK` and leaves a running
  test to `STOP` or `CLOSE_SESSION`.
- `START` without an applied configuration → `BAD_STATE / MISSING_CONFIG`; with a
  different `config_crc32` → `CONFIG_MISMATCH`.
- `SET_*_CONFIG` values are validated immediately, so a bad field is rejected at that command.
- `STOP` is confirmed after procedures are disabled and, in the initiator role, the
  last real-time RAS data has arrived or timed out (`OK / STOP_TIMEOUT`).
- `GET_CONFIG` is allowed in every state. `CLIENT_STATE`, `RAS_DATA_LOST`,
  `RADIO_TEST_STATS`, `CS_PROCEDURES_COMPLETE`, `CS_PEER_DATA` and
  `CONNECTION_PARAMETERS` are unsolicited and never replace a response.
- Radio RX and RX sweep tests send `RADIO_TEST_STATS`: a baseline after the `START`
  response, periodic reports, and a final report before the `STOP` response or
  `CLIENT_STATE(STOPPED, TEST_COMPLETE)`. Counters are cumulative since `START`.
- An interrupted operation ends with `CLIENT_STATE(STOPPED, INTERRUPTED, error)`:
  - `STOP` before a finite test completed (radio test `packet_count`): `-ECANCELED`; the
    `STOP` response stays `OK`. Stopping a continuous test is a plain `STOPPED`.
  - `CLOSE_SESSION` while running: the client stops the operation, `-ECANCELED`.
  - Host port closed (DTR dropped) while running: the client stops the operation, `-ENOTCONN`.
  - `CLOSE_SESSION` or a closed port during a CS setup (`LINK_CONNECTED`, `RAS_READY`): the
    client cancels the setup, `-ECANCELED`. Scanning, advertising and a connection attempt
    are stopped as by `STOP` (`CLIENT_STATE(LINK_DISCONNECTED)`); an established link is kept.
- A failure that aborts a running operation (failed stop, aborted procedure) is
  `CLIENT_STATE(ERROR, INTERRUPTED, error)` with the errno and, if any, `hci_status`.
- A `CLIENT_STATE` with an error sent while no session was open is sent again right after the
  next successful `CONNECT_RESPONSE`, so the host learns why the previous run ended.

```
CONNECT                  -> CONNECT_RESPONSE(OK, supported_modes, config_valid, config_crc32)
    (host compares config_crc32 with its own)

  either apply the host configuration:
[STOP]                   -> COMMAND_RESPONSE      only if running; closes the run
[LINK_DISCONNECT]        -> COMMAND_RESPONSE      only if a link, scan or advertising is active
SET_OPERATION_MODE       -> COMMAND_RESPONSE
SET_<mode>_CONFIG        -> COMMAND_RESPONSE
SET_PERIPHERAL_PATTERNS  -> COMMAND_RESPONSE      (CS modes, GAP central only)
[SET_DEVICE_NAME]        -> COMMAND_RESPONSE      (CS modes)
[SET_PEER_DATA]          -> COMMAND_RESPONSE      (CS initiator, reflector data none)
[SET_T_PM]               -> COMMAND_RESPONSE      (CS initiator, T_PM 20 or 40 us)
[SET_LOG_CONFIG]         -> COMMAND_RESPONSE      (any mode, levels other than the defaults)
APPLY_CONFIG             -> COMMAND_RESPONSE(config_crc32)   host checks CRC == its own

  or take the client configuration:
GET_CONFIG               -> SET_OPERATION_MODE, SET_<mode>_CONFIG, [SET_PERIPHERAL_PATTERNS],
                            [SET_DEVICE_NAME], [SET_PEER_DATA], [SET_T_PM],
                            [SET_LOG_CONFIG], COMMAND_RESPONSE(config_crc32)

START(config_crc32)      -> COMMAND_RESPONSE      then CLIENT_STATE, reports, CS_FAE_TABLE
STOP                     -> COMMAND_RESPONSE      procedures disabled, link kept, run closed
CLOSE_SESSION            -> COMMAND_RESPONSE      host session ends
```

Any rejection aborts the sequence on the host; nothing after it is sent. Enforcing
these rules is application work (`host_link`); this library only defines the frames.

## API

Fill the message fields of a complete frame, then finalize it in place:

```c
struct cs_protocol_operation_mode_frame_t frame = {
    .mode = CS_PROTOCOL_MODE_CS_INITIATOR,
};
int len = cs_protocol_finalize_frame(&frame, sizeof(frame),
                                     CS_PROTOCOL_PACKET_SET_OPERATION_MODE);
/* Send len bytes from &frame if len >= 0. */
```

`cs_protocol_finalize_frame` writes only sync, size, type, CRC and end sync.
It does not interpret or convert message fields. `cs_protocol_encode` and
`cs_protocol_encode_parts` alternatively wrap already serialized payload bytes
into a caller-provided output buffer.

On reception, `cs_protocol_decode` validates sync, size, footer and CRC and
returns the decoded type and a view of the payload. `cs_protocol_packet_t.valid`
is cleared at the start of every decode and set only when all checks pass. The application then checks
the type-specific frame size and field values before reading the corresponding
frame and populating its utility structs. The generic decoder accepts unknown
message IDs; the application decides which ones it supports. The UART parser
supports fragmented and consecutive frames; it performs framing, not application
command sequencing.

There are no per-message encoders, converters, apply callbacks or client state
objects. `cs_protocol_packets.h` is definitions only; `cs_protocol.c` implements
the generic wrapper and stream parser.

The matching Python implementation is in [`python/cs_app/protocol`](../../../python/cs_app/protocol).
It provides the generic frame codec, packet dataclasses, `ClientConfig` (configuration
CRC, send order, `GET_CONFIG` reply parsing), incremental receiver, and JSON-driven
transmitter.

## Checks

Frame sizes and footer offsets are checked at compile time by the `_Static_assert`s in
`cs_protocol_packets.h`. `sh tests/host_link/run.sh` builds `cs_protocol.c` natively with
the host link configuration store and checks the shared configuration CRC vector, using
strict compiler warnings, AddressSanitizer and UndefinedBehaviorSanitizer with test-only
Zephyr byte-order and CRC substitutes (`tests/host_link/include/`). The Python tests
(`python/tests/test_protocol.py`) cover frame sizes, round trips and known payload bytes.
None of these exercise hardware.

### Optional local Bluetooth name

`SET_DEVICE_NAME` = `0x010C`, 45-byte frame, payload `u8 length; u8 name[32]`.
The name is 1–32 valid UTF-8 bytes, no NUL, with zero padding. CS modes only.
Stage after the mode/configuration; send and replay after optional peripheral
patterns, and append the 33 payload bytes to the configuration CRC after the patterns
and before the peer data and log configuration. The name
uses the same BUSY/LINK_ACTIVE guards as other configuration changes. Omission
in the next applied set restores the firmware default and leaves legacy CRCs
unchanged. It is the local name, not the remote scan prefix.

### Reflector data (protocol 0x0007)

With IPT the initiator's own phase correction terms carry the full two-way phase, so a CS
initiator can run without the reflector's data (`docs/Bluetooth_CS_Inline_Phase_Transfer.tex`).

- `SET_PEER_DATA` (`0x0110`, 13 bytes, payload `u8 peer_data`) is optional configuration
  of the CS initiator mode. Without it the initiator receives the reflector's subevents
  through RAS real-time, so only `1` (none) is accepted (`REJECTED / VALUE_OUT_OF_RANGE`
  otherwise) and each configuration has one byte representation. Other modes:
  `REJECTED / MODE_MISMATCH`; before `SET_OPERATION_MODE`: `BAD_STATE / MISSING_CONFIG`.
  `SET_OPERATION_MODE` discards it with the rest of the staging area.
- `APPLY_CONFIG` rejects reflector data none without the IPT bit in the staged initiator
  configuration: `REJECTED / VALUE_OUT_OF_RANGE`, `error` -22 (`-EINVAL`).
- `CS_PEER_DATA` (`0x000F`, 13 bytes) is sent by a CS initiator (`cs_client` and
  `cs_hostless_initiator`) after each successful `CS_CONFIGURATION`, before the first
  subevent. The hostless initiator resends it with its cached link records when the host
  opens the port: a hostless host has no applied configuration, and `CS_CONFIGURATION`
  does not carry the setting.
- With none, the initiator sends no `CS_REFLECTOR_SUBEVENT_RESULT` and no `RAS_DATA_LOST`,
  and does not report `RAS_READY`: `LINK_CONNECTED` is followed by `RUNNING`. `STOP` never
  answers `STOP_TIMEOUT`.
- If the peer does not support IPT in the reflector, or the created configuration does not
  enable it, setup ends in `CLIENT_STATE(ERROR, PEER_IPT_UNSUPPORTED, error -134
  (-ENOTSUP))`. The initiator does not fall back to RAS: the configured procedure interval
  may be too short for its traffic.

### Preferred T_PM (protocol 0x0009)

T_PM is the phase measurement period of each mode-2 and mode-3 tone: 10, 20 or 40 µs
(40 mandatory). The initiator's controller chooses it at LE CS Create Config, and
`CS_CONFIGURATION` reports the value in use (`t_pm_time_us`).

- `SET_T_PM` (`0x0112`, 13 bytes, payload `u8 t_pm_us`) is optional configuration of the
  CS initiator mode. Without it the initiator prefers 10 µs, so only `20` and `40` are
  accepted (`REJECTED / VALUE_OUT_OF_RANGE` otherwise) and each configuration has one
  byte representation. Other modes: `REJECTED / MODE_MISMATCH`; before
  `SET_OPERATION_MODE`: `BAD_STATE / MISSING_CONFIG`.
- The initiator passes the preference to its controller before every LE CS Create
  Config (SoftDevice Controller vendor command CS Params Set), so a configuration without
  the frame goes back to 10 µs. The controller uses it when both devices support it,
  otherwise a T_PM both support; the reflector needs no setting.
- Hostless initiators take it from the planner export
  (`cs_initiator_config_set_t_pm()`).

### Negotiated ACL connection parameters and ATT MTU (protocol 0x000B)

`CONNECTION_PARAMETERS` (`0x0010`, 20 bytes) is an unsolicited client-to-host
report containing the actual ACL interval (1.25 ms units), peripheral latency
(ACL events), supervision timeout (10 ms units), and negotiated ATT MTU in bytes. It is sent after a hosted
USB session opens when a Bluetooth link exists. The hostless initiator caches
the latest values and resends them with its other link records whenever USB DTR
rises; ACL or ATT updates replace the cached value and produce another report.

### Log levels (protocol 0x0008)

The client's log messages (`common/libs/app_log/README.md`) go to two consumers, each
with its own level: the console (debug UART or RTT) and `LOG_MESSAGE` frames. Levels use
Zephyr numbering: 0 off, 1 error, 2 warning, 3 info, 4 debug; a consumer receives its
level and the ones below it.

- `SET_LOG_CONFIG` (`0x0111`, 14 bytes, payload `u8 console_level; u8 protocol_level`) is
  optional configuration of every operation mode, staged after `SET_OPERATION_MODE`
  (before it: `BAD_STATE / MISSING_CONFIG`). Without it the client uses the defaults,
  console 3 (info) and protocol 2 (warning), so a payload equal to the defaults is
  rejected, as is a level above 4 (`REJECTED / VALUE_OUT_OF_RANGE`): each configuration
  has one byte representation.
- The levels take effect at `APPLY_CONFIG`; a configuration without the frame restores
  the defaults. They follow the configuration rules: they count in the CRC (last),
  `GET_CONFIG` replays them last, and they change only with the Bluetooth link down.
  Changing levels during a run is not supported.
- `LOG_MESSAGE` text is `<lvl> module: text`, `lvl` one of `err`, `wrn`, `inf`, `dbg`,
  at most `CONFIG_APP_LOG_MESSAGE_MAX` bytes (256 by default). Messages are sent only
  while a host session is open.
- Hostless applications take their levels from the planner export
  (`cs_generated_config_log()`). `cs_hostless_initiator` sends `LOG_MESSAGE` frames on its
  report-only USB CDC port, at its exported protocol level.

## Peer discovery (protocol 0x0005)

Apply the CS configuration first. For GAP central, choose **Scan peers**, select
an entry, then **Connect selected peer**. For GAP peripheral, choose **Advertise**.
These commands establish the Bluetooth link separately from measurement START.

| Packet | ID | Payload | Frame bytes |
| --- | --- | --- | --- |
| `SCAN_START` | 0x010D | empty | 12 |
| `PEER_CONNECT` | 0x010E | `address_type:u8`, `address:u8[6]` | 19 |
| `ADVERTISE_START` | 0x010F | empty | 12 |
| `SCAN_RESULT` | 0x000D | `address_type:u8`, `address:u8[6]`, `rssi_dbm:i8`, `flags:u8`, `name_length:u8`, `name:u8[254]` | 276 |

Address type is 0 (public) or 1 (random); bytes use Zephyr/on-air order (reverse
for conventional colon-separated display). Names are the actual advertised bytes,
zero padded after `name_length`; absent names have length 0. The display decodes
UTF-8 with replacement for malformed bytes. Flags: bit 0 connectable, bit 1 complete
name; other bits reserved. Reports include unnamed and nonconnectable peers as well
as peers outside configured name patterns; the host filters by prefix. Advertisement/scan-response updates merge
by address/type, preserve complete names, and update RSSI. Equal names never merge
different addresses. Names learned from scan responses are reported too. A new scan
clears the host list; selection requires a connectable entry from the current scan.
A private address that rotates appears as a new entry; names are not identities.

All commands receive `COMMAND_RESPONSE`. Discovery requires an applied CS config,
the matching GAP role, and no existing link/connection attempt; PEER_CONNECT can stop
an active scan. Radio-only builds answer UNSUPPORTED. PEER_CONNECT acknowledges
acceptance of the attempt; `CLIENT_STATE(LINK_CONNECTING=0x0B)` and then
`LINK_CONNECTED` or `ERROR` report its outcome. The firmware also accepts an explicit
address/type without a preceding scan. No automatic connection to the first match.
Configuration changes remain blocked during discovery, connection attempts and links.

Firmware defaults: active scan interval 60 ms, window 30 ms; extended connectable
advertising interval 100–150 ms, complete configured Bluetooth name (up to 32 bytes).
Scan and advertising have no automatic timeout. STOP or LINK_DISCONNECT cancels
discovery; LINK_DISCONNECT also disconnects a link, waiting up to 3 s. Connection
attempt timeout is 10 s. Session close/USB loss cancels discovery and disconnects.
A bounded queue moves scan reports off the Bluetooth callback thread; overflow and
serial report loss are logged. Rescanning/repeated advertisements can recover an update
lost under load; delivery of every RF advertisement is not guaranteed.

Connection success requests security level L2 (encryption without MITM). Failures
are reported to Python as `CLIENT_STATE(ERROR, reason, hci_status, error)` and a
failed command response for synchronous failures; there are no automatic retries.
New reason values: SCAN_FAILED 0x0D, ADVERTISE_FAILED 0x0E, CONNECT_FAILED 0x0F,
SECURITY_FAILED 0x10, RAS_DISCOVERY_FAILED 0x11, CS_CONFIG_FAILED 0x12,
CS_SECURITY_FAILED 0x13. HCI status is populated only for an actual HCI status;
Zephyr pairing errors are logged separately, with SECURITY_FAILED / -EACCES on the
state frame. A security failure disconnects the link and preserves ERROR. The host
explicitly disconnects any remaining link and retries. Future RAS discovery/config/
CS security callbacks must use these same fail-and-wait rules (including existing
RAS_NO_REALTIME); those callbacks remain part of the unfinished CS/RAS sequence.

These are runtime commands, not configuration payloads: configuration CRCs and saved
plans do not change. C and Python must both use protocol version 0x000B. Existing packet
layouts remain decodable, including legacy 18-byte connection reports, which decode with
`mtu = 0`. The simulator provides three named peers, including two
with the same name, and supports scan, select, advertise and cancel.
