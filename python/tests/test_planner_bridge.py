"""Scenario <-> protocol packet conversion; no Qt dependency."""

from dataclasses import replace
import unittest

from cs_app.protocol.frame import Frame
from cs_app.protocol.packets import (ConnectionParametersPacket, CsInitiatorConfigPacket, CsReflectorConfigPacket,
                                 LogMessagePacket, OperationMode, decode_packet)
from cs_app.planner.bridge import (CONNECTION_SOURCE, HOST_DEFAULTS, HOST_SOURCE, NEGOTIATED_SOURCE,
                               apply_channel_list, apply_packet, config_packet, decode_config, source_label)
from cs_app.planner.model import Scenario, build_schedule, channel_map_bytes, enabled_channels, validate


class PlannerBridgeTests(unittest.TestCase):
    def setUp(self):
        self.s = Scenario()
        self.host = dict(HOST_DEFAULTS)

    def test_example_fields_are_not_sent_or_exported(self):
        from cs_app.planner.export_c import MARKER, generate
        from cs_app.planner.model import EXAMPLE_FIELDS, scenario_value
        base = replace(self.s, connection=replace(self.s.connection, interval_max=40),
                       configuration=replace(self.s.configuration, cs_enhancements_1=1))
        changed = {"connection.activity_us": 2000, "connection.mtu": 247, "event_offset_us": 2000,
                   "main_steps": 3, "target_steps": 40,
                   "preview_count": 5, "channel_seed": 7, "connection.interval": 32,
                   "configuration.t_ip1_time_us": 80, "configuration.t_ip2_time_us": 80,
                   "configuration.t_fcs_time_us": 100, "configuration.t_pm_time_us": 20, "t_sw_us": 4,
                   "t_sw_ipt_us": 4, "procedure.subevents_per_event": 3, "procedure.subevent_interval": 20,
                   "procedure.event_interval": 2}
        self.assertEqual(set(changed), set(EXAMPLE_FIELDS))
        host = {**self.host, "peripheral_patterns": ["CS"]}

        def exported(scenario):
            return {role: text.split("\n", 1)[1].split(MARKER)[0] for role, text in generate(scenario, host, role="both").items()}
        for key, value in changed.items():
            group, _, name = key.rpartition(".")
            scenario = (replace(base, **{group: replace(getattr(base, group), **{name: value})}) if group
                        else replace(base, **{name: value}))
            self.assertNotEqual(scenario_value(scenario, key), scenario_value(base, key), key)
            for mode in (OperationMode.CS_INITIATOR, OperationMode.CS_REFLECTOR):
                self.assertEqual(config_packet(scenario, host, mode), config_packet(base, host, mode), key)
            self.assertEqual(exported(scenario), exported(base), key)

    def test_default_scenario_collects_transmittable_initiator_config(self):
        packet = config_packet(self.s, self.host)
        self.assertIsInstance(packet, CsInitiatorConfigPacket)
        self.assertEqual(self.s.procedure.tone_antenna_config_selection, 0)  # A1:B1
        self.assertEqual(decode_packet(Frame.from_bytes(packet.to_bytes())), packet)
        c, p = self.s.configuration, self.s.procedure
        self.assertEqual((packet.creation_mode, packet.creation_channel_map, packet.creation_ch3c_jump),
                         (c.mode, c.channel_map, c.ch3c_jump))
        self.assertEqual((packet.min_subevent_len, packet.max_subevent_len), (p.subevent_len, p.subevent_len))
        self.assertEqual(packet.creation_context, 1)
        reflector = config_packet(self.s, self.host, OperationMode.CS_REFLECTOR)
        self.assertIsInstance(reflector, CsReflectorConfigPacket)
        with self.assertRaises(ValueError):
            config_packet(self.s, self.host, OperationMode.RADIO_TX_TEST)

    def test_initiator_config_round_trips_through_scenario(self):
        sent = replace(config_packet(self.s, self.host), gap_role=1, max_tx_power=-4, creation_mode=3,
                       creation_channel_map=channel_map_bytes(range(26, 56)), creation_context=0)
        scenario, host = apply_packet(self.s, self.host, sent)
        self.assertEqual(scenario.configuration.mode, 3)
        self.assertEqual(enabled_channels(scenario.configuration.channel_map), tuple(range(26, 56)))
        self.assertEqual(config_packet(scenario, host), sent)
        self.assertFalse(validate(scenario))

    def test_requested_ranges_clamp_selected_values(self):
        packet = replace(config_packet(self.s, self.host), connection_interval_min=30, connection_interval_max=40,
                         min_subevent_len=6000, max_subevent_len=8000, min_procedure_interval=1,
                         max_procedure_interval=9, creation_min_main_mode_steps=6, creation_max_main_mode_steps=8)
        scenario, _ = apply_packet(self.s, self.host, packet)
        self.assertEqual(scenario.connection.interval, 30)
        self.assertEqual(scenario.procedure.subevent_len, 6000)
        self.assertEqual(scenario.procedure.procedure_interval, 4)  # already within 1–9
        self.assertEqual(scenario.main_steps, 6)

    def test_reflector_config_keeps_creation_fields_and_host_context(self):
        packet = replace(config_packet(self.s, self.host, OperationMode.CS_REFLECTOR), phy=2)
        scenario, host = apply_packet(replace(self.s, configuration=replace(self.s.configuration, mode=3)),
                                      self.host, packet)
        self.assertEqual((scenario.configuration.mode, scenario.configuration.role), (3, 1))
        self.assertEqual((host["phy"], host["creation_context"]), (2, 1))

    def test_negotiated_packets_replace_configuration_and_procedure(self):
        c = replace(self.s.configuration, id=2, t_fcs_time_us=100)
        p = replace(self.s.procedure, config_id=2, subevents_per_event=1, subevent_interval=0)
        scenario, _ = apply_packet(self.s, self.host, c)
        self.assertEqual(scenario.procedure.config_id, 2)
        scenario, _ = apply_packet(scenario, self.host, p)
        self.assertEqual((scenario.configuration, scenario.procedure), (c, p))
        self.assertEqual(source_label([c], "x"), NEGOTIATED_SOURCE)
        self.assertEqual(source_label([config_packet(self.s)], "x"), HOST_SOURCE)
        self.assertEqual(source_label([self.s], "x"), "x")

    def test_reported_connection_parameters_replace_the_acl_values(self):
        s = replace(self.s, connection=replace(self.s.connection, interval_min=12, interval_max=40, interval=24))
        reported = ConnectionParametersPacket(interval=16, latency=2, timeout=500, mtu=498)
        scenario, host = apply_packet(s, self.host, reported)
        a = scenario.connection
        # A live link has one interval, so the request narrows to it and stays valid.
        self.assertEqual((a.interval_min, a.interval, a.interval_max), (16, 16, 16))
        self.assertEqual((a.latency, a.timeout), (2, 500))
        self.assertEqual(validate(scenario), [])
        self.assertEqual(config_packet(scenario, host).connection_interval_min, 16)
        self.assertEqual(source_label([reported], "x"), CONNECTION_SOURCE)
        self.assertEqual(decode_config(reported.to_frame()), reported)

    def test_decode_accepts_packets_frames_and_wire_bytes(self):
        c = self.s.configuration
        self.assertIs(decode_config(c), c)
        self.assertEqual(decode_config(c.to_frame()), c)
        self.assertEqual(decode_config(Frame(c.PACKET_TYPE, c.to_frame().payload)), c)
        self.assertEqual(decode_config(c.to_bytes()), c)
        with self.assertRaises(TypeError):
            decode_config(LogMessagePacket(b"hi").to_frame())
        with self.assertRaises(TypeError):
            decode_config(Frame(0x7777, b""))
        with self.assertRaises(ValueError):
            decode_config(c.to_bytes()[:-1])

    def test_channel_list_sets_map(self):
        scenario = apply_channel_list(self.s, [40, 2, 3, *range(50, 62)])
        self.assertEqual(enabled_channels(scenario.configuration.channel_map), (2, 3, 40, *range(50, 62)))
        self.assertTrue(build_schedule(replace(scenario, target_steps=15)).complete)
        raw = channel_map_bytes((0, *range(2, 20)))
        self.assertEqual(apply_channel_list(self.s, raw).configuration.channel_map, raw)
        for bad in ([80], [-1], [True], [2.0]):
            with self.assertRaises(ValueError):
                apply_channel_list(self.s, bad)
        with self.assertRaises(ValueError):
            apply_channel_list(self.s, b"\xff" * 9)


