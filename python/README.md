# Python host: `cs_app`

`cs_app` is the only Python package: one PyQt application that connects to a CS
client over serial (or the built-in simulator), keeps its configuration in sync,
starts and stops runs, shows results and FAE, records runs to HDF5 and converts
recordings to MATLAB files. See [cs_app/README.md](cs_app/README.md) for usage.

```sh
cd python
python -m pip install -e .
cs-app            # or: python -m cs_app
```

## Package layout

```
cs_app/
  app.py, __main__.py        main window and entry point
  session.py, qt_session.py  protocol state machine and its Qt wrapper
  transport.py, simulator.py serial transport and in-memory client
  config_sync.py             host/client configuration comparison
  validation.py              radio test and peripheral-pattern checks
  recorder.py, session_history.py, h5_to_mat.py  HDF5 recording, temporary session history and MAT conversion
  results.py                 result pairing and PBR analysis
  fae.py                     FAE table model
  protocol/                  wire protocol: frame codec, packets, ClientConfig/CRC, receiver
  planner/                   schedule model, CSA channels, packet bridge, C export
  views/                     all Qt widgets (port, general, recording, CS/planner,
                             radio test, results, session timeline, FAE, run bar,
                             sync dialog)
```

Everything outside `views/`, `app.py`, `qt_session.py` and the serial transport is Qt-free, so the
logic is unit-tested without a display.

## Protocol classes

`cs_app.protocol.frame` contains the generic frame codec and incremental stream
decoder. `cs_app.protocol.packets` contains dataclasses matching every frame in
`../common/libs/cs_protocol/cs_protocol_packets.h`. The packet classes contain
only message fields; their `to_frame()` method adds the common header and footer
through `Frame`.

| Class | Matching C definition | Direction | Complete size |
| --- | --- | --- | --- |
| `Frame` | `cs_protocol_header_t` + payload + `cs_protocol_footer_t` | Either | Variable |
| `FrameDecoder` | `cs_protocol_parser_t` behavior | Receive | N/A |
| `OperationModePacket` | `cs_protocol_operation_mode_frame_t` | Host → client | 13 |
| `PeerDataPacket` / `CsPeerDataPacket` | `SET_PEER_DATA` / `CS_PEER_DATA` | Both directions | 13 |
| `CsInitiatorConfigPacket` | `cs_protocol_cs_initiator_config_frame_t` | Host → client | 69 |
| `CsReflectorConfigPacket` | `cs_protocol_cs_reflector_config_frame_t` | Host → client | 46 |
| `RadioTxTestConfigPacket` | `cs_protocol_radio_tx_test_config_frame_t` | Host → client | 37 |
| `PeripheralPatternsPacket` | `cs_protocol_peripheral_patterns_frame_t` | Host → client | 277 |
| `TpmPacket` | `cs_protocol_t_pm_frame_t` (`SET_T_PM`) | Host → client | 13 |
| `LogConfigPacket` | `cs_protocol_log_config_frame_t` (`SET_LOG_CONFIG`) | Host → client | 14 |
| `ApplyConfigPacket` | `cs_protocol_apply_config_frame_t` | Host → client | 12 |
| `CsCapabilitiesPacket` | `cs_protocol_cs_capabilities_frame_t` | Client → host | 46 |
| `CsConfigurationPacket` | `cs_protocol_cs_configuration_frame_t` | Client → host | 40 |
| `CsProcedureEnableCompletePacket` | `cs_protocol_cs_procedure_enable_complete_frame_t` | Client → host | 31 |
| `CsInitiatorSubeventResultPacket` | `cs_protocol_cs_initiator_subevent_result_frame_t` | Client → host | Variable |
| `CsReflectorSubeventResultPacket` | `cs_protocol_cs_reflector_subevent_result_frame_t` | Client → host | Variable |
| `ConnectionParametersPacket` | `cs_protocol_connection_parameters_frame_t` | Client → host | 20 |
| `CsStep` | `cs_protocol_cs_step_decoded_t` | Nested record | 22 + tones |
| `CsTone` | `cs_protocol_cs_tone_decoded_t` | Nested record | 8 |
| `LogMessagePacket` | `cs_protocol_log_message_frame_t` | Client → host | Variable |
| `PacketReceiver` | Generic frame parsing plus packet dispatch | Receive | N/A |

The session frames (`CONNECT`, `START`, `COMMAND_RESPONSE`, `CS_FAE_TABLE`, …) are
listed in `common/libs/cs_protocol/README.md` (Messages).

