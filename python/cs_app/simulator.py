"""Deterministic in-memory client using the installed protocol API unchanged."""
from pathlib import Path
import dataclasses
import random
import time
from .protocol import PROTOCOL_VERSION
from .protocol.config import ClientConfig
from .protocol.frame import Frame, FrameDecoder, ProtocolError
from .protocol.packets import (
    ScanStartPacket, AdvertiseStartPacket, PeerConnectPacket, ScanResultPacket,
    RadioTestStatsPacket, RadioTestType, OperationMode, ProtocolStatus as Status, RejectReason as Reason, ClientState,
    ConnectPacket, ConnectResponsePacket, CommandResponsePacket, OperationModePacket,
    CsInitiatorConfigPacket, CsReflectorConfigPacket, RadioTxTestConfigPacket,
    PeripheralPatternsPacket, DeviceNamePacket, ApplyConfigPacket, GetConfigPacket, StartPacket, StopPacket,
    LinkDisconnectPacket, CloseSessionPacket, ClientStatePacket, CsFaeTablePacket,
    RasDataLostPacket, CsProceduresCompletePacket, CsInitiatorSubeventResultPacket, CsReflectorSubeventResultPacket,
    PeerDataPacket, CsPeerDataPacket, ConnectionParametersPacket, TpmPacket, T_PM_DEFAULT_US, T_PM_VALUES_US,
    LogConfigPacket, LogLevel, LOG_CONSOLE_LEVEL_DEFAULT, LOG_PROTOCOL_LEVEL_DEFAULT, LogMessagePacket,
    PACKET_CLASSES, decode_packet,
)
from .transport import LoopbackTransport
from .validation import (validate_antennas, validate_patterns, validate_preferred_peer_antenna,
                         validate_radio_test)

ECANCELED, ENOTCONN, ERANGE = 140, 128, 34  # Zephyr errno values, not the host's
FINITE_TEST_TYPES = (RadioTestType.MODULATED_TX, RadioTestType.RX, RadioTestType.MODULATED_TX_DUTY_CYCLE)

RTT_CHANNELS = tuple(range(44, 76, 4))
RTT_DISTANCE_M = 2.5
RTT_NOISE_UNITS = 4.0  # per-role time difference noise, 0.5 ns units
# cs_client starts the ATT MTU exchange (CONFIG_BT_GATT_AUTO_UPDATE_MTU), so a simulated
# link settles on its CONFIG_BT_L2CAP_TX_MTU, not on the 23 a link without one keeps.
ATT_MTU_NEGOTIATED = 498


