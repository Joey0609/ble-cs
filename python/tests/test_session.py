import unittest
import time
from dataclasses import replace
from ble_channel_sounding.protocol import PROTOCOL_VERSION
from ble_channel_sounding.session import ClientSession
from ble_channel_sounding.simulator import Simulator
from ble_channel_sounding.protocol.config import ClientConfig
from ble_channel_sounding.protocol.packets import (PeripheralPatternsPacket, PacketType, ProtocolStatus, CommandResponsePacket,
                                ConnectResponsePacket, ClientState, StartPacket, ClientStatePacket,
                                RadioTxTestConfigPacket, RejectReason, CsProceduresCompletePacket, CsPeerDataPacket,
                                CsConfigurationPacket, CsCapabilitiesPacket, CsReflectorSubeventResultPacket,
                                RasDataLostPacket, PeerDataPacket, OperationModePacket, ApplyConfigPacket,
                                ConnectionParametersPacket,
                                CloseSessionPacket, GetConfigPacket)
from ble_channel_sounding.protocol.packets import LogConfigPacket, LogMessagePacket
from ble_channel_sounding.protocol.frame import Frame
from ble_channel_sounding.session_history import SessionHistory
from unittest.mock import Mock
from ble_channel_sounding.planner.bridge import config_packet
from ble_channel_sounding.planner.model import Scenario


def config():
    return ClientConfig(0, config_packet(Scenario()), PeripheralPatternsPacket.from_patterns(["CS"]))


