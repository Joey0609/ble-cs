from __future__ import annotations

from dataclasses import fields, replace
import unittest

from ble_channel_sounding.protocol import PROTOCOL_VERSION, ClientConfig
from ble_channel_sounding.protocol.frame import Frame, FrameDecoder, ProtocolError
from ble_channel_sounding.protocol.packets import (
    ApplyConfigPacket,
    ClientState,
    ClientStatePacket,
    CloseSessionPacket,
    DeviceNamePacket,
    CommandResponsePacket,
    ConnectPacket,
    ConnectResponsePacket,
    CsCapabilitiesPacket,
    CsConfigurationPacket,
    CsFaeTablePacket,
    CsInitiatorConfigPacket,
    CsInitiatorSubeventResultPacket,
    CsProcedureEnableCompletePacket,
    CsReflectorConfigPacket,
    CsStep,
    CsTone,
    GetConfigPacket,
    LinkDisconnectPacket,
    OPERATION_MODE_NONE,
    OperationMode,
    OperationModeMask,
    OperationModePacket,
    PeerDataPacket,
    LogConfigPacket,
    LogLevel,
    CsPeerDataPacket,
    ConnectionParametersPacket,
    PacketType,
    PeripheralPatternsPacket,
    ProtocolStatus,
    RadioTxTestConfigPacket,
    RasDataLostPacket,
    CsProceduresCompletePacket,
    RejectReason,
    StartPacket,
    StopPacket,
    TpmPacket,
    decode_packet,
    packet_from_dict,
    packet_to_dict,
)
from ble_channel_sounding.protocol.receiver import PacketReceiver


EXPECTED_SIZES = {
    OperationModePacket: 13,
    CsInitiatorConfigPacket: 69,
    CsReflectorConfigPacket: 46,
    RadioTxTestConfigPacket: 37,
    PeripheralPatternsPacket: 277,
    LogConfigPacket: 14,
    TpmPacket: 13,
    ApplyConfigPacket: 12,
    CsCapabilitiesPacket: 49,
    CsConfigurationPacket: 40,
    CsProcedureEnableCompletePacket: 31,
    ConnectPacket: 14,
    StartPacket: 16,
    StopPacket: 12,
    CloseSessionPacket: 12,
    GetConfigPacket: 12,
    LinkDisconnectPacket: 12,
    ConnectResponsePacket: 30,
    CommandResponsePacket: 24,
    CsFaeTablePacket: 86,
    ClientStatePacket: 20,
    RasDataLostPacket: 16,
    CsProceduresCompletePacket: 14,
    ConnectionParametersPacket: 20,
}

BYTE_FIELD_SIZES = {
    "creation_channel_map": 10,
    "channel_map": 10,
    "lengths": 8,
    "patterns": 256,
}


def sample_packet(packet_class: type) -> object:
    values = {}
    for field in fields(packet_class):
        if field.name == "entries":
            values[field.name] = tuple(range(-36, 36))
        elif field.name in BYTE_FIELD_SIZES:
            values[field.name] = bytes(BYTE_FIELD_SIZES[field.name])
        elif field.name in {"max_tx_power", "tx_power_delta", "txpower", "selected_tx_power", "error"}:
            values[field.name] = -1
        else:
            values[field.name] = 1
    return packet_class(**values)


