# Saved session HDF5 and MATLAB organization

This document describes the recording format produced by cs_app, including files
created by **Save session…**, ordinary run recordings, and their MATLAB exports. The
HDF5 writer is implemented in
[python/cs_app/recorder.py](python/cs_app/recorder.py), and MATLAB conversion is
implemented in [python/cs_app/h5_to_mat.py](python/cs_app/h5_to_mat.py).

The current on-disk format is HDF5 format_version = 1. A saved session and a normal
run recording use the same HDF5 schema, so both can be opened by **Open capture…**,
replayed by cs-app --simulate, or converted to MATLAB.

## 1. What a saved session contains

A session is the ordered stream of protocol frames and host-side messages belonging to
one host session. The application keeps that stream in temporary, disk-backed history
segments even when **Record each run** is disabled. **Save session…** replays the kept
history through RunRecorder, producing a normal HDF5 file.

The saved file can contain:

- received protocol frames;
- sent host-command frames;
- host and peer-console messages;
- decoded analysis-oriented tables for supported received packets;
- the applied host configuration when one exists;
- negotiated controller reports and other context;
- root metadata describing source, mode, timing, closure, and optional notes.

The temporary history is bounded. If its oldest segments have been dropped, the saved
file remains valid but is explicitly marked as truncated by the root attributes
history_truncated and, when available, history_first_timestamp.

The save operation runs in the background. A failed or cancelled save removes the
partial HDF5 file. A saved session uses source = "session"; an ordinary run recording
uses source = "run".

### File names and companion configuration

Normal recordings are named using operation mode and start time, for example:

~~~text
cs_initiator_14_Sep_2026_13_05_22.h5
~~~

Saved sessions use the session_ prefix:

~~~text
session_<mode>_<start time>.h5
~~~

The application never replaces an existing HDF5 file; a __2, __3, … suffix is added
when necessary. For configured CS sessions, a planner/configuration JSON file is also
written beside the HDF5 file as:

~~~text
config_<hdf5-stem>.json
~~~

The JSON is a convenient reloadable preset. The HDF5 file also contains the exact
planner JSON in /config/planner_scenario when /config is present.

## 2. General HDF5 conventions

### 2.1 Dataset layout

Most records are one-dimensional, append-only, resizable compound datasets:

~~~text
dataset[row].field
~~~

They are created with HDF5 chunking and an unlimited first dimension. A dataset is
usually created lazily when the first corresponding packet arrives, so an absent table
means “no packet of this type was recorded”; it does not necessarily mean that the
format does not support the table.

Scalar configuration values are ordinary scalar datasets. String datasets use UTF-8
variable-length HDF5 strings. Variable-length byte fields use arrays of uint8.
Fixed byte arrays, such as a 10-byte CS channel map, remain rectangular fixed-size
uint8 fields inside a compound row.

### 2.2 Common timing and index fields

The field name rx_index is retained for compatibility, but it is the recorder's
monotonic record index, not an RX-only counter. It is assigned to both rx and tx
frames and to host-log records. The index is incremented in the order records enter
the recorder queue.

t_host is a relative host time in seconds, measured from creation of that recorder.
It is the timestamp captured by the transport/application thread, not the time at
which the HDF5 worker happens to write the row. Values are clamped to zero if the
supplied timestamp predates recorder start. Context rows written directly by an
ordinary RunRecorder are stamped with t_host = 0.

Unless a narrower type is explicitly required, decoded integer fields are stored as
little-endian signed 64-bit integers (<i8). Important explicit exceptions are:

- /raw/frames.packet_type: little-endian unsigned 16-bit (<u2);
- /raw/frames.rx_index: little-endian unsigned 64-bit (<u8);
- /raw/frames.data: variable-length uint8;
- /host_log, /fae, and /radio_test/stats use explicit unsigned/signed widths;
- fixed byte arrays use uint8 with their declared length.

Generic decoded tables are generated from Python integer values and therefore normally
show <i8 even when the original wire field was narrower. The raw frame remains the
authoritative representation when original wire width or signedness matters.

### 2.3 HDF5 tree

A typical file has this shape:

