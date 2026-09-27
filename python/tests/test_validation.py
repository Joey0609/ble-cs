from dataclasses import replace
import unittest
from cs_app.planner.bridge import config_packet
from cs_app.planner.model import Scenario
from cs_app.validation import validate_patterns, validate_preferred_peer_antenna, validate_radio_test
from cs_app.protocol.packets import OperationMode, PeripheralPatternsPacket, RadioTxTestConfigPacket

RADIO = RadioTxTestConfigPacket(0, 0, 3, 0, 0, 0, 0, 80, 10, 50, 100, 100, 0, 255)


class ValidationTests(unittest.TestCase):
    def test_patterns_utf8_bytes_and_padding(self):
        self.assertFalse(validate_patterns(["ä" * 16]))
        for bad in ([], ["ä" * 17], [""], ["x\0y"], ["x"] * 9):
            self.assertTrue(validate_patterns(bad))
        p = PeripheralPatternsPacket.from_patterns(["CS"])
        self.assertFalse(validate_patterns(p))
        self.assertTrue(validate_patterns(replace(p, patterns=p.patterns[:31] + b'x' + p.patterns[32:])))

    def test_radio_active_fields_and_widths(self):
        self.assertFalse(validate_radio_test(RADIO))
        self.assertTrue(validate_radio_test(replace(RADIO, channel=81)))
        self.assertTrue(validate_radio_test(replace(RADIO, phy=6)))
        self.assertFalse(validate_radio_test(replace(RADIO, phy=6, channel=11)))
        self.assertFalse(validate_radio_test(replace(RADIO, test_type=3, phy=6)))
        for bad in (replace(RADIO, test_type=3, sweep_start_channel=81),
                    replace(RADIO, test_type=5, duty_cycle=100),
                    replace(RADIO, test_type=6, tx_time_us=0),
                    replace(RADIO, packet_count=2**32)):
            self.assertTrue(validate_radio_test(bad))
        self.assertFalse(validate_radio_test(replace(RADIO, duty_cycle=0)))

    def test_preferred_peer_antenna_covers_the_peer_side(self):
        # As cs_*_config_set_procedure(): B bits for an initiator, A bits for a reflector.
        def errors(selection, mask, mode=OperationMode.CS_INITIATOR):
            scenario = replace(Scenario(), procedure=replace(Scenario().procedure,
                                                             tone_antenna_config_selection=selection))
            return validate_preferred_peer_antenna(config_packet(scenario, {"preferred_peer_antenna": mask}, mode))

        self.assertFalse(errors(0, 1))
        self.assertIn("Set at least 2 bits, for example 3", errors(4, 4)[0])  # A1:B2 with antenna 3 only
        self.assertFalse(errors(4, 3))
        self.assertFalse(errors(4, 1, OperationMode.CS_REFLECTOR))
        self.assertTrue(errors(1, 8, OperationMode.CS_REFLECTOR))  # A2:B1
        self.assertFalse(errors(1, 8))
        for mask in (0, 0x11):
            self.assertTrue(errors(0, mask))
        self.assertFalse(validate_preferred_peer_antenna(RADIO))