class Simulator:
    def __init__(self, transport=None, *, clock=time.monotonic, capture=None, connect_delay=0,
                 never_connect=False, supported_modes=7, num_antennas_supported=1,
                 peer_ipt_supported=True):
        self.transport = transport or LoopbackTransport()
        self.transport.peer = self.feed
        self.transport.on_close = self.host_lost
        self.undelivered = None
        self.clock = clock
        self.decoder = FrameDecoder()
        self.config = None
        self.log_config = LogConfigPacket(int(LOG_CONSOLE_LEVEL_DEFAULT), int(LOG_PROTOCOL_LEVEL_DEFAULT))
        self.staging = []
        self.connected = False
        self.state = ClientState.IDLE
        self.mtu = ATT_MTU_NEGOTIATED
        self.connect_delay, self.never_connect = connect_delay, never_connect
        self.supported_modes = supported_modes
        self.num_antennas_supported = num_antennas_supported
        self.peer_ipt_supported = peer_ipt_supported
        self.connect_due = None
        self.next_report = clock()
        self.counter = 0
        self.procedures = 0
        self.radio_received = self.radio_crc = self.radio_ticks = 0
        self.radio_last = None
        self.link_number = 0
        self.link_fae_sent = False
        self.link_established = False
        self.capture = []
        self.radio_capture = []
        if capture:
            from .results import load_capture
            self.capture, errors = load_capture(Path(capture).read_bytes())
            if errors:
                raise ValueError("\n".join(errors))
            self.radio_capture = [p for p in self.capture if isinstance(p, RadioTestStatsPacket)]
            self.capture = [p for p in self.capture if isinstance(p, (CsInitiatorSubeventResultPacket, CsReflectorSubeventResultPacket))]

    def send(self, packet):
        self.transport.deliver(packet.to_bytes())

    def reset(self):
        self.config = None
        self.log_config = LogConfigPacket(int(LOG_CONSOLE_LEVEL_DEFAULT), int(LOG_PROTOCOL_LEVEL_DEFAULT))
        self.staging.clear()
        self.connected = False
        self.state = ClientState.IDLE
        self.mtu = ATT_MTU_NEGOTIATED
        self.link_fae_sent = False
        self.link_established = False
        self.decoder.reset()

    def response(self, request, status=Status.OK, reason=Reason.NONE, error=0):
        self.send(CommandResponsePacket(request.PACKET_TYPE, status, reason, error,
                                        self.config.crc32() if self.config else 0))

    def log_message(self, level, module="simulator", text=""):
        """Emit a firmware-shaped LOG_MESSAGE when the host consumer admits it."""
        if (not self.connected or not self.transport.is_open or level <= 0 or
                level > self.log_config.protocol_level):
            return
        labels = {1: "err", 2: "wrn", 3: "inf", 4: "dbg"}
        if level not in labels:
            raise ValueError("log level must be 1 (error) through 4 (debug)")
        self.send(LogMessagePacket(f"<{labels[level]}> {module}: {text}".encode("utf-8")))

    def set_state(self, state, reason=Reason.NONE, error=0):
        self.state = state
        packet = ClientStatePacket(state, self.config.mode if self.config else 255, reason, 0, error)
        # Like the firmware: no report without a session, but an error is delivered after the next CONNECT.
        if self.connected and self.transport.is_open:
            self.send(packet)
            self.undelivered = None
            # As cs_session.c reports on every parameter update: the ACL parameters of the new link.
            link = self.config.config if state == ClientState.LINK_CONNECTED and self.config else None
            if isinstance(link, (CsInitiatorConfigPacket, CsReflectorConfigPacket)):
                self.send(ConnectionParametersPacket(link.connection_interval_min, link.connection_latency,
                                                     link.connection_timeout, self.mtu))
        elif error:
            self.undelivered = packet

    def set_mtu(self, mtu):
        """Change the simulated negotiated ATT MTU and report it on an active link."""
        self.mtu = mtu
        if (self.connected and self.transport.is_open and
                self.state in (ClientState.LINK_CONNECTED, ClientState.RAS_READY,
                               ClientState.RUNNING, ClientState.STOPPED)):
            link = self.config.config if self.config else None
            if isinstance(link, (CsInitiatorConfigPacket, CsReflectorConfigPacket)):
                self.send(ConnectionParametersPacket(link.connection_interval_min, link.connection_latency,
                                                     link.connection_timeout, self.mtu))

    def link_active(self):
        """As cs_role_link_active(): a link, scan, advertising or connection attempt exists.

        A setup failure (for example PEER_IPT_UNSUPPORTED) leaves ERROR with the link still up.
        """
        return self.link_established or self.state in (
            ClientState.SCANNING, ClientState.ADVERTISING, ClientState.LINK_CONNECTING,
            ClientState.LINK_CONNECTED, ClientState.RAS_READY, ClientState.STOPPED)

    def finite_test_running(self):
        """True while a radio test with a finite packet count has not completed."""
        cfg = self.config.config if self.config else None
        return (self.state == ClientState.RUNNING and self.config.mode == OperationMode.RADIO_TX_TEST
                and bool(cfg.packet_count) and cfg.test_type in FINITE_TEST_TYPES)

    def interrupt(self, error):
        """The host session ended while running: stop and report STOPPED / INTERRUPTED."""
        if self.state == ClientState.RUNNING:
            self.set_state(ClientState.STOPPED, Reason.INTERRUPTED, error)

    def host_lost(self):
        if self.connected:
            self.connected = False
            # Staged configuration is session-local; the applied configuration remains.
            self.staging.clear()
            self.interrupt(-ENOTCONN)

    def connect_response(self):
        self.connected = True
        self.send(ConnectResponsePacket(Status.OK, PROTOCOL_VERSION, self.supported_modes, 0x10000,
                                       65535, bool(self.config), self.config.mode if self.config else 255,
                                       self.config.crc32() if self.config else 0, self.state, self.num_antennas_supported))
        if self.undelivered is not None:
            self.send(self.undelivered)
            self.undelivered = None

    def feed(self, data):
        for frame in self.decoder.feed(data):
            try:
                packet = decode_packet(frame)
            except ProtocolError:
                # Firmware validates frame layouts before connection/state rules.
                known = frame.packet_type in {int(value) for value in PACKET_CLASSES}
                self.send(CommandResponsePacket(frame.packet_type,
                                                 Status.INVALID_FRAME if known else Status.UNSUPPORTED,
                                                 Reason.NONE, 0,
                                                 self.config.crc32() if self.config else 0))
                continue
            self.handle(packet)

    def handle(self, p):
        if isinstance(p, Frame):
            # A validly framed but unknown command is unsupported even before CONNECT.
            self.send(CommandResponsePacket(p.packet_type, Status.UNSUPPORTED, Reason.NONE, 0,
                                             self.config.crc32() if self.config else 0))
            return
        if isinstance(p, ConnectPacket):
            if p.protocol_version != PROTOCOL_VERSION:
                self.send(ConnectResponsePacket(Status.VERSION, PROTOCOL_VERSION, self.supported_modes,
                                                0x10000, 65535, 0, 255, 0, self.state, self.num_antennas_supported))
            elif not self.never_connect:
                if self.connect_delay:
                    self.connect_due = self.clock() + self.connect_delay
                else:
                    self.connect_response()
            return
        if not self.connected:
            self.response(p, Status.BAD_STATE, Reason.NOT_CONNECTED)
            return
        setting = isinstance(p, (OperationModePacket, CsInitiatorConfigPacket, CsReflectorConfigPacket,
                                 RadioTxTestConfigPacket, PeripheralPatternsPacket, DeviceNamePacket,
                                 PeerDataPacket, TpmPacket, LogConfigPacket, ApplyConfigPacket))
        if setting and self.state == ClientState.RUNNING:
            self.response(p, Status.BAD_STATE, Reason.BUSY)
            return
        if setting and self.link_active():
            self.response(p, Status.BAD_STATE, Reason.LINK_ACTIVE)
            return
        if isinstance(p, OperationModePacket):
            if p.mode not in (0, 1, 2) or not self.supported_modes & (1 << p.mode):
                self.response(p, Status.UNSUPPORTED)
                return
            self.staging = [p]
        elif isinstance(p, (CsInitiatorConfigPacket, CsReflectorConfigPacket, RadioTxTestConfigPacket)):
            if not self.staging:
                self.response(p, Status.BAD_STATE, Reason.MISSING_CONFIG)
                return
            try:
                ClientConfig(self.staging[0].mode, p)
            except ValueError:
                self.response(p, Status.REJECTED, Reason.MODE_MISMATCH)
                return
            if isinstance(p, RadioTxTestConfigPacket) and validate_radio_test(p):
                self.response(p, Status.REJECTED, Reason.VALUE_OUT_OF_RANGE, -22)
                return
            antenna_errors = validate_antennas(p, self.num_antennas_supported)
            if antenna_errors:
                # Like host_link_config_check_antennas(): -EINVAL for an unknown encoding, else -ERANGE.
                unknown = any(error.startswith("Unknown") for error in antenna_errors)
                self.response(p, Status.REJECTED, Reason.VALUE_OUT_OF_RANGE, -22 if unknown else -ERANGE)
                return
            if validate_preferred_peer_antenna(p):
                # Like cs_*_config_set_procedure(): -EINVAL.
                self.response(p, Status.REJECTED, Reason.VALUE_OUT_OF_RANGE, -22)
                return
            self.staging = [self.staging[0], p]
        elif isinstance(p, PeripheralPatternsPacket):
            if not self.staging:
                self.response(p, Status.BAD_STATE, Reason.MISSING_CONFIG)
                return
            if self.staging[0].mode == OperationMode.RADIO_TX_TEST:
                self.response(p, Status.REJECTED, Reason.MODE_MISMATCH)
                return
            errors = validate_patterns(p)
            if errors:
                reason = Reason.NONZERO_PADDING if p.has_nonzero_padding() else Reason.VALUE_OUT_OF_RANGE
                self.response(p, Status.REJECTED, reason, -22)
                return
            self.staging = self.staging[:2] + [p]
        elif isinstance(p, DeviceNamePacket):
            if len(self.staging) < 2:
                self.response(p, Status.BAD_STATE, Reason.MISSING_CONFIG)
                return
            if self.staging[0].mode == OperationMode.RADIO_TX_TEST:
                self.response(p, Status.REJECTED, Reason.MODE_MISMATCH)
                return
            self.staging = [item for item in self.staging if not isinstance(item, DeviceNamePacket)] + [p]
        elif isinstance(p, PeerDataPacket):
            # As host_link_config_check_peer_data(): RAS real-time is expressed by omitting the frame.
            if not self.staging:
                self.response(p, Status.BAD_STATE, Reason.MISSING_CONFIG)
                return
            if self.staging[0].mode != OperationMode.CS_INITIATOR:
                self.response(p, Status.REJECTED, Reason.MODE_MISMATCH)
                return
            if p.peer_data != 1:
                self.response(p, Status.REJECTED, Reason.VALUE_OUT_OF_RANGE)
                return
            self.staging = [item for item in self.staging if not isinstance(item, PeerDataPacket)] + [p]
        elif isinstance(p, TpmPacket):
            # As host_link_config_check_t_pm(): 10 us is the preference expressed by omitting the frame.
            if not self.staging:
                self.response(p, Status.BAD_STATE, Reason.MISSING_CONFIG)
                return
            if self.staging[0].mode != OperationMode.CS_INITIATOR:
                self.response(p, Status.REJECTED, Reason.MODE_MISMATCH)
                return
            if p.t_pm_us not in T_PM_VALUES_US or p.t_pm_us == T_PM_DEFAULT_US:
                self.response(p, Status.REJECTED, Reason.VALUE_OUT_OF_RANGE)
                return
            self.staging = [item for item in self.staging if not isinstance(item, TpmPacket)] + [p]
        elif isinstance(p, LogConfigPacket):
            if not self.staging:
                self.response(p, Status.BAD_STATE, Reason.MISSING_CONFIG)
                return
            if p.is_default:
                self.response(p, Status.REJECTED, Reason.VALUE_OUT_OF_RANGE)
                return
            self.staging = [item for item in self.staging if not isinstance(item, LogConfigPacket)] + [p]
        elif isinstance(p, ApplyConfigPacket):
            # The firmware's order: missing configuration, missing patterns, then reflector data.
            peer_data = [item for item in self.staging if isinstance(item, PeerDataPacket)]
            t_pm = [item for item in self.staging if isinstance(item, TpmPacket)]
            try:
                config = ClientConfig.from_packets([item for item in self.staging
                                                    if not isinstance(item, (PeerDataPacket, TpmPacket))])
                if getattr(config.config, "gap_role", 1) == 0 and config.patterns is None:
                    self.response(p, Status.BAD_STATE, Reason.MISSING_PATTERNS)
                    return
            except ValueError:
                self.response(p, Status.REJECTED, Reason.MISSING_CONFIG)
                return
            if peer_data:
                if not getattr(config.config, "creation_cs_enhancements_1", 0) & 0x01:
                    # Reflector data none without the IPT request (-EINVAL).
                    self.response(p, Status.REJECTED, Reason.VALUE_OUT_OF_RANGE, -22)
                    return
                config = dataclasses.replace(config, peer_data=peer_data[-1].peer_data)
            if t_pm:
                config = dataclasses.replace(config, t_pm=t_pm[-1].t_pm_us)
            self.config = config
            self.log_config = config.log or LogConfigPacket(int(LOG_CONSOLE_LEVEL_DEFAULT), int(LOG_PROTOCOL_LEVEL_DEFAULT))
            self.staging = []
            self.set_state(ClientState.CONFIGURED)
            self.log_message(int(LogLevel.INFO), text="configuration applied")
        elif isinstance(p, GetConfigPacket):
            if not self.config:
                self.response(p, Status.BAD_STATE, Reason.MISSING_CONFIG)
                return
            for item in self.config.packets():
                self.send(item)
        elif isinstance(p, (ScanStartPacket, AdvertiseStartPacket, PeerConnectPacket)):
            if not self.config:
                self.response(p, Status.BAD_STATE, Reason.MISSING_CONFIG)
                return
            if self.config.mode == OperationMode.RADIO_TX_TEST:
                self.response(p, Status.UNSUPPORTED)
                return
            role = 1 if isinstance(p, AdvertiseStartPacket) else 0
            if self.config.config.gap_role != role:
                self.response(p, Status.BAD_STATE, Reason.MODE_MISMATCH)
                return
            # Firmware accepts an explicit peer address with or without an
            # active scan, while rejecting a second concurrent link attempt.
            direct_peer_connect = (isinstance(p, PeerConnectPacket) and
                                   self.state in (ClientState.IDLE, ClientState.CONFIGURED,
                                                  ClientState.SCANNING))
            if self.link_active() and not direct_peer_connect:
                self.response(p, Status.BAD_STATE, Reason.LINK_ACTIVE)
                return
            self.response(p)
            if isinstance(p, ScanStartPacket):
                self.set_state(ClientState.SCANNING)
                for index, name in enumerate(("CS-Reflector", "CS-Reflector", "Lab peer å"), 1):
                    raw = name.encode("utf-8")
                    self.send(ScanResultPacket(1, bytes([index, 2, 3, 4, 5, 6]), -40-index*5,
                                               3, len(raw), raw.ljust(254, b"\0")))
            elif isinstance(p, AdvertiseStartPacket):
                self.set_state(ClientState.ADVERTISING)
            else:
                self.selected_peer = (p.address_type, p.address)
                self.set_state(ClientState.LINK_CONNECTING)
                self.set_state(ClientState.LINK_CONNECTED)
            return
        elif isinstance(p, StartPacket):
            if not self.config:
                self.response(p, Status.BAD_STATE, Reason.MISSING_CONFIG)
                return
            if p.config_crc32 != self.config.crc32():
                self.response(p, Status.CONFIG_MISMATCH)
                return
            # Reflector data none needs a peer with IPT: the firmware ends the setup after the
            # remote capabilities, following the START response.
            peer_ipt_fails = (self.config.mode == OperationMode.CS_INITIATOR and self.config.peer_data == 1 and
                              not self.peer_ipt_supported)
            if self.state == ClientState.RUNNING:
                self.response(p, Status.BAD_STATE, Reason.BUSY)
                return
            start_response_sent = False
            if not self.link_established and self.config.mode != OperationMode.RADIO_TX_TEST:
                from dataclasses import fields, replace
                from .protocol.packets import CAPABILITIES_CONN_NONE, CapabilitiesSource, CsCapabilitiesPacket
                from .planner.model import Scenario
                from .planner.bridge import apply_packet
                self.link_number += 1
                self.link_established = True
                self.set_state(ClientState.LINK_CONNECTED)
                # Firmware acknowledges START before it streams the negotiated
                # capability/configuration reports; this lets the host commit
                # the new history before those reports arrive.
                self.response(p)
                start_response_sent = True
                # Loopback delivery is synchronous.  A host that detects a CRC
                # mismatch can immediately send STOP while START is still on
                # this call stack; do not overwrite that stopped state below.
                if self.state in (ClientState.STOPPED, ClientState.LINK_DISCONNECTED,
                                  ClientState.ERROR):
                    return
                capabilities = {f.name: 0 for f in fields(CsCapabilitiesPacket)}
                capabilities.update(num_antennas_supported=4, max_antenna_paths_supported=4,
                                    num_config_supported=4, initiator_supported=1, reflector_supported=1,
                                    rtt_aa_only_precision=1, rtt_aa_only_n=10, t_sw_time=2, cs_sync_2m_phy_supported=1,
                                    t_ip1_times_supported=0x7F, t_ip2_times_supported=0x7F,
                                    t_fcs_times_supported=0x1FF, t_pm_times_supported=0x03)
                self.send(CsCapabilitiesPacket(**{**capabilities, "conn_index": CAPABILITIES_CONN_NONE}))
                self.send(CsCapabilitiesPacket(**{**capabilities, "source": CapabilitiesSource.REMOTE,
                                                  "cs_ipt_reflector_supported": int(self.peer_ipt_supported)}))
                if not peer_ipt_fails:
                    scenario, _ = apply_packet(Scenario(), {}, self.config.config)
                    # Both simulated controllers support every T_PM, so a requested one is the one
                    # used; without a request the controller keeps its own choice.
                    configuration = scenario.configuration
                    if self.config.t_pm != T_PM_DEFAULT_US:
                        configuration = replace(configuration, t_pm_time_us=self.config.t_pm)
                    self.send(configuration)
                    # Like the firmware initiator: after each configuration complete, once per link.
                    if self.config.mode == OperationMode.CS_INITIATOR:
                        self.send(CsPeerDataPacket(self.config.peer_data))
                    self.send(replace(scenario.procedure, state=1))
            if peer_ipt_fails:
                if not start_response_sent:
                    self.response(p)
                self.set_state(ClientState.ERROR, Reason.PEER_IPT_UNSUPPORTED, -134)
                return
            self.radio_received = self.radio_crc = self.radio_ticks = 0
            self.radio_last = None
            self.procedures = 0
            self.set_state(ClientState.RUNNING)
            self.next_report = self.clock()
        elif isinstance(p, StopPacket):
            if self.state in (ClientState.SCANNING, ClientState.ADVERTISING, ClientState.LINK_CONNECTING):
                self.set_state(ClientState.LINK_DISCONNECTED)
                self.response(p)
                return
            if self.radio_last is not None and self.config.mode == OperationMode.RADIO_TX_TEST:
                self.send(self.radio_last)
            if self.finite_test_running():
                self.set_state(ClientState.STOPPED, Reason.INTERRUPTED, -ECANCELED)
            else:
                self.set_state(ClientState.STOPPED)
        elif isinstance(p, LinkDisconnectPacket):
            # link_disconnect() stops the client itself, so a running measurement
            # is interrupted rather than refused with BUSY (§7.8, §10 item 9).
            self.interrupt(-ECANCELED)
            self.link_fae_sent = False
            self.link_established = False
            self.set_state(ClientState.LINK_DISCONNECTED)
        elif isinstance(p, CloseSessionPacket):
            self.connected = False
            self.staging.clear()
        else:
            self.response(p, Status.UNSUPPORTED)
            return
        if not (isinstance(p, StartPacket) and start_response_sent):
            self.response(p)
        if isinstance(p, CloseSessionPacket):
            self.interrupt(-ECANCELED)
        if isinstance(p, StartPacket) and self.config.mode == OperationMode.RADIO_TX_TEST:
            if self.config.config.test_type in (RadioTestType.RX, RadioTestType.RX_SWEEP):
                self.radio_tick()  # baseline after START confirmation, even if stopped immediately
                self.next_report = self.clock() + .2
        if isinstance(p, StartPacket):
            self.log_message(int(LogLevel.INFO), text="run started")

    def rtt_time_differences(self, channels):
        """(initiator ToA−ToD, reflector ToD−ToA, AA quality, bit errors) per mode-1 step.

        Both are 0.5 ns offsets from nominal: the reflector reports its turnaround
        error and the initiator the round trip plus that error, so
        (t_i − t_r) / 2 is the time of flight. Seeded by the procedure counter.
        """
        rng = random.Random(self.counter)
        round_trip = 2 * RTT_DISTANCE_M / 299_792_458.0 / 0.5e-9
        values = []
        for _ in channels:
            turnaround = rng.gauss(0, 3)
            bad = rng.random() < 0.05
            values.append((round(round_trip + turnaround + rng.gauss(0, RTT_NOISE_UNITS)),
                           round(turnaround + rng.gauss(0, RTT_NOISE_UNITS)),
                           1 if bad else 0, rng.randint(1, 4) if bad else 0))
        return values

    def radio_tick(self):
        cfg = self.config.config
        if cfg.test_type not in (RadioTestType.RX, RadioTestType.RX_SWEEP):
            if cfg.test_type == RadioTestType.MODULATED_TX and cfg.packet_count:
                self.set_state(ClientState.STOPPED, Reason.TEST_COMPLETE)
            return
        if self.radio_capture:
            for packet in self.radio_capture:
                self.send(packet)
            self.set_state(ClientState.STOPPED, Reason.TEST_COMPLETE)
            return
        # First report is a baseline; then ~100 packets/s with deterministic loss.
        if self.radio_ticks:
            valid = 16 + self.radio_ticks % 4
            if cfg.test_type == RadioTestType.RX and cfg.packet_count:
                valid = min(valid, cfg.packet_count - self.radio_received)
            self.radio_received += valid
            self.radio_crc += int(self.radio_ticks % 3 == 0)
        channel = cfg.channel
        if cfg.test_type == RadioTestType.RX_SWEEP:
            dwell = max(.001, cfg.sweep_delay_ms / 1000)
            channel = cfg.sweep_start_channel + int(self.radio_ticks * .2 / dwell) % (cfg.sweep_end_channel - cfg.sweep_start_channel + 1)
        self.radio_last = RadioTestStatsPacket(self.radio_received, self.radio_crc,
                                               -55 + self.radio_ticks % 11, channel)
        self.send(self.radio_last)
        self.radio_ticks += 1
        if cfg.test_type == RadioTestType.RX and cfg.packet_count and self.radio_received >= cfg.packet_count:
            self.set_state(ClientState.STOPPED, Reason.TEST_COMPLETE)

    def tick(self):
        if self.connect_due is not None and self.clock() >= self.connect_due:
            self.connect_due = None
            self.connect_response()
        if self.state != ClientState.RUNNING or self.clock() < self.next_report:
            return
        self.next_report = self.clock() + .2
        self.counter = (self.counter + 1) % 65536
        if not self.connected:
            return
        if self.config.mode == OperationMode.RADIO_TX_TEST:
            self.radio_tick()
            return
        if not self.link_fae_sent and self.config.mode == OperationMode.CS_INITIATOR:
            self.send(CsFaeTablePacket(0, 32, tuple((i % 17) - 8 for i in range(72))))
            self.link_fae_sent = True
        if self.capture:
            for packet in self.capture:
                self.send(packet)
        else:
            from .protocol.packets import CsStep, CsTone
            # Mode-1 RTT steps, then mode-2 tones on several channels; both roles share the procedure key.
            classes = ((CsInitiatorSubeventResultPacket, CsReflectorSubeventResultPacket)
                       if self.config.mode == OperationMode.CS_INITIATOR and self.config.peer_data == 0
                       else (CsInitiatorSubeventResultPacket,)
                       if self.config.mode == OperationMode.CS_INITIATOR
                       else (CsReflectorSubeventResultPacket,))
            paths = (1, 2, 3, 4, 2, 3, 4, 4)[self.config.config.tone_antenna_config_selection]
            rtt = self.rtt_time_differences(RTT_CHANNELS)
            for cls in classes:
                initiator = cls is CsInitiatorSubeventResultPacket
                steps = tuple(CsStep(mode=1, channel=ch, flags=0x05, aa_quality=quality, bit_errors=errors,
                                     rssi=-40, antenna=1, nadm=0, measured_freq_offset=0,
                                     time_difference=t_i if initiator else t_r, pct1_i=0, pct1_q=0, pct2_i=0,
                                     pct2_q=0, antenna_permutation_index=0)
                              for ch, (t_i, t_r, quality, errors) in zip(RTT_CHANNELS, rtt))
                steps += tuple(CsStep(mode=2, channel=ch, flags=8, aa_quality=0, bit_errors=0,
                                      rssi=-40, antenna=1, nadm=0, measured_freq_offset=0,
                                      time_difference=0, pct1_i=1000, pct1_q=0, pct2_i=1000, pct2_q=0,
                                      antenna_permutation_index=0, tones=tuple(CsTone(1000, ch * 3, path, 0, 0) for path in range(paths)))
                               for ch in range(26, 42))
                self.send(cls(self.config.config.config_id, self.counter, self.counter,
                              0, -20, 0, 0, 0, 0, paths, 0, steps))
        if self.counter % 20 == 0 and not (self.config.mode == OperationMode.CS_INITIATOR and self.config.peer_data == 1):
            self.send(RasDataLostPacket(self.counter, -61))
        self.procedures += 1
        limit = self.config.config.max_procedure_count
        if self.config.mode == OperationMode.CS_INITIATOR and limit and self.procedures >= limit:
            # Like cs_roles: the controller completed max_procedure_count without STOP.
            self.send(CsProceduresCompletePacket(self.procedures))
            self.set_state(ClientState.STOPPED, Reason.TEST_COMPLETE)