~~~text
/
├── root attributes                     metadata; see §3
├── config/                             optional applied host configuration
│   ├── operation_mode
│   ├── peer_data
│   ├── t_pm
│   ├── log
│   ├── cs_config                       CS initiator/reflector row, or …
│   ├── radio_test_config               … radio-test configuration row
│   ├── device_name                     optional UTF-8 scalar
│   ├── payloads                        variable-length uint8 payloads
│   ├── peripheral_patterns             UTF-8 string array
│   └── planner_scenario                UTF-8 JSON scalar
├── context/                             optional typed pre-run snapshots
├── host_log                             optional host/peer messages
├── raw/
│   └── frames                           complete wire frames, both directions
├── reports/                             decoded link/controller reports
│   ├── capabilities
│   ├── configuration
│   ├── procedure_enable
│   ├── peer_data
│   └── connection_parameters
├── radio_test/
│   └── stats                             radio RX statistics
├── fae                                   decoded FAE tables
├── events                                command/state/error/completion events
├── log                                   client LOG_MESSAGE text
└── results/
    ├── subevents                         one row per CS subevent
    ├── steps                             flattened CS steps
    └── tones                             flattened tone measurements
~~~

The root attributes are attached to /, not stored as a dataset named root attributes.

## 3. Root attributes

Root attributes are scalar metadata. HDF5 readers should tolerate additional
attributes because application metadata is copied into the root from the recorder's
metadata argument.

| Attribute | Meaning |
| --- | --- |
| format_version | HDF5 schema version; currently 1. |
| created | UTC ISO-8601 creation time of the HDF5 file. |
| app_version | Application version; current writer value is 0.1.0. |
| source | "run" for an ordinary recording, "session" for Save session…. |
| partial | Whether the file was started as a partial/record-from-now stream. |
| history_truncated | true when temporary session history dropped old segments. |
| history_first_timestamp | Relative time of the first retained history record; present only when applicable. |
| close_reason | Closure reason, initially "unclosed", then replaced when the writer closes. |
| description | User-entered UTF-8 notes; may contain newlines. |
| description_updated | UTC ISO-8601 time of the last post-run description update, or an empty string. |
| operation_mode | Numeric mode: 0 CS initiator, 1 CS reflector, 2 radio TX/RX test, 3 hostless CS. |
| config_crc32 | CRC-32 of the applied ClientConfig; 0 when no host configuration is available. |
| protocol_version | Host protocol version, when supplied by the application. |
| firmware_version | Client firmware version, when known. |
| port | Serial/simulator port identifier, when supplied. |
| baud | Serial baud rate, when supplied. |
| run_number | Application run counter for ordinary recordings. |
| link_number | Link counter used to identify successive Bluetooth links for FAE rows. |

protocol_version, firmware_version, port, baud, run_number, link_number, and future
application metadata are not required for a minimal reader. The writer copies
non-reserved metadata keys through as root attributes.

description can be changed after a file is closed without rewriting frame data. The
application reopens the file in append mode and updates both description and
description_updated.

## 4. Configuration organization: /config

/config is present for a configured hosted recording or saved session. A hostless
saved session has no host-side configuration, so /config is intentionally omitted;
its negotiated controller information is available under /reports and in the raw
stream.

The group is also omitted when a caller explicitly creates a RunRecorder with
write_config = False.

### 4.1 Scalar and vector datasets

| Path | Shape/type | Meaning |
| --- | --- | --- |
| /config/operation_mode | scalar integer | Applied operation mode. |
| /config/peer_data | scalar integer | Initiator reflector-data selection: 0 RAS real-time data, 1 initiator-only data. |
| /config/t_pm | scalar integer | Preferred CS phase-measurement period in microseconds. Default is 10 when no explicit request was sent. |
| /config/log | uint8[2] | [console_level, host_level], each 0 off through 4 debug. |
| /config/device_name | UTF-8 scalar, optional | Bluetooth device name when configured. |
| /config/payloads | 1-D vlen uint8 | Exact configuration payloads sent to the client, one payload per row, in ClientConfig.packets() order. These are payload bytes only, not complete framed packets. |
| /config/peripheral_patterns | 1-D UTF-8 string array | Active GAP peripheral-name prefixes used during discovery. |
| /config/planner_scenario | UTF-8 scalar | Planner and host-settings JSON document; empty for radio-test configurations. |

The /config/log dataset also carries the attributes console_level and host_level,
duplicating its two values for convenient attribute-based inspection.

| Value | Level |
| ---: | --- |
| 0 | off |
| 1 | error |
| 2 | warning |
| 3 | info |
| 4 | debug |

### 4.2 /config/cs_config

/config/cs_config is a one-row compound dataset for either
CsInitiatorConfigPacket or CsReflectorConfigPacket. Its packet_type attribute
identifies which packet was recorded: 0x0101 for initiator or 0x0102 for reflector.
The common fields are:

