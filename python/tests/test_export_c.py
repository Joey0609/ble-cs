from dataclasses import replace
import unittest
from ble_channel_sounding.planner.export_c import document, generate, load_document
from ble_channel_sounding.planner.bridge import config_packet
from ble_channel_sounding.planner.model import Scenario
from ble_channel_sounding.protocol.config import ClientConfig
from ble_channel_sounding.protocol.packets import PeripheralPatternsPacket


class ExportTests(unittest.TestCase):
    def test_both_roles_round_trip_and_setters(self):
        scenario = Scenario()
        host = {"peripheral_patterns": ["CS"]}
        output = generate(scenario, host, role="both")
        self.assertEqual(set(output), {"initiator", "reflector"})
        for role, source in output.items():
            recovered, settings = load_document(source)
            mode = 0 if role == "initiator" else 1
            # Each file re-imports with its own operation mode.
            self.assertEqual(recovered, replace(scenario, configuration=replace(scenario.configuration, role=mode)))
            packet = config_packet(recovered, settings, mode)
            crc = ClientConfig(mode, packet, PeripheralPatternsPacket.from_patterns(["CS"]) if mode == 0 else None,
                               t_pm=40 if mode == 0 else 10).crc32()
            self.assertIn(f"0x{crc:08x}U", source)
            self.assertIn(f"cs_{role}_config_set_procedure(config, &procedure)", source)
            self.assertEqual(settings["gap_role"], mode)
        self.assertNotIn("struct cs_config_creation", output["reflector"])
        self.assertIn("cs_initiator_config_set_creation", output["initiator"])

    def test_ipt_and_role_follow_the_plan(self):
        base = Scenario()
        for role, name in ((0, "initiator"), (1, "reflector")):
            scenario = replace(base, configuration=replace(base.configuration, role=role, cs_enhancements_1=1))
            host = {"gap_role": 1 - role, "peripheral_patterns": ["CS"]}
            source = generate(*load_document(document(scenario, host)), role=name)[name]
            self.assertIn(f"int cs_generated_config_{name}(", source)
            self.assertIn("IPT: requested", source)
            self.assertEqual("cs_initiator_config_enable_ipt(config)" in source, role == 0)
            self.assertEqual(load_document(source), (scenario, {**load_document(source)[1], **host}))

    def test_initiator_only_reflector_data(self):
        scenario = replace(Scenario(), configuration=replace(Scenario().configuration, cs_enhancements_1=1))
        host = {"peripheral_patterns": ["CS"], "peer_data": 1}
        output = generate(scenario, host, role="both")
        initiator, reflector = output["initiator"], output["reflector"]
        self.assertIn("/* Reflector data: none (initiator only) */", initiator)
        calls = [line.strip() for line in initiator.splitlines() if "_config_" in line and "err =" in line]
        # The setter follows enable_ipt, whose IPT bit cs_initiator_config_check_peer_data() requires.
        self.assertEqual(calls[-3:], ["err = cs_initiator_config_enable_ipt(config);",
                                      "err = cs_initiator_config_set_peer_data(config, CS_CONFIG_PEER_DATA_NONE);",
                                      "err = cs_initiator_config_set_t_pm(config, CS_CONFIG_T_PM_40_US);"])
        packet = config_packet(scenario, {**host, "gap_role": 0}, 0)
        crc = ClientConfig(0, packet, PeripheralPatternsPacket.from_patterns(["CS"]), None, 1, t_pm=40).crc32()
        self.assertIn(f"0x{crc:08x}U", initiator)
        self.assertNotIn("set_peer_data", reflector)
        self.assertIn("the initiator runs without RAS", reflector)
        self.assertNotIn("the initiator runs without RAS", generate(scenario, {**host, "peer_data": 0}, role="both")["reflector"])

    def test_preferred_t_pm(self):
        scenario = Scenario()
        host = {"peripheral_patterns": ["CS"], "t_pm": 40}
        output = generate(scenario, host, role="both")
        initiator, reflector = output["initiator"], output["reflector"]
        self.assertIn("/* Preferred T_PM: 40 us */", initiator)
        self.assertIn("err = cs_initiator_config_set_t_pm(config, CS_CONFIG_T_PM_40_US);", initiator)
        packet = config_packet(scenario, {**host, "gap_role": 0}, 0)
        crc = ClientConfig(0, packet, PeripheralPatternsPacket.from_patterns(["CS"]), t_pm=40).crc32()
        self.assertIn(f"0x{crc:08x}U", initiator)
        # SET_T_PM is a CS initiator setting, and 10 µs sends nothing.
        self.assertNotIn("set_t_pm", reflector)
        self.assertIn("/* Preferred T_PM: not set; the controller keeps its own preference (set by the initiator) */",
                      reflector)
        self.assertNotIn("set_t_pm", generate(scenario, {**host, "t_pm": 10}, role="initiator")["initiator"])
        # The plan file carries it.
        self.assertEqual(load_document(initiator)[1]["t_pm"], 40)

    def test_document_lists_every_host_setting(self):
        import json
        from ble_channel_sounding.planner.bridge import HOST_DEFAULTS
        settings = json.loads(document(Scenario()))["host_settings"]
        self.assertEqual(set(settings), {*HOST_DEFAULTS, "peripheral_patterns"})

    def test_bad_plan_or_missing_patterns_refused(self):
        with self.assertRaises(ValueError):
            generate(Scenario(), role="initiator")
        # A1:B2 needs two reflector antennas; the record would fail its setter at boot.
        a1_b2 = replace(Scenario(), procedure=replace(Scenario().procedure, tone_antenna_config_selection=4))
        with self.assertRaisesRegex(ValueError, "CS initiator: .*Set at least 2 bits"):
            generate(a1_b2, {"gap_role": 1}, role="initiator")
        self.assertIn(".preferred_peer_antenna = 3,",
                      generate(a1_b2, {"gap_role": 1, "preferred_peer_antenna": 3}, role="initiator")["initiator"])
        with self.assertRaises(ValueError):
            generate(replace(Scenario(), main_steps=0), {"gap_role": 1})

    def test_embedded_comment_and_utf8_are_safe(self):
        scenario = replace(Scenario(), provenance="quote */ comment")
        source = generate(scenario, {"peripheral_patterns": ['ä"*/']}, role="initiator")["initiator"]
        self.assertEqual(load_document(source)[0], scenario)
        self.assertIn('\\303\\244', source)

    def test_generated_helpers_compile_without_writing_c_sources(self):
        import shutil
        import subprocess
        from pathlib import Path
        compiler = shutil.which('cc')
        if not compiler:
            self.skipTest('No host C compiler')
        root = Path(__file__).resolve().parents[2]
        ipt = replace(Scenario(), configuration=replace(Scenario().configuration, cs_enhancements_1=1))
        sources = [*generate(Scenario(), {'peripheral_patterns': ['CS']}, role='both').values(),
                   generate(ipt, {'peripheral_patterns': ['CS'], 'peer_data': 1, 't_pm': 40,
                                  'log': {'console': 4, 'host': 1}}, role='initiator')['initiator'],
                   generate(Scenario(), {'peripheral_patterns': ['CS'], 't_pm': 20}, role='initiator')['initiator']]
        for source in sources:
            # Compile against the firmware interface (cs_generated_config/cs_generated_config.h) via stdin.
            result = subprocess.run([compiler, '-x', 'c', '-std=c11', '-Werror', '-fsyntax-only',
                                     '-I' + str(root / 'common/libs'), '-'],
                                    input=source, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