Packet dataclass fields use the same names and declaration order as the C
message fields. Common `header` and `footer` members are represented once by
`Frame`. All integer fields are Python integers; packing checks their C width
and signedness. Fixed byte arrays are Python `bytes` with the exact C length.
Detailed field units and allowed enum values remain canonical in
`../common/libs/cs_protocol/cs_protocol_packets.h`; every class docstring states its mapping and size.

`to_frame()` returns a generic frame, `to_bytes()` returns complete wire bytes,
and `from_frame()` validates packet type and payload size before unpacking.
`decode_packet()` selects the matching class for a validated `Frame`. Unknown
packet IDs remain generic frames so a newer sender does not stop the receiver.

## Runtime logging

**Configuration → General → Client log** selects independent Console and Host consumers at Off,
Error, Warning, Info or Debug. The firmware defaults are Info for the console
and Warning for `LOG_MESSAGE`; the default pair is omitted from the staged
configuration. Non-default levels are sent as `SET_LOG_CONFIG`, replayed by
`GET_CONFIG`, included last in the configuration CRC, and recorded at
`/config/log`. `LOG_MESSAGE` frames feed the Session tab (with the level of
their `<err>`/`<wrn>` prefix) and HDF5 `/log`, including receive-only hostless
sessions.

## Tests

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

## Radio RX measurements

Select **Radio test**, configure **RX** or **RX sweep**, apply and start. The
**Radio RX results** tab displays RSSI, valid RX packets/s, CRC failure percentage,
estimated undetected drops/s, cumulative valid/CRC counters, reported channel and
report interval. Live plots retain the last 5,000 reports; HDF5 retains every report.
Each new Start clears the live history. The session toolbar's **Open capture…** replays
a radio HDF5 file using its original host timestamps, and **Clear** drops what the view holds. The existing Recording controls save each run
and convert it to MAT (`radio_test.stats`).

Set **Expected TX rate** only if the transmitter's packet rate during RX listening
is known. Estimated undetected drops/s = max(0, expected TX rate − valid RX rate −
CRC failure rate). CRC failure percentage uses valid + failed detected packets as
its denominator; it is not total packet loss. Unknown TX rate leaves drops unavailable.
These estimates use intervals between reports, exclude the first baseline and counter
resets, and can be affected by serial delivery timing. RX sweep reports can span multiple
channels; the channel graph is the reported channel, not a per-channel packet count.
The expected rate is an analysis setting, not a firmware configuration or recorded fact.

**Wire format:** `RADIO_TEST_STATS = 0x000C` (`struct cs_protocol_radio_test_stats_frame_t`)
with payload `<IIbB` (10 bytes; 22-byte framed packet): `packets_received: u32`,
`crc_errors: u32`, `rssi_dbm: i8`, `channel: u8`. Counters are cumulative since START,
across sweep channels, modulo 2³²; received counts CRC-valid packets only. RSSI is the
latest packet (valid or failed CRC) since the previous report, sampled at its address,
or 127 if none arrived; the channel is that packet's channel, or the tuned channel.
The `cs_client` radio test build sends a baseline after the START response, a report
every `CONFIG_CS_CLIENT_RADIO_TEST_STATS_INTERVAL_MS` (250 ms), and a final report
before the STOP response or `CLIENT_STATE(STOPPED, TEST_COMPLETE)`. Counter decreases
beyond the half-range rollover rule are treated as resets.

`cs-app --simulate` exercises RX, finite RX completion and continuous RX sweep without
hardware. Select RX and enter 100 packets/s to explore the simulated drop estimates.
A capture passed to `--simulate capture.h5` replays its RX reports once in radio RX mode;
use the session toolbar's **Open capture…** for analysis with the original capture timing.

Raw statistics are stored at `/radio_test/stats` with `rx_index`, `t_host`,
`packets_received`, `crc_errors`, `rssi_dbm`, and `channel`, and also in `/raw/frames`.
Derived rates/drop estimates are calculated in the view rather than stored as measurements.

## Bluetooth device name

**Configuration → General → Bluetooth name** sets the connected board's own Bluetooth name for
CS initiator/reflector mode. Leave it blank to use the firmware default (`CS Client`).
Names support 1–32 UTF-8 bytes, without NUL; multibyte characters count by bytes.
Apply sends the name with the configuration, and editing it makes the configuration
out of sync until applied. General is locked while running. Radio test mode disables
the field and excludes it from the radio configuration.