class FrameTests(unittest.TestCase):
    def test_known_operation_mode_frame_matches_c_wire_layout(self) -> None:
        encoded = OperationModePacket(OperationMode.RADIO_TX_TEST).to_bytes()
        self.assertEqual(
            encoded,
            bytes.fromhex("a55a0d00000102c163a7c95aa5"),
        )
        frame = Frame.from_bytes(encoded)
        self.assertEqual(frame.packet_type, PacketType.SET_OPERATION_MODE)
        self.assertEqual(frame.payload, b"\x02")

    def test_rejects_size_sync_and_crc_errors(self) -> None:
        encoded = bytearray(OperationModePacket(0).to_bytes())
        for offset in (0, 2, 7, len(encoded) - 1):
            corrupted = encoded.copy()
            corrupted[offset] ^= 1
            with self.assertRaises(ProtocolError):
                Frame.from_bytes(corrupted)

    def test_stream_decoder_handles_noise_fragments_and_multiple_frames(self) -> None:
        first = OperationModePacket(0).to_bytes()
        second = ApplyConfigPacket().to_bytes()
        decoder = FrameDecoder()
        self.assertEqual(decoder.feed(b"noise" + first[:5]), [])
        frames = decoder.feed(first[5:] + second)
        self.assertEqual([frame.packet_type for frame in frames], [0x0100, 0x0105])
        self.assertEqual(decoder.buffered_bytes, 0)
        self.assertEqual(decoder.discarded_bytes, 5)


class PacketTests(unittest.TestCase):
    def test_all_fixed_packet_sizes_and_round_trips_match_c_asserts(self) -> None:
        for packet_class, expected_size in EXPECTED_SIZES.items():
            with self.subTest(packet=packet_class.__name__):
                packet = sample_packet(packet_class)
                encoded = packet.to_bytes()
                self.assertEqual(len(encoded), expected_size)
                self.assertEqual(decode_packet(Frame.from_bytes(encoded)), packet)

    def test_wrong_fixed_payload_size_is_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            decode_packet(Frame(PacketType.SET_OPERATION_MODE, b""))

    def test_unknown_packet_remains_a_generic_frame(self) -> None:
        frame = Frame(0x7777, b"future")
        self.assertIs(decode_packet(frame), frame)

    def test_peripheral_pattern_builder_matches_c_arrays(self) -> None:
        packet = PeripheralPatternsPacket.from_patterns(["sensor", b"peer"])
        self.assertEqual(packet.count, 2)
        self.assertEqual(packet.lengths, b"\x06\x04" + bytes(6))
        self.assertEqual(packet.patterns[:32], b"sensor" + bytes(26))
        self.assertEqual(packet.names(), ["sensor", "peer"])
        self.assertEqual(decode_packet(Frame.from_bytes(packet.to_bytes())), packet)

    def test_subevent_steps_and_tones_round_trip(self) -> None:
        step = CsStep(
            mode=2,
            channel=17,
            flags=0,
            aa_quality=0,
            bit_errors=0,
            rssi=0,
            antenna=0,
            nadm=0,
            measured_freq_offset=0,
            time_difference=0,
            pct1_i=0,
            pct1_q=0,
            pct2_i=0,
            pct2_q=0,
            antenna_permutation_index=3,
            tones=(CsTone(100, -200, 1, 0, 0),),
        )
        packet = CsInitiatorSubeventResultPacket(
            config_id=1,
            start_acl_conn_event=2,
            procedure_counter=3,
            frequency_compensation=4,
            reference_power_level=-5,
            procedure_done_status=0,
            subevent_done_status=0,
            procedure_abort_reason=0,
            subevent_abort_reason=0,
            num_antenna_paths=1,
            abort_step=0xFF,
            steps=(step,),
        )
        encoded = packet.to_bytes()
        self.assertEqual(len(encoded), 12 + 15 + 22 + 8)
        self.assertEqual(decode_packet(Frame.from_bytes(encoded)), packet)

    def test_subevent_without_antenna_paths_round_trips(self) -> None:
        # Mode 1 only: the controller reports no antenna paths, and no step has tones.
        step = CsStep(mode=1, channel=17, flags=0x05, aa_quality=0, bit_errors=0, rssi=-40, antenna=1,
                      nadm=0, measured_freq_offset=0, time_difference=-12, pct1_i=0, pct1_q=0, pct2_i=0,
                      pct2_q=0, antenna_permutation_index=0)
        packet = CsInitiatorSubeventResultPacket(
            config_id=1, start_acl_conn_event=2, procedure_counter=3, frequency_compensation=4,
            reference_power_level=-5, procedure_done_status=0, subevent_done_status=0,
            procedure_abort_reason=0, subevent_abort_reason=0, num_antenna_paths=0, abort_step=0xFF,
            steps=(step, step))
        decoded = decode_packet(Frame.from_bytes(packet.to_bytes()))
        self.assertEqual(decoded, packet)
        self.assertEqual(decoded.num_antenna_paths, 0)

    def test_subevent_rejects_step_count_mismatch(self) -> None:
        payload = CsInitiatorSubeventResultPacket.STRUCT.pack(
            0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0xFF
        )
        with self.assertRaises(ProtocolError):
            decode_packet(Frame(PacketType.CS_INITIATOR_SUBEVENT_RESULT, payload))

    def test_json_packet_factory(self) -> None:
        self.assertEqual(
            packet_from_dict("operation-mode", {"mode": 1}),
            OperationModePacket(1),
        )
        self.assertEqual(
            packet_from_dict(
                "set_peripheral_patterns",
                {"peripheral_names": ["left", "right"]},
            ).names(),
            ["left", "right"],
        )

    def test_peer_data_packets_are_13_bytes(self) -> None:
        for packet in (PeerDataPacket(1), CsPeerDataPacket(1)):
            with self.subTest(packet=type(packet).__name__):
                self.assertEqual(packet.to_frame().size, 13)
                self.assertEqual(decode_packet(Frame.from_bytes(packet.to_bytes())), packet)

    def test_connection_parameters_packet_is_20_bytes(self) -> None:
        packet = ConnectionParametersPacket(interval=14, latency=0, timeout=400, mtu=498)
        self.assertEqual(packet.to_frame().payload, bytes.fromhex("0e0000009001f201"))
        self.assertEqual(decode_packet(Frame.from_bytes(packet.to_bytes())), packet)
        legacy = decode_packet(Frame(PacketType.CONNECTION_PARAMETERS,
                                     bytes.fromhex("0e0000009001")))
        self.assertEqual(legacy, ConnectionParametersPacket(14, 0, 400, 0))

    def test_log_config_packet_is_14_bytes(self) -> None:
        packet = LogConfigPacket(LogLevel.DEBUG, LogLevel.INFO)
        self.assertEqual(packet.to_frame().payload, b"\x04\x03")
        self.assertEqual(decode_packet(Frame.from_bytes(packet.to_bytes())), packet)