~~~text
gap_role
config_id
connection_interval_min
connection_interval_max
connection_latency
connection_timeout
cs_sync_antenna_selection
max_tx_power
max_procedure_len
min_procedure_interval
max_procedure_interval
max_procedure_count
min_subevent_len
max_subevent_len
tone_antenna_config_selection
phy
tx_power_delta
preferred_peer_antenna
snr_control_initiator
snr_control_reflector
~~~

An initiator row additionally contains:

~~~text
creation_mode
creation_min_main_mode_steps
creation_max_main_mode_steps
creation_main_mode_repetition
creation_mode_0_steps
creation_rtt_type
creation_cs_sync_phy
creation_channel_map              uint8[10]
creation_channel_map_repetition
creation_channel_selection_type
creation_ch3c_shape
creation_ch3c_jump
creation_cs_enhancements_1
creation_context
~~~

All scalar fields in this decoded table are normally <i8; the channel map is a fixed
10-element uint8 array.

### 4.3 /config/radio_test_config

Radio-test recordings use /config/radio_test_config instead of /config/cs_config.
Its packet_type attribute is 0x0103. The one-row fields are:

~~~text
test_type
phy
channel
txpower
pattern
packet_count
sweep_start_channel
sweep_end_channel
sweep_delay_ms
duty_cycle
tx_time_us
sleep_time_us
fem_ramp_up_time_us
fem_tx_power_control
~~~

The configuration packet's enums and units are defined by the corresponding protocol
packet class; the HDF5 table preserves field names but does not replace enum values
with strings.

## 5. Pre-run context: /context

For an ordinary RunRecorder recording, the application passes the latest known link
context at recorder creation. These typed rows are written at t_host = 0 and are
separate from the live raw-frame stream. They make a normal run file self-describing
even if the link reports that established the context arrived just before recording
started.

Typical paths are:

| Path | Contents |
| --- | --- |
| /context/capabilities | Latest local/remote CS capabilities. |
| /context/configuration | Latest controller-created CS configuration. |
| /context/procedure_enable | Latest selected CS procedure parameters. |
| /context/fae | Latest FAE table; has the same channels annotation as /fae. |

The schemas are the same as the corresponding typed tables described in §7. A context
table may be absent or empty when no such report was available.

### Saved-session nuance

Save session replays the temporary history into RunRecorder. The temporary history
itself is seeded with context packets, but those packets are replayed as normal
received records. Consequently, in a saved session those seeded packets are present
in /raw/frames and in their normal decoded destinations, such as
/reports/configuration or /fae, rather than being written a second time under
/context. The /context group still exists because the common writer creates it, but
it can be empty.

This is intentional: the saved session is a complete replayable timeline, while an
ordinary run recording uses /context for pre-run snapshots that were not themselves
part of the recorded run stream.

## 6. Raw frames: /raw/frames

/raw/frames is the lossless replay source. It contains both directions:

| Field | HDF5 type | Meaning |
| --- | --- | --- |
| rx_index | <u8 | Recorder sequence index. |
| t_host | <f8 | Relative host time in seconds. |
| direction | fixed S2 | b"rx" for received, b"tx" for sent. |
| packet_type | <u2 | Protocol packet type from the frame header. |
| data | vlen uint8 | Complete validated wire frame, including protocol header, payload, CRC, and end marker. |

The complete frame can be passed to Frame.from_bytes() after converting the vlen array
to Python bytes. It includes the six-byte generic header, packet payload, and six-byte
footer. The packet_type field is duplicated in the table for filtering without
decoding data.

Only received frames are decoded into typed report/result tables. Sent command frames
remain available in /raw/frames, preserving the exact host-to-client conversation
without inventing received measurements from commands.

The load() helper in recorder.py replays received frames by default. Use include_tx=True
for both directions, times=True for timestamps, and include_host=True to include
/host_log records in the merged timeline.

## 7. Host and client text logs

### 7.1 /host_log

/host_log stores host application messages and peer-console messages in the same
relative timeline as protocol frames:

| Field | Type | Meaning |
| --- | --- | --- |
| rx_index | <u8 | Recorder sequence index, including frame and host records. |
| t_host | <f8 | Relative host time in seconds. |
| level | uint8 | 1 error, 2 warning, 3 info, 4 debug. |
| source | UTF-8 vlen string | Origin, commonly host or peer. |
| text | UTF-8 vlen string | Message text. |