The name is saved in planner `host_settings.device_name`, restored by Open/Get
configuration, and recorded in `/config/device_name` (also available in MAT).
Generated C exports provide `cs_generated_config_device_name()` and include the
name in their configuration CRC; hostless applications should apply this getter's
non-NULL value before advertising. The GAP role is selected under **Configuration → General → GAP role**;
remote device scan prefixes (**Configuration → General → Scan prefixes**) and the Scan/Connect peer
controls are shown only for GAP central, and Advertise only for GAP peripheral.

This requires firmware supporting `SET_DEVICE_NAME` (`0x010C`): a 33-byte payload,
`length: u8` followed by `name: u8[32]`, padded with zero bytes (45-byte frame).
It is the optional final configuration payload, after peripheral patterns, in
send/GET_CONFIG/CRC order. Omitting it restores the firmware default and keeps
legacy CRCs unchanged. Older firmware rejects a nonempty name instead of silently
ignoring it. The Bluetooth client now enables dynamic device names and applies
`bt_set_name()` before committing its configuration.

## Reflector data and IPT

Planner `host_settings.peer_data` is `0` for RAS real-time reports or `1` for
initiator-only reports. The latter requires a CS initiator configuration with
IPT requested. It is the optional final configuration payload and is included
in the configuration CRC. The control is *CS modes → Reflector data*, directly
below *Inline PCT transfer (IPT)*; it is enabled only for a CS initiator with IPT
requested, and exports call `cs_initiator_config_set_peer_data(config,
CS_CONFIG_PEER_DATA_NONE)`. `CS_PEER_DATA` reports the applied choice once per
link; Results also take it from the applied configuration, so a reconnect to an
established link still analyses initiator-only procedures. Recordings store it in
`/config/peer_data` and `/reports/peer_data`. In a *both* export the reflector
file notes that the initiator runs without RAS.

Analysis with IPT (`docs/Bluetooth_CS_Inline_Phase_Transfer.tex`): the
reflector has already rotated its tones, so the initiator PCT carries the
two-way phase and the reflector reports amplitude only (Q zero, I
non-negative). Initiator-only procedures are complete with the initiator's
reports, use unit reflector amplitude and the initiator's tone quality, and show
RTT as unavailable. With RAS, the reflector's I is the amplitude; a non-zero Q
or a negative I is shown as an IPT protocol violation and that tone is dropped
by the high-quality filter. The frequency-offset delay uses T_SW_IPT from the
capabilities instead of T_SW.

When `CONNECT_RESPONSE` reports a running client (possible only on a port without
DTR; a USB CDC client stops its run when the host goes away), `cs-app` fetches the
client's configuration with `GET_CONFIG`, loads it into the views and warns which
settings differ from its own. It does not stop the run.

## Preferred T_PM (protocol 0x0009)

T_PM is the phase measurement period of each tone slot. The host has no HCI
parameter for it: the controllers select it during the CS Configuration
procedure. The SoftDevice Controller does accept a preference through its
vendor command CS Params Set, which the firmware applies before every LE CS
Create Config, so `SET_T_PM` (`0x0112`, `t_pm_us: u8`, 13-byte frame) makes it a
client setting of the CS initiator.

Planner `host_settings.t_pm` holds it. 20 and 40 µs are sent; 10 µs is the
controller's own preference and sends nothing, so each configuration has one
wire representation and configurations without it keep their CRC. The payload
sits between the reflector data and the log configuration in send, `GET_CONFIG`
and CRC order. The control is *CS modes → Preferred T_PM*, below *Reflector
data*; it is enabled only for a CS initiator with Mode 2 or 3, and selecting 20
or 40 µs also sets the example T_PM so the prediction follows the request.
Exports call `cs_initiator_config_set_t_pm(config, CS_CONFIG_T_PM_40_US)`.
`CS_CONFIGURATION` still reports the value the controllers actually chose, and
the Controller view compares it against the request; a value the peer does not
support is listed under Compatibility before the run. Recordings store the
request in `/config/t_pm`. Whether a longer T_PM averages better is the
measurement question this setting exists for; `cs-app` provides no analysis for
it.

The standalone `cs_planner` leaves T_PM to the firmware, as it does the
reflector data and log levels, so its exports never call the setter.

## Peer discovery (protocol 0x0007)

Apply the CS configuration first. For GAP central, choose **Scan peers**, select
an entry, then **Connect selected peer**. For GAP peripheral, choose **Advertise**.
The list shows peers whose advertised name starts with one of the applied scan
prefixes (byte comparison, case-sensitive); **Show all** lists every report,
including unnamed peers and names outside the prefixes.
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
plans do not change. C and Python must both use protocol version 0x000B; existing
packet layouts remain decodable. The simulator provides
three named peers, including two with the same name and one outside the default
`CS` prefix, and supports scan, select,
advertise and cancel.