class SessionPacketTests(unittest.TestCase):
    def test_command_response_matches_c_wire_bytes(self) -> None:
        # Payload bytes follow cs_protocol_command_response_frame_t in cs_protocol_packets.h.
        packet = CommandResponsePacket(
            request_type=PacketType.APPLY_CONFIG,
            status=ProtocolStatus.BAD_STATE,
            reason=RejectReason.LINK_ACTIVE,
            error=-16,
            config_crc32=0x11223344,
        )
        self.assertEqual(
            packet.to_frame().payload, bytes.fromhex("05010308f0ffffff44332211")
        )
        info = packet_to_dict(packet)
        self.assertEqual(
            (info["request_name"], info["status_name"], info["reason_name"]),
            ("apply_config", "bad_state", "link_active"),
        )

    def test_connect_response_matches_c_wire_bytes(self) -> None:
        packet = ConnectResponsePacket(
            status=ProtocolStatus.OK,
            protocol_version=PROTOCOL_VERSION,
            supported_modes=OperationModeMask.CS_INITIATOR | OperationModeMask.CS_REFLECTOR,
            firmware_version=0x01020304,
            max_frame_size=1024,
            config_valid=0,
            operation_mode=OPERATION_MODE_NONE,
            config_crc32=0,
            client_state=ClientState.IDLE,
            num_antennas_supported=4,
        )
        self.assertEqual(
            packet.to_frame().payload, bytes.fromhex("000b000304030201000400ff000000000004")
        )
        info = packet_to_dict(packet)
        self.assertEqual(info["supported_mode_names"], ["cs_initiator", "cs_reflector"])
        self.assertEqual(info["operation_mode_name"], "none")
        self.assertEqual(info["client_state_name"], "idle")

    def test_enum_values_match_c_header(self) -> None:
        self.assertEqual(PROTOCOL_VERSION, 0x000B)
        self.assertEqual(PacketType.CS_PROCEDURES_COMPLETE, 0x000E)
        self.assertEqual(PacketType.CONNECTION_PARAMETERS, 0x0010)
        self.assertEqual(PacketType.SET_T_PM, 0x0112)
        self.assertEqual(ProtocolStatus.CONFIG_MISMATCH, 0x07)
        self.assertEqual(RejectReason.RAS_NO_REALTIME, 0x0A)
        self.assertEqual(RejectReason.TEST_COMPLETE, 0x0B)
        self.assertEqual(RejectReason.INTERRUPTED, 0x0C)
        self.assertEqual(ClientState.ERROR, 0x0A)
        self.assertEqual(OperationModeMask.of(OperationMode.RADIO_TX_TEST), 0x04)
        self.assertEqual(ConnectPacket().protocol_version, PROTOCOL_VERSION)

    def test_fae_table_is_signed_and_checks_entry_count(self) -> None:
        entries = (-128, 127) + (0,) * 70
        packet = CsFaeTablePacket(hci_status=0, lsb_denominator=32, entries=entries)
        payload = packet.to_frame().payload
        self.assertEqual(payload[:4], bytes([0, 32, 0x80, 0x7F]))
        self.assertEqual(decode_packet(Frame.from_bytes(packet.to_bytes())), packet)
        with self.assertRaises(ProtocolError):
            CsFaeTablePacket(0, 32, (0,) * 71).to_bytes()
        with self.assertRaises(ProtocolError):
            decode_packet(Frame(PacketType.CS_FAE_TABLE, payload[:-1]))

    def test_client_state_error_and_version_2_frames(self) -> None:
        packet = ClientStatePacket(ClientState.STOPPED, OperationMode.RADIO_TX_TEST,
                                   RejectReason.INTERRUPTED, 0, -140)
        self.assertEqual(packet.to_frame().payload, bytes.fromhex("0702" "0c00" "74ffffff"))
        self.assertEqual(decode_packet(Frame.from_bytes(packet.to_bytes())), packet)
        info = packet_to_dict(packet)
        self.assertEqual((info["reason_name"], info["error_name"]), ("interrupted", "-ECANCELED"))
        legacy = decode_packet(Frame(PacketType.CLIENT_STATE, bytes([7, 2, 0x0B, 0])))
        self.assertEqual(legacy, ClientStatePacket(7, 2, RejectReason.TEST_COMPLETE, 0, 0))
        with self.assertRaises(ProtocolError):
            decode_packet(Frame(PacketType.CLIENT_STATE, bytes(5)))

    def test_unknown_enum_values_are_named(self) -> None:
        info = packet_to_dict(ClientStatePacket(state=0x40, operation_mode=1, reason=0x30))
        self.assertEqual(info["state_name"], "unknown_0x40")
        self.assertEqual(info["operation_mode_name"], "cs_reflector")
        self.assertEqual(info["reason_name"], "unknown_0x30")

    def test_json_capture_names(self) -> None:
        self.assertEqual(packet_from_dict("connect", {}), ConnectPacket(PROTOCOL_VERSION))
        self.assertEqual(
            packet_from_dict("start", {"config_crc32": 0xB61D36F1}), StartPacket(0xB61D36F1)
        )
        self.assertEqual(packet_from_dict("stop", {}), StopPacket())
        self.assertEqual(packet_from_dict("get-config", {}), GetConfigPacket())
        self.assertEqual(packet_from_dict("link-disconnect", {}), LinkDisconnectPacket())
        self.assertEqual(packet_from_dict("close-session", {}), CloseSessionPacket())
        self.assertEqual(
            packet_from_dict("cs-fae-table", {"hci_status": 0, "lsb_denominator": 32,
                                              "entries": [1] * 72}).entries,
            (1,) * 72,
        )