def rx_config(packet_count):
    return ClientConfig(2, RadioTxTestConfigPacket(2, 0, 3, 0, 0, packet_count, 0, 80, 10, 50, 100, 100, 0, 255))


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.events = []
        self.sim = Simulator(clock=lambda: self.now)
        self.session = ClientSession(clock=lambda: self.now, emit=lambda *event: self.events.append(event))
        self.session.set_host_config(config())
        self.session.connect(self.sim.transport)

    def test_apply_start_stop_and_reapply_sequence(self):
        s = self.session
        s.apply()
        self.assertTrue(s.in_sync)
        s.start()
        self.sim.tick()
        self.assertEqual(s.state, "RUNNING")
        with self.assertRaises(ValueError):
            s.apply()
        with self.assertRaises(ValueError):
            s.apply(allow_interrupt=True)
        s.stop()
        with self.assertRaises(ValueError):
            s.apply()
        self.events.clear()
        s.apply(allow_interrupt=True)
        sent = [v.PACKET_TYPE for k, v in self.events if k == "packet_sent"]
        self.assertEqual(sent[0], PacketType.LINK_DISCONNECT)
        self.assertEqual(sent[-1], PacketType.APPLY_CONFIG)
        self.assertTrue(s.in_sync)
        s.start()
        s.stop()
        self.assertEqual(s.state, "CONFIGURED")
        s.close()
        self.assertEqual(s.state, "DISCONNECTED")

    def test_confirmed_start_switches_history_and_refused_start_keeps_it(self):
        s = self.session
        s.apply()
        s.start()
        first = s.history
        self.assertIsNotNone(first)
        s.stop()
        self.assertFalse(first.closed)

        s.start()
        second = s.history
        self.assertIsNot(first, second)
        self.assertTrue(first.closed)
        s.stop()

        original = self.sim.handle
        self.sim.handle = lambda packet: self.sim.response(packet, ProtocolStatus.REJECTED) \
            if packet.PACKET_TYPE == PacketType.START else original(packet)
        try:
            s.start()
        finally:
            self.sim.handle = original
        self.assertIs(s.history, second)
        self.assertIsNone(s.pending_history)

    def test_log_config_is_applied_and_protocol_levels_filter_simulator_messages(self):
        s = self.session
        s.set_host_config(ClientConfig(0, config_packet(Scenario()),
                                       PeripheralPatternsPacket.from_patterns(["CS"]),
                                       log=LogConfigPacket(4, 3)))
        s.apply()
        self.assertEqual(s.client_config.log, LogConfigPacket(4, 3))
        before = len([p for p in self.received() if isinstance(p, LogMessagePacket)])
        self.sim.log_message(4, text="debug filtered")
        self.sim.log_message(3, text="info admitted")
        logs = [p.message.decode() for p in self.received() if isinstance(p, LogMessagePacket)]
        self.assertEqual(len(logs), before + 1)
        self.assertIn("info admitted", logs[-1])

    def initiator_only(self, peer_ipt_supported=True):
        scenario = replace(Scenario(), configuration=replace(Scenario().configuration, cs_enhancements_1=1))
        host = ClientConfig(0, config_packet(scenario, {"peer_data": 1}),
                            PeripheralPatternsPacket.from_patterns(["CS"]), peer_data=1)
        sim = Simulator(clock=lambda: self.now, peer_ipt_supported=peer_ipt_supported)
        s = ClientSession(clock=lambda: self.now, emit=lambda *event: self.events.append(event))
        s.set_host_config(host)
        s.connect(sim.transport)
        return sim, s

    def received(self):
        return [value for kind, value in self.events if kind == "packet_received"]

    def test_initiator_only_reports_peer_data_after_configuration(self):
        sim, s = self.initiator_only()
        s.apply()
        # As the firmware: nothing at APPLY_CONFIG, the applied configuration tells the host.
        self.assertFalse(any(isinstance(p, CsPeerDataPacket) for p in self.received()))
        self.assertEqual(s.applied_peer_data, 1)
        s.start()
        sim.tick()
        kinds = [type(p) for p in self.received()]
        self.assertEqual(kinds[kinds.index(CsConfigurationPacket) + 1], CsPeerDataPacket)
        self.assertEqual(s.context["peer_data"], 1)
        self.assertNotIn(CsReflectorSubeventResultPacket, kinds)
        self.assertNotIn(RasDataLostPacket, kinds)
        remote = [p for p in self.received() if isinstance(p, CsCapabilitiesPacket) and p.source == 1][0]
        self.assertEqual(remote.cs_ipt_reflector_supported, 1)

    def test_simulator_reports_initial_and_changed_att_mtu(self):
        self.session.apply()
        self.session.start()
        reports = [packet for packet in self.received() if isinstance(packet, ConnectionParametersPacket)]
        self.assertTrue(reports)
        self.assertEqual(reports[-1].mtu, 498)
        self.sim.set_mtu(247)
        self.assertEqual(self.received()[-1].mtu, 247)

    def test_initiator_only_without_peer_ipt(self):
        sim, s = self.initiator_only(peer_ipt_supported=False)
        s.apply()
        s.start()
        start = [v for k, v in self.events if k == "command_result" and v.request_type == PacketType.START][-1]
        self.assertEqual(start.status, ProtocolStatus.OK)
        state = [value for kind, value in self.events if kind == "client_state"][-1]
        self.assertEqual((state.state, state.reason, state.error),
                         (ClientState.ERROR, RejectReason.PEER_IPT_UNSUPPORTED, -134))
        self.assertFalse(any(isinstance(p, (CsConfigurationPacket, CsPeerDataPacket)) for p in self.received()))

    def test_simulator_rejects_a_short_preferred_peer_antenna_mask(self):
        sim, out = Simulator(clock=lambda: self.now, num_antennas_supported=4), []
        sim.send = out.append
        sim.connected = True
        scenario = replace(Scenario(), procedure=replace(Scenario().procedure, tone_antenna_config_selection=4))
        sim.handle(OperationModePacket(0))
        # A1:B2 with reflector antenna 3 only: -EINVAL from cs_initiator_config_set_procedure().
        sim.handle(config_packet(scenario, {"preferred_peer_antenna": 4}))
        self.assertEqual((out[-1].status, out[-1].reason, out[-1].error),
                         (ProtocolStatus.REJECTED, RejectReason.VALUE_OUT_OF_RANGE, -22))
        sim.handle(config_packet(scenario, {"preferred_peer_antenna": 3}))
        self.assertEqual(out[-1].status, ProtocolStatus.OK)

    def test_simulator_set_peer_data_rules(self):
        sim, out = Simulator(clock=lambda: self.now), []
        sim.send = out.append
        sim.connected = True

        def result(packet):
            out.clear()
            sim.handle(packet)
            response = [p for p in out if isinstance(p, CommandResponsePacket)][-1]
            return response.status, response.reason, response.error

        self.assertEqual(result(PeerDataPacket(1)), (ProtocolStatus.BAD_STATE, RejectReason.MISSING_CONFIG, 0))
        sim.handle(OperationModePacket(1))
        self.assertEqual(result(PeerDataPacket(1)), (ProtocolStatus.REJECTED, RejectReason.MODE_MISMATCH, 0))
        sim.handle(OperationModePacket(0))
        self.assertEqual(result(PeerDataPacket(0)), (ProtocolStatus.REJECTED, RejectReason.VALUE_OUT_OF_RANGE, 0))
        # None without the IPT request is refused at APPLY_CONFIG.
        sim.handle(config_packet(Scenario()))
        sim.handle(PeripheralPatternsPacket.from_patterns(["CS"]))
        self.assertEqual(result(PeerDataPacket(1)), (ProtocolStatus.OK, RejectReason.NONE, 0))
        self.assertEqual(result(ApplyConfigPacket()),
                         (ProtocolStatus.REJECTED, RejectReason.VALUE_OUT_OF_RANGE, -22))
        # As host_link_config_check_apply(): missing patterns are reported first.
        sim.handle(OperationModePacket(0))
        sim.handle(config_packet(Scenario()))
        self.assertEqual(result(PeerDataPacket(1)), (ProtocolStatus.OK, RejectReason.NONE, 0))
        self.assertEqual(result(ApplyConfigPacket()), (ProtocolStatus.BAD_STATE, RejectReason.MISSING_PATTERNS, 0))

    def test_simulator_set_t_pm_rules(self):
        from ble_channel_sounding.protocol.packets import TpmPacket
        sim, out = Simulator(clock=lambda: self.now), []
        sim.send = out.append
        sim.connected = True

        def result(packet):
            out.clear()
            sim.handle(packet)
            response = [p for p in out if isinstance(p, CommandResponsePacket)][-1]
            return response.status, response.reason, response.error

        # As host_link_config_check_t_pm(): a staged CS initiator mode, 20 or 40 µs only.
        self.assertEqual(result(TpmPacket(40)), (ProtocolStatus.BAD_STATE, RejectReason.MISSING_CONFIG, 0))
        sim.handle(OperationModePacket(1))
        self.assertEqual(result(TpmPacket(40)), (ProtocolStatus.REJECTED, RejectReason.MODE_MISMATCH, 0))
        sim.handle(OperationModePacket(0))
        for refused in (10, 30):
            self.assertEqual(result(TpmPacket(refused)),
                             (ProtocolStatus.REJECTED, RejectReason.VALUE_OUT_OF_RANGE, 0), refused)
        sim.handle(config_packet(Scenario()))
        sim.handle(PeripheralPatternsPacket.from_patterns(["CS"]))
        self.assertEqual(result(TpmPacket(20)), (ProtocolStatus.OK, RejectReason.NONE, 0))
        # The last frame wins, and the applied configuration replays it.
        self.assertEqual(result(TpmPacket(40)), (ProtocolStatus.OK, RejectReason.NONE, 0))
        self.assertEqual(result(ApplyConfigPacket()), (ProtocolStatus.OK, RejectReason.NONE, 0))
        self.assertEqual(sim.config.t_pm, 40)
        out.clear()
        sim.handle(GetConfigPacket())
        self.assertEqual([p.t_pm_us for p in out if isinstance(p, TpmPacket)], [40])

    def test_simulator_reports_the_requested_t_pm_at_configuration_complete(self):
        from ble_channel_sounding.protocol.packets import T_PM_DEFAULT_US
        s = self.session
        s.set_host_config(ClientConfig(0, config_packet(Scenario()),
                                       PeripheralPatternsPacket.from_patterns(["CS"]), t_pm=40))
        s.apply()
        self.assertEqual(s.client_config.t_pm, 40)
        s.start()
        configuration = [p for p in self.received() if isinstance(p, CsConfigurationPacket)][-1]
        self.assertEqual(configuration.t_pm_time_us, 40)
        # Without a request the simulated controller keeps its own choice.
        self.assertEqual(ClientConfig(0, config_packet(Scenario()),
                                      PeripheralPatternsPacket.from_patterns(["CS"])).t_pm, T_PM_DEFAULT_US)

    def test_simulator_command_framing_and_staging_parity(self):
        sim = Simulator()
        out = []
        sim.send = out.append
        unknown = Frame(0x7777, b"unknown")
        sim.handle(unknown)
        self.assertEqual((out[-1].request_type, out[-1].status), (0x7777, ProtocolStatus.UNSUPPORTED))

        out.clear()
        sim.feed(Frame(PacketType.STOP, b"bad").to_bytes())
        self.assertEqual((out[-1].request_type, out[-1].status), (PacketType.STOP, ProtocolStatus.INVALID_FRAME))

        sim.connected = True
        out.clear()
        sim.handle(PeripheralPatternsPacket(0, b"\0" * 8, b"\0" * 256))
        self.assertEqual((out[-1].status, out[-1].reason), (ProtocolStatus.BAD_STATE, RejectReason.MISSING_CONFIG))

        sim.handle(OperationModePacket(0))
        sim.handle(config_packet(Scenario()))
        out.clear()
        sim.handle(PeripheralPatternsPacket(0, b"\0" * 8, b"\0" * 256))
        self.assertEqual((out[-1].status, out[-1].reason), (ProtocolStatus.REJECTED, RejectReason.VALUE_OUT_OF_RANGE))
        out.clear()
        padded = bytearray(256)
        padded[1] = 1
        sim.handle(PeripheralPatternsPacket(1, b"\x01" + b"\0" * 7, bytes(padded)))
        self.assertEqual((out[-1].status, out[-1].reason), (ProtocolStatus.REJECTED, RejectReason.NONZERO_PADDING))

    def test_simulator_link_active_matches_cs_role_link_active(self):
        from ble_channel_sounding.protocol.packets import ClientState, ScanStartPacket, PeerConnectPacket
        sim, out = Simulator(), []
        sim.send = out.append
        sim.connected = True

        def status(packet):
            out.clear()
            sim.handle(packet)
            response = [p for p in out if isinstance(p, CommandResponsePacket)][-1]
            return response.status, response.reason

        link_active = (ProtocolStatus.BAD_STATE, RejectReason.LINK_ACTIVE)
        # A connection attempt is a link (CS_ROLE_LINK_CONNECTING).
        sim.state = ClientState.LINK_CONNECTING
        self.assertEqual(status(OperationModePacket(0)), link_active)
        # A setup failure (PEER_IPT) leaves ERROR with the link up (cs_role_fail keeps it).
        sim.state, sim.link_established = ClientState.ERROR, True
        self.assertEqual(status(OperationModePacket(0)), link_active)
        # ERROR without a link accepts configuration again.
        sim.link_established = False
        self.assertEqual(status(OperationModePacket(0))[0], ProtocolStatus.OK)
        # Discovery: while scanning, only PEER_CONNECT is allowed (peer_discovery.c).
        sim.handle(config_packet(Scenario()))
        sim.handle(PeripheralPatternsPacket.from_patterns(["CS"]))
        sim.handle(ApplyConfigPacket())
        sim.state = ClientState.SCANNING
        self.assertEqual(status(ScanStartPacket()), link_active)
        self.assertEqual(status(PeerConnectPacket(0, bytes(6)))[0], ProtocolStatus.OK)
        sim.state, sim.link_established = ClientState.ERROR, True
        self.assertEqual(status(ScanStartPacket()), link_active)

    def test_simulator_clears_staged_configuration_at_session_end(self):
        sim = Simulator()
        sim.connected = True
        sim.staging = [OperationModePacket(0)]
        sim.handle(CloseSessionPacket())
        self.assertFalse(sim.staging)
        sim.connected = True
        sim.staging = [OperationModePacket(0)]
        sim.host_lost()
        self.assertFalse(sim.staging)

    def test_mode3_four_path_history_stays_lossless_under_simulator_load(self):
        from dataclasses import replace
        scenario = replace(Scenario(), procedure=replace(Scenario().procedure,
                                                         tone_antenna_config_selection=7))
        # A2:B2 names two reflector antennas.
        host = ClientConfig(0, config_packet(scenario, {"preferred_peer_antenna": 3}),
                            PeripheralPatternsPacket.from_patterns(["CS"]))
        sim = Simulator(clock=lambda: self.now, num_antennas_supported=4)
        events = []
        session = ClientSession(clock=lambda: self.now, emit=lambda *event: events.append(event))
        session.set_host_config(host)
        session.connect(sim.transport)
        session.apply()
        session.start()
        started = time.monotonic()
        for _ in range(100):
            self.now += .2
            sim.tick()
        elapsed = time.monotonic() - started
        history = session.history
        self.assertIsNotNone(history)
        history.flush()
        self.assertIsNone(history.error)
        self.assertGreaterEqual(len(history.entries), 200)
        self.assertLess(elapsed, 10.0)
        history.close()

    def test_attaching_to_a_running_client_fetches_its_configuration(self):
        # A client without DTR (hardware UART) keeps running when its host goes away.
        s = self.session
        s.apply()
        s.start()
        self.sim.tick()
        other = replace(config(), patterns=PeripheralPatternsPacket.from_patterns(["Other"]))
        second = ClientSession(clock=lambda: self.now, emit=lambda *event: self.events.append(event))
        second.set_host_config(other)
        self.events.clear()
        second.connect(self.sim.transport)
        sent = [v.PACKET_TYPE for k, v in self.events if k == "packet_sent"]
        self.assertEqual(sent[-1], PacketType.GET_CONFIG)
        attached = [v for k, v in self.events if k == "attached_to_run"]
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0]["config"].crc32(), config().crc32())
        self.assertEqual(list(attached[0]["differences"]), ["patterns"])
        self.assertFalse(second.attached_to_run)
        self.assertEqual(second.applied_peer_data, 0)
        self.assertEqual(second.state, "RUNNING")

    def test_fetch_and_edit_disable_start(self):
        s = self.session
        s.apply()
        s.set_host_config(replace(config(), config=replace(config().config, max_tx_power=-4)))
        self.assertFalse(s.in_sync)
        with self.assertRaises(ValueError):
            s.start()
        s.fetch_config()
        self.assertEqual(s.client_config, config())
        s.set_host_config(s.client_config)
        self.assertTrue(s.in_sync)

    def test_timeout_closes_ambiguous_transport(self):
        s = self.session
        s.close()
        self.sim.never_connect = True
        s.connect(self.sim.transport)
        self.now = 9.9
        s.tick()
        self.assertEqual(s.state, "CONNECTING")
        self.now = 10
        s.tick()
        self.assertEqual(s.state, "FAILED")
        self.assertFalse(self.sim.transport.is_open)

    def test_cancel_connect_closes_the_unanswered_handshake(self):
        s = self.session
        s.close()
        self.sim.never_connect = True
        s.connect(self.sim.transport)
        self.now = 1
        s.cancel_connect()
        self.assertEqual(s.state, "DISCONNECTED")
        self.assertIsNone(s.transport)
        self.assertIsNone(s.pending)
        self.assertFalse(self.sim.transport.is_open)
        # Nothing is left waiting for the deadline that the cancel pre-empted.
        self.now = 20
        s.tick()
        self.assertEqual(s.state, "DISCONNECTED")
        with self.assertRaises(ValueError):
            s.cancel_connect()
        # The port stays usable: a cancel is not a failure.
        self.sim.never_connect = False
        s.connect(self.sim.transport)
        self.assertEqual(s.state, "CONNECTED")

    def test_rejection_aborts_apply(self):
        original = self.sim.handle
        def reject(packet):
            if packet.PACKET_TYPE == PacketType.SET_CS_INITIATOR_CONFIG:
                self.sim.response(packet, ProtocolStatus.REJECTED,
                                  RejectReason.VALUE_OUT_OF_RANGE, -34)
            else:
                original(packet)
        self.sim.handle = reject
        self.session.apply()
        self.assertIsNone(self.sim.config)
        sent = [v.PACKET_TYPE for k, v in self.events if k == "packet_sent"]
        self.assertNotIn(PacketType.APPLY_CONFIG, sent)
        self.assertIsNone(self.session.pending)
        refused = [value for event, value in self.events if event == "sync_failed"]
        self.assertEqual(len(refused), 1)
        self.assertIn("SET_CS_INITIATOR_CONFIG rejected", refused[0])
        self.assertIn("reason VALUE_OUT_OF_RANGE", refused[0])
        self.assertIn("ERANGE (-34)", refused[0])

    def test_connect_version_rejection_and_running_attach(self):
        s = self.session
        s.close()
        self.sim.never_connect = True
        s.connect(self.sim.transport)
        self.sim.send(ConnectResponsePacket(0, 999, 7, 1, 65535, 0, 255, 0, 0, 1))
        self.assertEqual(s.state, "FAILED")
        self.sim.never_connect = False
        self.sim.config = config()
        self.sim.state = ClientState.RUNNING
        s.connect(self.sim.transport)
        self.assertEqual(s.state, "RUNNING")
        s.stop()
        self.assertEqual(s.state, "CONFIGURED")

    def test_received_history_waits_for_connect_response(self):
        simulator = Simulator(clock=lambda: self.now, never_connect=True)
        events = []
        session = ClientSession(clock=lambda: self.now, emit=lambda *event: events.append(event))
        session.connect(simulator.transport)
        history = SessionHistory()
        session.history = history
        try:
            session.receive(LogMessagePacket(b"before connect response"))
            history.flush()
            self.assertTrue(history.empty)

            session.receive(ConnectResponsePacket(ProtocolStatus.OK, PROTOCOL_VERSION, 7, 0x10000,
                                                  65535, 0, 255, 0, ClientState.IDLE, 1))
            session.receive(LogMessagePacket(b"after connect response"))
            history.flush()
            self.assertEqual([packet.message for _, packet, _ in history.iter_packets()
                              if isinstance(packet, LogMessagePacket)], [b"after connect response"])
        finally:
            history.close(discard=True)

    def test_disconnect_link_while_running_ends_the_session_without_a_stop(self):
        """Disconnect link drops the peer and closes the session; the port stays open (§7.8)."""
        s = self.session
        s.apply()
        s.start()
        self.sim.tick()
        self.events.clear()
        s.disconnect_link()
        sent = [v.PACKET_TYPE for k, v in self.events if k == "packet_sent"]
        self.assertEqual(sent, [PacketType.LINK_DISCONNECT, PacketType.CLOSE_SESSION])
        self.assertEqual(s.state, "DISCONNECTED")
        self.assertEqual(s.link_state, ClientState.LINK_DISCONNECTED)
        self.assertEqual(self.sim.state, ClientState.LINK_DISCONNECTED)
        self.assertTrue(any(k == "run_finished" for k, v in self.events))
        # The port is still open: the next Connect is a handshake over it.
        self.assertIsNotNone(s.transport)
        self.assertFalse(self.sim.connected)
        s.reconnect()
        self.assertEqual(s.state, "CONFIGURED")
        self.assertTrue(self.sim.connected)
        s.start()
        self.assertEqual(s.state, "RUNNING")

    def test_session_toggle_tears_down_link_session_and_port(self):
        """The second press of the Connect toggle ends everything, in order (§7.8)."""
        s = self.session
        s.apply()
        s.start()
        self.sim.tick()
        self.events.clear()
        s.close()
        sent = [v.PACKET_TYPE for k, v in self.events if k == "packet_sent"]
        self.assertEqual(sent, [PacketType.LINK_DISCONNECT, PacketType.CLOSE_SESSION])
        self.assertNotIn(PacketType.STOP, sent)
        self.assertEqual(s.state, "DISCONNECTED")
        self.assertIsNone(s.transport)
        self.assertFalse(self.sim.connected)

    def test_session_close_without_a_link_sends_close_session_only(self):
        s = self.session  # connected, nothing applied: no link and no discovery to stop
        self.events.clear()
        self.assertFalse(s.can_disconnect_link)
        s.close()
        self.assertEqual([v.PACKET_TYPE for k, v in self.events if k == "packet_sent"],
                         [PacketType.CLOSE_SESSION])
        self.assertIsNone(s.transport)

    def test_reconnect_needs_an_open_port_and_no_session(self):
        s = self.session
        with self.assertRaises(ValueError):
            s.reconnect()  # a session is already open
        s.disconnect_link()
        s.close_port()
        with self.assertRaises(ValueError):
            s.reconnect()  # the port is gone with it

    def test_start_confirmed_with_other_crc_is_stopped_and_discarded(self):
        s = self.session
        s.apply()
        other = replace(config(), config=replace(config().config, max_tx_power=-9))
        original = self.sim.handle
        def confirm_other(packet):
            if packet.PACKET_TYPE == PacketType.START:
                self.sim.config = other
                packet = StartPacket(other.crc32())  # the client runs its own configuration
            original(packet)
        self.sim.handle = confirm_other
        recorder = Mock()
        s.logging_factory = lambda session, partial: recorder
        self.events.clear()
        s.start()
        recorder.close.assert_called_once_with("START configuration mismatch", discard=True)
        self.assertIsNone(s.recorder)
        sent = [v.PACKET_TYPE for k, v in self.events if k == "packet_sent"]
        self.assertEqual(sent, [PacketType.START, PacketType.STOP])
        self.assertTrue(any(k == "start_failed" for k, v in self.events))
        self.assertTrue(any(k == "recording_discarded" for k, v in self.events))
        self.assertEqual(s.state, "CONFIGURED")
        self.assertFalse(s.in_sync)
        self.assertEqual(self.sim.state, ClientState.STOPPED)

    def test_stop_timeout_and_start_crc_mismatch(self):
        s = self.session
        s.apply()
        self.sim.config = replace(config(), config=replace(config().config, max_tx_power=-9))
        self.events.clear()
        s.start()
        self.assertNotEqual(s.state, "RUNNING")
        self.assertFalse(s.in_sync)
        self.assertTrue(any(k == "start_failed" for k, v in self.events))
        with self.assertRaisesRegex(ValueError, "not synced"):
            s.start()
        self.sim.config = config()
        s.apply()
        s.start()
        original = self.sim.handle
        self.sim.handle = lambda p: None if p.PACKET_TYPE == PacketType.STOP else original(p)
        s.stop()
        self.now += 5
        s.tick()
        self.assertEqual(s.state, "FAILED")


class InterruptionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.events = []
        self.sim = Simulator(clock=lambda: self.now)
        self.session = ClientSession(clock=lambda: self.now, emit=lambda *event: self.events.append(event))
        self.session.connect(self.sim.transport)

    def run_test(self, packet_count):
        self.session.set_host_config(rx_config(packet_count))
        self.session.apply()
        self.session.start()
        self.assertEqual(self.session.state, "RUNNING")
        self.events.clear()

    def states(self):
        return [v for k, v in self.events if k == "packet_received" and isinstance(v, ClientStatePacket)]

    def errors(self):
        return [v for k, v in self.events if k == "link_error"]

    def test_stop_before_finite_test_completes_reports_interrupted(self):
        self.run_test(1000)
        self.session.stop()
        self.assertEqual(self.states(), [ClientStatePacket(ClientState.STOPPED, 2, RejectReason.INTERRUPTED, 0, -140)])
        self.assertIn("-ECANCELED", self.errors()[0])
        self.assertEqual(self.session.state, "CONFIGURED")
        self.assertEqual([v for k, v in self.events if k == "run_finished"], ["STOP confirmed"])

    def test_stop_of_continuous_test_is_not_an_interruption(self):
        self.run_test(0)
        self.session.stop()
        self.assertEqual(self.states(), [ClientStatePacket(ClientState.STOPPED, 2)])
        self.assertEqual(self.errors(), [])

    def test_close_session_while_running_reports_after_reconnect(self):
        self.run_test(0)
        self.session.close()
        self.assertEqual(self.sim.state, ClientState.STOPPED)
        self.assertEqual(self.states(), [])
        self.session.connect(self.sim.transport)
        self.assertEqual(self.session.state, "CONFIGURED")
        self.assertEqual(self.states(), [ClientStatePacket(ClientState.STOPPED, 2, RejectReason.INTERRUPTED, 0, -140)])
        self.assertIn("was interrupted", self.errors()[0])
        self.session.close()
        self.events.clear()
        self.session.connect(self.sim.transport)
        self.assertEqual(self.states(), [])  # delivered once

    def test_lost_port_while_running_stops_and_reports_enotconn(self):
        self.run_test(0)
        self.session.fail("port unplugged")
        self.assertEqual(self.sim.state, ClientState.STOPPED)
        self.events.clear()
        self.session.connect(self.sim.transport)
        self.assertEqual(self.states(), [ClientStatePacket(ClientState.STOPPED, 2, RejectReason.INTERRUPTED, 0, -128)])
        self.assertIn("-ENOTCONN", self.errors()[0])
        self.assertFalse(self.session.running)

    def test_max_procedure_count_reached_completes_the_run(self):
        self.session.set_host_config(replace(config(), config=replace(config().config, max_procedure_count=3)))
        self.session.apply()
        self.session.start()
        self.events.clear()
        for _ in range(3):
            self.now += 1
            self.sim.tick()
        completions = [v for k, v in self.events if k == "packet_received" and isinstance(v, CsProceduresCompletePacket)]
        self.assertEqual(completions, [CsProceduresCompletePacket(3)])
        self.assertEqual([v for k, v in self.events if k == "procedures_complete"], [3])
        self.assertEqual(self.states(), [ClientStatePacket(ClientState.STOPPED, 0, RejectReason.TEST_COMPLETE, 0, 0)])
        self.assertEqual([v for k, v in self.events if k == "run_finished"], ["complete: 3 procedures"])
        self.assertEqual(self.errors(), [])
        self.assertEqual(self.session.state, "CONFIGURED")
        self.assertFalse(self.session.running)
        self.session.start()  # a new run is possible on the kept link
        self.assertEqual(self.session.state, "RUNNING")

    def test_interruption_during_run_finishes_it(self):
        self.run_test(0)
        self.sim.send(ClientStatePacket(ClientState.ERROR, 2, RejectReason.INTERRUPTED, 0x1F, -5))
        self.assertEqual([v for k, v in self.events if k == "run_finished"], ["client state: ERROR (-EIO)"])
        self.assertIn("HCI status 0x1f", self.errors()[0])
        self.assertEqual(self.session.state, "CONFIGURED")