if __name__ == "__main__":
    unittest.main()

class RequestedRangeTests(unittest.TestCase):
    def test_both_roles_preserve_ranges_and_edit_collapses(self):
        for mode in (OperationMode.CS_INITIATOR, OperationMode.CS_REFLECTOR):
            s = Scenario()
            packet = replace(config_packet(s, mode=mode), min_procedure_interval=1, max_procedure_interval=9,
                             min_subevent_len=4000, max_subevent_len=8000)
            scenario, host = apply_packet(s, {}, packet)
            self.assertEqual(config_packet(scenario, host, mode).to_bytes(), packet.to_bytes())
            edited = replace(scenario, procedure=replace(scenario.procedure, subevent_len=7000))
            emitted = config_packet(edited, host, mode)
            self.assertEqual((emitted.min_subevent_len, emitted.max_subevent_len), (7000, 7000))
            self.assertEqual((emitted.min_procedure_interval, emitted.max_procedure_interval), (1, 9))

    def test_preferred_t_pm_is_a_host_setting_of_the_cs_initiator(self):
        from cs_app.planner.bridge import HOST_DEFAULTS
        s = Scenario()
        self.assertEqual(HOST_DEFAULTS["t_pm"], 40)
        # It has no field in the host configuration packet, so the packet is unchanged.
        self.assertEqual(config_packet(s, {"t_pm": 40}).to_bytes(),
                         config_packet(s).to_bytes())
        # A negotiated report replaces the example T_PM and leaves the request alone.
        scenario, host = apply_packet(s, {"t_pm": 40}, replace(s.configuration, t_pm_time_us=20))
        self.assertEqual((scenario.configuration.t_pm_time_us, host["t_pm"]), (20, 40))
        for value in (0, 15, 80, "40"):
            with self.assertRaises(ValueError):
                config_packet(s, {"t_pm": value})
        with self.assertRaises(ValueError):
            config_packet(s, {"t_pm": 20}, OperationMode.CS_REFLECTOR)

    def test_negotiated_reports_do_not_change_requested_packet(self):
        s = Scenario()
        packet = config_packet(s)
        scenario, host = apply_packet(s, {}, packet)
        scenario, host = apply_packet(scenario, host, replace(s.procedure, subevent_len=6000, procedure_interval=8))
        scenario, host = apply_packet(scenario, host, replace(s.configuration, t_pm_time_us=40))
        self.assertEqual(config_packet(scenario, host).to_bytes(), packet.to_bytes())

    def test_main_mode_bounds_are_neutral_without_a_sub_mode(self):
        """The bounds order main-mode against sub-mode steps, so they are not sent without one (§14)."""
        base = Scenario()
        edited = replace(base.configuration, min_main_mode_steps=2, max_main_mode_steps=10)
        for mode in (0x01, 0x02, 0x03):
            packet = config_packet(replace(base, configuration=replace(edited, mode=mode)))
            self.assertEqual((packet.creation_min_main_mode_steps, packet.creation_max_main_mode_steps),
                             (1, 1), f"mode 0x{mode:02x} carried the disabled controls' values")
        for mode in (0x12, 0x32, 0x23):
            packet = config_packet(replace(base, configuration=replace(edited, mode=mode)))
            self.assertEqual((packet.creation_min_main_mode_steps, packet.creation_max_main_mode_steps),
                             (2, 10), f"mode 0x{mode:02x} lost the requested bounds")

    def test_neutral_main_mode_bounds_do_not_disturb_the_scenario(self):
        """Only the request is neutralised; the scenario keeps the values for when a sub-mode returns."""
        base = Scenario()
        edited = replace(base, configuration=replace(base.configuration, mode=0x02,
                                                     min_main_mode_steps=2, max_main_mode_steps=10))
        config_packet(edited)
        self.assertEqual((edited.configuration.min_main_mode_steps,
                          edited.configuration.max_main_mode_steps), (2, 10))