# Shared configuration CRC vector, also in tests/host_link/test_config_store.c.
CONFIG_CRC_VECTOR = 0xB61D36F1
CONFIG_CRC_VECTOR_NO_PATTERNS = 0x7A403314
# The same configuration with IPT requested, the two patterns and SET_PEER_DATA(1).
CONFIG_CRC_VECTOR_PEER_DATA = 0x8252106B
# The first configuration and patterns with SET_LOG_CONFIG(DEBUG, INFO).
CONFIG_CRC_VECTOR_LOG_CONFIG = 0x7EA17539
# The first configuration and patterns with SET_T_PM(40), then also SET_LOG_CONFIG(DEBUG, INFO).
CONFIG_CRC_VECTOR_T_PM = 0x2DBB98CB
CONFIG_CRC_VECTOR_T_PM_LOG_CONFIG = 0x6A66BE09


def vector_initiator_config() -> CsInitiatorConfigPacket:
    return CsInitiatorConfigPacket(
        gap_role=0,
        config_id=1,
        connection_interval_min=24,
        connection_interval_max=24,
        connection_latency=0,
        connection_timeout=400,
        cs_sync_antenna_selection=0xFE,
        max_tx_power=20,
        max_procedure_len=0x3E80,
        min_procedure_interval=10,
        max_procedure_interval=20,
        max_procedure_count=0,
        min_subevent_len=60000,
        max_subevent_len=70000,
        tone_antenna_config_selection=7,
        phy=2,
        tx_power_delta=-128,
        preferred_peer_antenna=0x03,
        snr_control_initiator=0xFF,
        snr_control_reflector=0xFF,
        creation_mode=0x23,
        creation_min_main_mode_steps=2,
        creation_max_main_mode_steps=5,
        creation_main_mode_repetition=1,
        creation_mode_0_steps=3,
        creation_rtt_type=1,
        creation_cs_sync_phy=2,
        creation_channel_map=bytes.fromhex("fcff7ffcffffffffff1f"),
        creation_channel_map_repetition=1,
        creation_channel_selection_type=0,
        creation_ch3c_shape=0,
        creation_ch3c_jump=2,
        creation_cs_enhancements_1=0,
        creation_context=1,
    )


class ClientConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.patterns = PeripheralPatternsPacket.from_patterns(["CS-Reflector", "nRF"])
        self.config = ClientConfig(
            OperationMode.CS_INITIATOR, vector_initiator_config(), self.patterns
        )

    def test_shared_crc_vector(self) -> None:
        self.assertEqual(self.config.crc32(), CONFIG_CRC_VECTOR)
        self.assertEqual(len(self.config.payloads()), 1 + 57 + 265)
        without = ClientConfig(OperationMode.CS_INITIATOR, vector_initiator_config())
        self.assertEqual(without.crc32(), CONFIG_CRC_VECTOR_NO_PATTERNS)

    def test_shared_crc_vector_with_peer_data(self) -> None:
        ipt = replace(vector_initiator_config(), creation_cs_enhancements_1=1)
        config = ClientConfig(OperationMode.CS_INITIATOR, ipt, self.patterns, None, 1)
        self.assertEqual(config.crc32(), CONFIG_CRC_VECTOR_PEER_DATA)
        self.assertEqual(len(config.payloads()), 1 + 57 + 265 + 1)
        # The standalone planner's export CRC follows the same rule.
        from ble_channel_sounding_planner.export_c import config_crc32
        values = {name: getattr(ipt, name) for name in ipt.__dataclass_fields__}
        self.assertEqual(config_crc32("initiator", values, ["CS-Reflector", "nRF"], "", 1),
                         CONFIG_CRC_VECTOR_PEER_DATA)
        # Without SET_PEER_DATA the IPT configuration keeps RAS and has another CRC.
        self.assertNotEqual(ClientConfig(OperationMode.CS_INITIATOR, ipt, self.patterns).crc32(),
                            CONFIG_CRC_VECTOR_PEER_DATA)

    def test_shared_crc_vector_with_log_config(self) -> None:
        config = ClientConfig(OperationMode.CS_INITIATOR, vector_initiator_config(), self.patterns,
                              log=LogConfigPacket(LogLevel.DEBUG, LogLevel.INFO))
        self.assertEqual(config.crc32(), CONFIG_CRC_VECTOR_LOG_CONFIG)
        self.assertEqual(len(config.payloads()), 1 + 57 + 265 + 2)
        self.assertIsInstance(config.packets()[-1], LogConfigPacket)
        restored = ClientConfig.from_packets([decode_packet(Frame.from_bytes(packet.to_bytes()))
                                               for packet in config.packets()])
        self.assertEqual(restored, config)

    def test_peer_data_is_last_and_round_trips(self) -> None:
        ipt = replace(vector_initiator_config(), creation_cs_enhancements_1=1)
        config = ClientConfig(OperationMode.CS_INITIATOR, ipt, self.patterns,
                              DeviceNamePacket.from_name("Board"), 1)
        packets = config.packets()
        self.assertIsInstance(packets[-1], PeerDataPacket)
        self.assertIsInstance(packets[-2], DeviceNamePacket)
        received = [decode_packet(Frame.from_bytes(packet.to_bytes())) for packet in packets]
        restored = ClientConfig.from_packets(received)
        self.assertEqual(restored.peer_data, 1)
        self.assertEqual(restored.crc32(), config.crc32())

    def test_shared_crc_vector_with_t_pm(self) -> None:
        config = ClientConfig(OperationMode.CS_INITIATOR, vector_initiator_config(), self.patterns,
                              t_pm=40)
        self.assertEqual(config.crc32(), CONFIG_CRC_VECTOR_T_PM)
        self.assertEqual(len(config.payloads()), 1 + 57 + 265 + 1)
        both = ClientConfig(OperationMode.CS_INITIATOR, vector_initiator_config(), self.patterns,
                            log=LogConfigPacket(LogLevel.DEBUG, LogLevel.INFO), t_pm=40)
        self.assertEqual(both.crc32(), CONFIG_CRC_VECTOR_T_PM_LOG_CONFIG)
        # Between the peer data and the log levels, and it survives a GET_CONFIG round trip.
        ipt = replace(vector_initiator_config(), creation_cs_enhancements_1=1)
        full = ClientConfig(OperationMode.CS_INITIATOR, ipt, self.patterns, None, 1,
                            LogConfigPacket(LogLevel.DEBUG, LogLevel.INFO), t_pm=20)
        self.assertEqual([type(packet) for packet in full.packets()[-3:]],
                         [PeerDataPacket, TpmPacket, LogConfigPacket])
        restored = ClientConfig.from_packets([decode_packet(Frame.from_bytes(packet.to_bytes()))
                                               for packet in full.packets()])
        self.assertEqual(restored, full)

    def test_t_pm_10_is_omitted_and_other_values_are_refused(self) -> None:
        default = ClientConfig(OperationMode.CS_INITIATOR, vector_initiator_config(), self.patterns,
                               t_pm=10)
        self.assertEqual(default.crc32(), CONFIG_CRC_VECTOR)
        self.assertFalse(any(isinstance(packet, TpmPacket) for packet in default.packets()))
        for value in (0, 30, 80, True):
            with self.assertRaises(ProtocolError):
                ClientConfig(OperationMode.CS_INITIATOR, vector_initiator_config(), self.patterns,
                             t_pm=value)

    def test_peer_data_needs_ipt_in_initiator_mode(self) -> None:
        with self.assertRaises(ProtocolError):
            ClientConfig(OperationMode.CS_INITIATOR, vector_initiator_config(), self.patterns, None, 1)

    def test_packets_are_in_send_order_and_round_trip(self) -> None:
        packets = self.config.packets()
        self.assertEqual(
            [type(packet) for packet in packets],
            [OperationModePacket, CsInitiatorConfigPacket, PeripheralPatternsPacket],
        )
        # GET_CONFIG reply: the same packets as received over the wire.
        received = [decode_packet(Frame.from_bytes(packet.to_bytes())) for packet in packets]
        restored = ClientConfig.from_packets(received)
        self.assertEqual(restored, self.config)
        self.assertEqual(restored.crc32(), CONFIG_CRC_VECTOR)

    def test_radio_test_config(self) -> None:
        radio = sample_packet(RadioTxTestConfigPacket)
        config = ClientConfig.from_packets([OperationModePacket(2), radio])
        self.assertEqual(config.mode, OperationMode.RADIO_TX_TEST)
        self.assertEqual(len(config.payloads()), 1 + 25)

    def test_rejects_mode_mismatch_and_bad_patterns(self) -> None:
        with self.assertRaises(ProtocolError):
            ClientConfig(OperationMode.CS_REFLECTOR, vector_initiator_config())
        with self.assertRaises(ProtocolError):
            ClientConfig(7, vector_initiator_config())
        with self.assertRaises(ProtocolError):
            ClientConfig(
                OperationMode.RADIO_TX_TEST, sample_packet(RadioTxTestConfigPacket), self.patterns
            )
        slots = bytearray(self.patterns.patterns)
        slots[12] = ord("x")  # after the 12-byte first pattern
        with self.assertRaises(ProtocolError):
            ClientConfig(
                OperationMode.CS_INITIATOR,
                vector_initiator_config(),
                PeripheralPatternsPacket(2, self.patterns.lengths, bytes(slots)),
            )
        lengths = bytearray(self.patterns.lengths)
        lengths[5] = 1  # unused slot
        self.assertTrue(
            PeripheralPatternsPacket(2, bytes(lengths), self.patterns.patterns).has_nonzero_padding()
        )
        self.assertFalse(self.patterns.has_nonzero_padding())

    def test_from_packets_rejects_wrong_sequence(self) -> None:
        for packets in (
            [OperationModePacket(0)],
            [vector_initiator_config(), OperationModePacket(0)],
            [OperationModePacket(0), vector_initiator_config(), ApplyConfigPacket()],
        ):
            with self.subTest(packets=[type(p).__name__ for p in packets]):
                with self.assertRaises(ProtocolError):
                    ClientConfig.from_packets(packets)