Older files without /host_log remain readable. A file can have an empty host log; the
MATLAB converter still emits an empty 1×0 host_log variable when that section is
selected.

### 7.2 /log

/log contains decoded client LOG_MESSAGE packets. Its row fields are:

~~~text
rx_index    integer
t_host      float64 seconds
text        UTF-8 vlen string
~~~

The original message bytes are decoded as UTF-8 with replacement for invalid byte
sequences. Log severity prefixes, when present in the text, are preserved in text; the
HDF5 /log table does not add a separate severity field.

## 8. Decoded reports and events

Typed tables are convenience indexes over received packets. They are not a
replacement for /raw/frames; a future or unknown packet type may exist in the raw
stream without a corresponding typed table.

Every table below starts with common rx_index and t_host fields unless noted
otherwise.

### 8.1 /reports/capabilities

One row per CS_CAPABILITIES report:

~~~text
source
conn_index
num_config_supported
max_consecutive_procedures_supported
num_antennas_supported
max_antenna_paths_supported
initiator_supported
reflector_supported
mode_3_supported
rtt_aa_only_precision
rtt_sounding_precision
rtt_random_payload_precision
rtt_aa_only_n
rtt_sounding_n
rtt_random_payload_n
phase_based_nadm_sounding_supported
phase_based_nadm_random_supported
cs_sync_2m_phy_supported
cs_sync_2m_2bt_phy_supported
cs_without_fae_supported
chsel_alg_3c_supported
pbr_from_rtt_sounding_seq_supported
t_ip1_times_supported
t_ip2_times_supported
t_fcs_times_supported
t_pm_times_supported
t_sw_time
tx_snr_capability
t_ip2_ipt_times_supported
t_sw_ipt_time_supported
cs_ipt_reflector_supported
~~~

Boolean capabilities remain numeric wire values rather than MATLAB logical labels.
source identifies local versus remote capability information, and conn_index identifies
the associated connection; 0xFF is the protocol “no connection” value.

### 8.2 /reports/configuration

One row per controller-completed CS_CONFIGURATION report:

~~~text
id
mode
min_main_mode_steps
max_main_mode_steps
main_mode_repetition
mode_0_steps
role
rtt_type
cs_sync_phy
channel_map_repetition
channel_selection_type
ch3c_shape
ch3c_jump
cs_enhancements_1
t_ip1_time_us
t_ip2_time_us
t_fcs_time_us
t_pm_time_us
channel_map                  uint8[10]
~~~

The 10-byte channel_map is kept in the controller's raw C field order.

### 8.3 /reports/procedure_enable

One row per CS_PROCEDURE_ENABLE_COMPLETE report:

~~~text
config_id
state
tone_antenna_config_selection
selected_tx_power
subevent_len
subevents_per_event
subevent_interval
event_interval
procedure_interval
procedure_count
max_procedure_len
~~~

### 8.4 Other report tables

/reports/peer_data contains peer_data for each CS_PEER_DATA report.

/reports/connection_parameters contains negotiated ACL parameters:

~~~text
interval
latency
timeout
mtu
~~~

`mtu` is the negotiated ATT MTU in bytes. Recordings made with the legacy 18-byte
report may not have this column; readers should treat it as zero when absent.

/radio_test/stats contains radio RX test reports:

| Field | Type | Meaning |
| --- | --- | --- |
| packets_received | <u4 | Cumulative CRC-valid packet count. |
| crc_errors | <u4 | Cumulative detected CRC-error count. |
| rssi_dbm | i1 | Latest RSSI, or 127 when no packet was observed in the interval. |
| channel | uint8 | Channel associated with the report/sample. |

### 8.5 /fae

Each FAE table row contains:

| Field | Type | Meaning |
| --- | --- | --- |
| link_number | <u4 | Bluetooth-link counter at the time of the report. |
| hci_status | uint8 | HCI completion status. Nonzero indicates a failed read. |
| lsb_denominator | uint8 | FAE scale denominator; one entry is 1 / denominator ppm. |
| entries | i1[72] | Signed FAE values in HCI table order. |

The dataset has a channels attribute containing the 72 channel numbers aligned with
entries: channels 2..22 followed by 26..76. FAE rows are raw signed data; ppm and Hz
conversions are analysis operations, not additional HDF5 fields.

### 8.6 /events

Command responses, client-state changes, RAS data-loss notifications, and procedure
completion notifications are normalized into one compound table. It has these fields:

~~~text
kind
request_type
status
reason
error
state
config_crc32
ranging_counter
operation_mode
hci_status
procedures_completed
~~~

Unused fields are filled with sentinel values: -1 for most absent integer fields and 0
for status/error-like fields. kind identifies the original packet class, for example
CommandResponsePacket, ClientStatePacket, RasDataLostPacket, or
CsProceduresCompletePacket.

| Packet kind | Meaningful fields in addition to kind, rx_index, t_host |
| --- | --- |
| CommandResponsePacket | request_type, status, reason, error, config_crc32 |
| ClientStatePacket | state, operation_mode, reason, hci_status, error |
| RasDataLostPacket | ranging_counter, error |
| CsProceduresCompletePacket | procedures_completed |

## 9. Nested CS results

Variable-length subevent packets are normalized into three flat tables so that they
can be read efficiently from NumPy, MATLAB, or other HDF5 clients.

### 9.1 /results/subevents

One row is written per initiator or reflector subevent. In addition to common timing
fields, it contains:

~~~text
role
source
config_id
start_acl_conn_event
procedure_counter
frequency_compensation
reference_power_level
procedure_done_status
subevent_done_status
procedure_abort_reason
subevent_abort_reason
num_antenna_paths
abort_step
num_steps
step_start
~~~

role is 0 for an initiator subevent and 1 for a reflector subevent. source is "RAS"
for reflector data in CS mode 0 and "local HCI" otherwise. step_start and num_steps
define the contiguous range of child rows in /results/steps.

### 9.2 /results/steps

One row is written for each step in a subevent:

~~~text
subevent_row
step_index
mode
channel
flags
aa_quality
bit_errors
rssi
antenna
nadm
measured_freq_offset
time_difference
pct1_i
pct1_q
pct2_i
pct2_q
antenna_permutation_index
tone_start
num_tones
~~~

subevent_row points back to /results/subevents. tone_start and num_tones define the
contiguous child range in /results/tones.

### 9.3 /results/tones

One row is written per decoded tone:

~~~text
step_row
i
q
antenna_path
quality
extension
reserved
~~~

step_row points back to /results/steps. The i and q values are signed phase
correction components; the remaining fields retain controller-derived tone metadata.

### 9.4 Relationship example

The following pseudocode reads all tones belonging to one subevent:

~~~python
subevent = h5["results/subevents"][subevent_index]
steps = h5["results/steps"][
    subevent["step_start"] : subevent["step_start"] + subevent["num_steps"]
]

for step in steps:
    tones = h5["results/tones"][
        step["tone_start"] : step["tone_start"] + step["num_tones"]
    ]
~~~

The recorder appends child rows immediately after their parent, so these ranges are
contiguous. The explicit back-reference fields make integrity checks possible even
after filtering or exporting.

## 10. MATLAB organization

MATLAB files are produced by h5_to_mat.convert(), normally as a .mat file beside the
HDF5 source. The default converter output is compressed MAT v5. The application's
Recording panel exposes section and metadata checkboxes; its compact default selects
config, results, and host_log and omits HDF5 metadata. Direct callers can select other
top-level groups.

### 10.1 HDF5 paths become MATLAB structs

The converter recursively maps HDF5 groups to nested MATLAB structs:

~~~text
HDF5: /reports/configuration/id
MAT:  data.reports.configuration.id

HDF5: /results/subevents/procedure_counter
MAT:  data.results.subevents.procedure_counter

HDF5: /config/t_pm
MAT:  data.config.t_pm
~~~

The top-level MATLAB variable is whatever name the caller gives it after load(); the
HDF5 root is represented by the collection of top-level variables such as meta,
config, reports, and results.

### 10.2 Compound datasets become structs of columns

An HDF5 compound dataset becomes a MATLAB struct whose fields are the compound
fields. For example, /results/steps becomes a struct containing fields such as
subevent_row, channel, tone_start, and num_tones. Each field is a column vector in
the normal MAT v5 representation; fixed-size fields become matrices:

~~~text
N rows, scalar field       -> N×1 numeric vector
N rows, fixed uint8[10]    -> N×10 numeric matrix
one scalar HDF5 dataset    -> MATLAB scalar
UTF-8 HDF5 string          -> MATLAB character array
~~~

This column-oriented layout is the intended analysis interface. The converter does not
translate protocol enums or numeric status codes into text labels.

### 10.3 Metadata and descriptions

When metadata export is enabled, HDF5 attributes are represented by a nested meta
field:

- root attributes become meta.*;
- group attributes become that group's meta.*;
- dataset attributes become a meta field inside that dataset's MATLAB struct.

The top-level description variable is always added as a MATLAB character row, even
when metadata export is disabled. Newlines are preserved. It is intentionally a
MATLAB char array, not a MATLAB string object, for compatibility with older MATLAB
versions and Octave. When the HDF5 description is empty, it is an empty character
array.

With metadata enabled, the same text is also available as meta.description because it
is a root HDF5 attribute.

### 10.4 Special host_log representation

host_log is not exported as a struct of column vectors. It is converted specially to a
1×N MATLAB struct array with exactly these fields:

~~~text
timestamp    relative host time in seconds
level        1 error, 2 warning, 3 info, 4 debug
source       MATLAB char row
text         MATLAB char row
~~~

When there are no host messages, host_log is still present as a 1×0 struct array.
This makes code such as for k = 1:numel(host_log) safe for every recording.

### 10.5 Raw-frame export

/raw is omitted by default because it is a lossless transport archive rather than the
compact analysis representation. It can be included by selecting **Raw wire frames**
in the Recording panel or by passing include_raw=True to a direct conversion when no
explicit group selection is supplied.

When included, the raw compound dataset is recursively converted like other compound
datasets. Its variable-length data field remains byte-oriented and may be loaded by
MATLAB as a cell/object-like collection of byte vectors. For robust frame replay,
HDF5 /raw/frames plus h5read is preferable to the MAT v5 representation.

### 10.6 Selecting sections programmatically

The converter accepts include_groups with top-level HDF5 names such as config,
reports, results, events, log, host_log, context, and raw. It accepts
include_meta=False to omit meta fields. For example:

~~~python
from cs_app.h5_to_mat import convert

convert(
    "session_cs_initiator_14_Sep_2026_13_05_22.h5",
    include_groups={"config", "reports", "results", "host_log"},
    include_meta=True,
)
~~~

If include_groups is omitted, every top-level HDF5 group except raw is selected unless
include_raw=True is also supplied. The special host_log variable is added when the
selected set contains host_log (and for the default all-non-raw export).

### 10.7 MAT v5 size limit and MAT v7.3

MAT v5 variables are limited to approximately 2 GiB. Before reading selected groups,
the converter checks regular dataset storage and HDF5 storage used by variable-length
data. If a selected top-level group reaches the limit, conversion is rejected with
guidance to use MATLAB h5read or MAT v7.3.

MAT v7.3 conversion is available to direct callers with v73=True and requires the
optional hdf5storage package. It is useful for large captures, but HDF5 remains the
canonical lossless format for raw-frame archives.

## 11. Reading examples

### 11.1 Inspect HDF5 layout with Python

~~~python
import h5py

with h5py.File("session.h5", "r") as h5:
    print(h5.attrs["source"])
    print(h5.attrs["close_reason"])

    if "config" in h5:
        print("mode:", int(h5["config/operation_mode"][()]))

    frames = h5["raw/frames"]
    for row in frames[:10]:
        wire = bytes(row["data"])
        print(row["rx_index"], row["t_host"], row["direction"],
              hex(int(row["packet_type"])), len(wire))

    if "results/subevents" in h5:
        subevents = h5["results/subevents"]
        print("subevents:", len(subevents))
~~~

### 11.2 Load MATLAB data

~~~matlab
S = load("session.mat");

disp(S.description)
disp(S.meta.source)

if isfield(S, "results") && isfield(S.results, "subevents")
    counters = S.results.subevents.procedure_counter;
    step_counts = S.results.subevents.num_steps;
end

for k = 1:numel(S.host_log)
    fprintf("[%g] %s: %s\n", S.host_log(k).timestamp, ...
        S.host_log(k).source, S.host_log(k).text);
end
~~~

## 12. Compatibility guidance

Readers should:

1. check format_version before assuming a schema;
2. treat missing groups/datasets as empty data rather than as corruption;
3. read /raw/frames for lossless replay and for packet types that have no typed table;
4. use source to distinguish an ordinary recording from a saved session;
5. check history_truncated before interpreting a saved session as complete;
6. use config_crc32 and /config/payloads when configuration identity matters;
7. use step_start/num_steps and tone_start/num_tones instead of assuming that a
   particular result has a fixed number of steps or tones.

The authoritative field names and wire-level enum definitions remain the protocol
packet classes in python/cs_app/protocol/packets.py and the corresponding C headers
under common/libs/cs_protocol/.