class IoTests(unittest.TestCase):
    def test_receiver_decodes_packet_bytes(self) -> None:
        packet = OperationModePacket(2)
        self.assertEqual(len(packet.to_bytes()), 13)
        self.assertEqual(PacketReceiver().feed(packet.to_bytes()), [packet])

    def test_receiver_skips_undecodable_packet_and_continues(self) -> None:
        bad_length = Frame(PacketType.SET_OPERATION_MODE, b"").to_bytes()
        reserved_type = Frame(PacketType.INVALID, b"").to_bytes()
        packet = OperationModePacket(1)
        receiver = PacketReceiver()
        self.assertEqual(receiver.feed(bad_length + reserved_type + packet.to_bytes()), [packet])
        self.assertEqual(len(receiver.packet_errors), 2)

    def test_decoder_recovers_frames_behind_false_sync(self) -> None:
        frame = ApplyConfigPacket().to_bytes()
        false_header = bytes([0xA5, 0x5A, 20, 0, 0, 0])
        corrupted = bytearray(frame)
        corrupted[6] ^= 1
        stream = false_header + frame + bytes(corrupted) + frame
        decoder = FrameDecoder()
        split = [f for i in range(len(stream)) for f in decoder.feed(stream[i : i + 1])]
        self.assertEqual(len(FrameDecoder().feed(stream)), 2)
        self.assertEqual(len(split), 2)


if __name__ == "__main__":
    unittest.main()
