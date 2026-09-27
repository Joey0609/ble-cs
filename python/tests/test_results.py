"""Checks for cs_app.results: pairing, mode-0 correction, RTT, capture loading and the Qt view."""

import cmath
from dataclasses import replace
import gc
import importlib.util
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from cs_app.protocol.packets import (CsCapabilitiesPacket, CsConfigurationPacket, CsInitiatorSubeventResultPacket,
                                 CsPeerDataPacket, CsReflectorSubeventResultPacket, CsStep, CsTone,
                                 LogMessagePacket, packet_to_dict)
from cs_app.results import (CORRECTION_COMPENSATION, CORRECTION_MEASURED, CORRECTION_NONE, CORRECTION_RESIDUAL,
                              MAX_PACKETS, ResultStore, analyze_pbr, analyze_rtt, centi_ppm, load_capture,
                              tone_pair_delay_us, unwrap)
from cs_app.simulator import RTT_DISTANCE_M, Simulator

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
GUI_AVAILABLE = all(importlib.util.find_spec(m) for m in ("PyQt6", "pyqtgraph"))
CHANNELS = (*range(2, 23), *range(26, 77))
DISTANCE_M = 3.0
OFFSET_PPM = 12.34
RTT_CHANNELS = (10, 20, 30, 40, 50, 60)
ROUND_TRIP_UNITS = 40  # 2·ToF in 0.5 ns: 20 ns of round trip, 2.998 m
RTT_DISTANCE = 299_792_458.0 * ROUND_TRIP_UNITS * 0.5e-9 / 2


def configuration():
    return CsConfigurationPacket(0, 2, 4, 4, 0, 2, 0, 1, 2, 1, 0, 0, 2, 0, 40, 40, 80, 10,
                                 bytes.fromhex("fcff7ffcffffffffff1f"))


def step(mode, channel, flags=0, offset=0, tones=()):
    return CsStep(mode, channel, flags, 0, 0, 0, 0, 0xFF, offset, 0, 0, 0, 0, 0, 0, tones)


def synthetic_packets(paths=2, compensation=0xC000):
    """A 3 m, 12.34 ppm procedure with the delay of the default configuration."""
    delay = tone_pair_delay_us(40, 10, paths)
    raw_offset = round(OFFSET_PPM * 100) & 0x7FFF
    ini = [step(0, 5, 0x02, raw_offset) for _ in range(2)]
    ref = [step(0, 5) for _ in range(2)]
    for channel in CHANNELS:
        f = (2402 + channel) * 1e6
        phase = -4 * math.pi * f * DISTANCE_M / 299_792_458.0 + 2 * math.pi * OFFSET_PPM * 1e-6 * f * delay * 1e-6
        a, b = 800 * cmath.exp(0.4j), 800 * cmath.exp(1j * (phase - 0.4))
        extension = CsTone(0, 0, 0, 3, 2)
        # Reverse path order to check tones are matched by antenna_path, not slot.
        ini.append(step(2, channel, tones=tuple(CsTone(round(a.real), round(a.imag), p, 0, 0)
                                                for p in reversed(range(paths))) + (extension,)))
        ref.append(step(2, channel, tones=tuple(CsTone(round(b.real), round(b.imag), p, 0, 0)
                                                for p in range(paths)) + (extension,)))
    header = (0, 10, 7, compensation, 0x7F, 0, 0, 0, 0, paths, 0xFF)
    return [configuration(), CsInitiatorSubeventResultPacket(*header, tuple(ini)),
            CsReflectorSubeventResultPacket(*header, tuple(ref))]


def ipt_packets(paths=2, reflector=True):
    """A 3 m, 12.34 ppm IPT procedure: the initiator's PCT already carries the two-way phase.

    The reflector (when present) reports its amplitude in I with Q zero, as IPT requires.
    """
    delay = tone_pair_delay_us(40, 10, paths)
    raw_offset = round(OFFSET_PPM * 100) & 0x7FFF
    ini = [step(0, 5, 0x02, raw_offset) for _ in range(2)]
    ref = [step(0, 5) for _ in range(2)]
    for channel in CHANNELS:
        f = (2402 + channel) * 1e6
        phase = -4 * math.pi * f * DISTANCE_M / 299_792_458.0 + 2 * math.pi * OFFSET_PPM * 1e-6 * f * delay * 1e-6
        a = 800 * cmath.exp(1j * phase)
        extension = CsTone(0, 0, 0, 3, 2)
        ini.append(step(2, channel, tones=tuple(CsTone(round(a.real), round(a.imag), p, 0, 0)
                                                for p in range(paths)) + (extension,)))
        ref.append(step(2, channel, tones=tuple(CsTone(500 + channel, 0, p, 0, 0)
                                                for p in range(paths)) + (extension,)))
    header = (0, 10, 7, 0xC000, 0x7F, 0, 0, 0, 0, paths, 0xFF)
    packets = [replace(configuration(), cs_enhancements_1=1),
               CsInitiatorSubeventResultPacket(*header, tuple(ini))]
    if reflector:
        packets.append(CsReflectorSubeventResultPacket(*header, tuple(ref)))
    else:
        packets.insert(1, CsPeerDataPacket(1))
    return packets


def rtt_step(mode, channel, time_difference, flags=0x05, aa_quality=0, bit_errors=0, tones=()):
    return CsStep(mode, channel, flags, aa_quality, bit_errors, -50, 1, 2, 0, time_difference,
                  0, 0, 0, 0, 0, tones)


def rtt_packets(paths=1):
    """Mode 0, then alternating mode-1 and mode-3 steps with a 3 m round trip.

    Each reflector reports a different turnaround error; the initiator's
    ToA−ToD includes it, so only (t_i − t_r) / 2 recovers the distance.
    """
    ini = [step(0, 5, 0x02, 0), step(0, 5)]
    ref = [step(0, 5), step(0, 5)]
    tones = tuple(CsTone(800, 0, p, 0, 0) for p in range(paths)) + (CsTone(0, 0, 0, 3, 2),)
    for n, channel in enumerate(RTT_CHANNELS):
        mode, turnaround = (1, 3)[n % 2], 7 * n - 20
        ini.append(rtt_step(mode, channel, turnaround + ROUND_TRIP_UNITS, tones=tones if mode == 3 else ()))
        ref.append(rtt_step(mode, channel, turnaround, tones=tones if mode == 3 else ()))
    header = (0, 11, 8, 0xC000, 0x7F, 0, 0, 0, 0, paths, 0xFF)
    return [configuration(), CsInitiatorSubeventResultPacket(*header, tuple(ini)),
            CsReflectorSubeventResultPacket(*header, tuple(ref))]


def replace_step(packet, index, **changes):
    steps = list(packet.steps)
    steps[index] = replace(steps[index], **changes)
    return replace(packet, steps=tuple(steps))


def procedure_of(packets):
    store = ResultStore()
    for packet in packets:
        store.add(packet)
    procedure, = store.procedures.values()
    return store, procedure


class RttTests(unittest.TestCase):
    def test_pairs_mode_1_and_3_and_recovers_distance(self):
        store, procedure = procedure_of(rtt_packets())
        steps, mismatched = procedure.rtt_steps()
        self.assertEqual(mismatched, 0)
        self.assertEqual([s.mode for s in steps], [1, 3] * 3)
        self.assertEqual([s.ordinal for s in steps], list(range(2, 2 + len(RTT_CHANNELS))))
        self.assertEqual(steps[0].initiator.nadm, 2)
        self.assertEqual(steps[0].reflector.rssi, -50)
        for s in steps:
            self.assertAlmostEqual(s.tof_ns, 10.0)
            self.assertAlmostEqual(s.distance_m, RTT_DISTANCE)
        result = analyze_rtt(steps)
        self.assertEqual((len(result.accepted), len(result.rejected)), (len(RTT_CHANNELS), 0))
        self.assertAlmostEqual(result.mean_m, RTT_DISTANCE)
        self.assertAlmostEqual(result.median_m, RTT_DISTANCE)
        self.assertAlmostEqual(result.std_m, 0.0)
        # Mode-3 steps also feed PBR.
        pbr, _ = procedure.pbr_steps(store.configurations[0])
        self.assertEqual([s.channel for s in pbr], list(RTT_CHANNELS[1::2]))

    def test_statistics(self):
        packets = rtt_packets()
        # Initiator step 2 (first RTT step) gets 8 more units: +0.6 m on one pair.
        packets[1] = replace_step(packets[1], 2, time_difference=packets[1].steps[2].time_difference + 8)
        result = analyze_rtt(procedure_of(packets)[1].rtt_steps()[0])
        extra = 299_792_458.0 * 8 * 0.25e-9
        distances = [RTT_DISTANCE + extra] + [RTT_DISTANCE] * 5
        self.assertAlmostEqual(result.mean_m, sum(distances) / 6)
        self.assertAlmostEqual(result.median_m, RTT_DISTANCE)
        mean = sum(distances) / 6
        self.assertAlmostEqual(result.std_m, math.sqrt(sum((d - mean) ** 2 for d in distances) / 5))

    def test_filters_invalid_time_difference_aa_quality_and_bit_errors(self):
        packets = rtt_packets()
        packets[1] = replace_step(packets[1], 2, flags=0x01)  # initiator time difference not valid
        packets[2] = replace_step(packets[2], 3, aa_quality=1, bit_errors=2)  # reflector AA bit errors
        packets[1] = replace_step(packets[1], 4, bit_errors=5)  # payload bit errors, AA fine
        steps, _ = procedure_of(packets)[1].rtt_steps()
        self.assertIsNone(steps[0].initiator.time_difference)
        self.assertIsNone(steps[0].distance_m)

        def accepted(**kwargs):
            return [s.ordinal for s in analyze_rtt(steps, **kwargs).accepted]
        self.assertEqual(accepted(), [4, 5, 6, 7])
        self.assertEqual(accepted(max_bit_errors=4), [5, 6, 7])
        self.assertEqual(accepted(aa_success_only=False), [3, 4, 5, 6, 7])
        self.assertEqual(accepted(aa_success_only=False, max_bit_errors=1), [5, 6, 7])
        empty = analyze_rtt(steps[:1])
        self.assertEqual((empty.mean_m, empty.median_m, empty.std_m), (None, None, None))
        self.assertIsNone(analyze_rtt(steps[1:2], aa_success_only=False).std_m)

    def test_mismatched_rtt_steps_are_counted_not_paired(self):
        packets = rtt_packets()
        packets[2] = replace_step(packets[2], 2, channel=11)
        packets[2] = replace(packets[2], steps=packets[2].steps[:-1])
        steps, mismatched = procedure_of(packets)[1].rtt_steps()
        self.assertEqual(len(steps), len(RTT_CHANNELS) - 2)
        self.assertEqual(mismatched, 2)

    def test_simulator_time_differences_are_plausible_and_deterministic(self):
        simulator = Simulator()
        values = simulator.rtt_time_differences(range(2000))
        self.assertEqual(values, simulator.rtt_time_differences(range(2000)))
        good = [(t_i - t_r) * 0.25e-9 * 299_792_458.0 for t_i, t_r, quality, _ in values if quality == 0]
        self.assertGreater(len(good), 1800)
        self.assertAlmostEqual(sum(good) / len(good), RTT_DISTANCE_M, delta=0.1)
        self.assertTrue(all(-2 ** 15 <= t < 2 ** 15 for t_i, t_r, _, _ in values for t in (t_i, t_r)))


class ModelTests(unittest.TestCase):
    def test_centi_ppm_decodes_15_bit_signed_and_not_available(self):
        self.assertEqual(centi_ppm(1234), 12.34)
        self.assertEqual(centi_ppm((-1234) & 0x7FFF), -12.34)
        self.assertIsNone(centi_ppm(0xC000))

    def test_unwrap_removes_2pi_jumps(self):
        values = unwrap([3.0, -3.0, 3.0 - 2 * math.pi - 0.5])
        self.assertAlmostEqual(values[1], -3.0 + 2 * math.pi)
        self.assertAlmostEqual(values[2], 3.0 - 0.5)

    def test_pairs_steps_and_mode0_correction_recovers_distance(self):
        store = ResultStore()
        for packet in synthetic_packets():
            store.add(packet)
        procedure, = store.procedures.values()
        steps, mismatched = procedure.pbr_steps(store.configurations[0])
        self.assertEqual((len(steps), mismatched), (len(CHANNELS), 0))
        self.assertEqual(steps[0].delay_us, (2 + 1) * (2 + 10) + 5 + 40)
        self.assertAlmostEqual(steps[0].measured_offset_ppm, OFFSET_PPM)
        for path in (0, 1):
            corrected = analyze_pbr(steps, path, CORRECTION_MEASURED)
            self.assertAlmostEqual(corrected.distance_corrected_m, DISTANCE_M, delta=0.01)
            self.assertEqual(len(corrected.points), len(CHANNELS))
        raw = analyze_pbr(steps, 0, CORRECTION_NONE)
        self.assertAlmostEqual(raw.distance_corrected_m, raw.distance_raw_m)
        bias = 299_792_458.0 * OFFSET_PPM * 1e-6 * steps[0].delay_us * 1e-6 / 2
        self.assertAlmostEqual(DISTANCE_M - raw.distance_raw_m, bias, delta=0.01)
        flipped = analyze_pbr(steps, 0, CORRECTION_MEASURED, sign=-1)
        self.assertAlmostEqual(DISTANCE_M - flipped.distance_corrected_m, 2 * bias, delta=0.01)

    def test_compensation_choices(self):
        store = ResultStore()
        for packet in synthetic_packets(compensation=200):
            store.add(packet)
        steps, _ = next(iter(store.procedures.values())).pbr_steps(store.configurations[0])
        self.assertEqual(steps[0].offset_ppm(CORRECTION_COMPENSATION), 2.0)
        self.assertAlmostEqual(steps[0].offset_ppm(CORRECTION_RESIDUAL), OFFSET_PPM - 2.0)
        self.assertIsNone(steps[0].offset_ppm(CORRECTION_NONE))

    def test_low_quality_tones_filtered(self):
        packets = synthetic_packets(paths=1)
        ini = packets[1]
        tones = list(ini.steps[2].tones)
        tones[0] = CsTone(tones[0].i, tones[0].q, 0, 2, 0)
        steps = list(ini.steps)
        steps[2] = replace(steps[2], tones=tuple(tones))
        packets[1] = replace(ini, steps=tuple(steps))
        store = ResultStore()
        for packet in packets:
            store.add(packet)
        pairs, _ = next(iter(store.procedures.values())).pbr_steps(store.configurations[0])
        self.assertEqual(len(analyze_pbr(pairs, 0).points), len(CHANNELS) - 1)
        self.assertEqual(len(analyze_pbr(pairs, 0, high_quality_only=False).points), len(CHANNELS))

    def test_capture_json_lines_and_binary_round_trip(self):
        packets = synthetic_packets() + [LogMessagePacket(b"hello"),
                                         CsCapabilitiesPacket(*([1] * 31))]
        text = "\n".join(json.dumps(packet_to_dict(p)) for p in packets).encode()
        for data in (text, b"".join(p.to_bytes() for p in packets)):
            loaded, errors = load_capture(data)
            self.assertEqual(errors, [])
            self.assertEqual(loaded, packets)
        store = ResultStore()
        for packet in loaded:
            store.add(packet)
        self.assertEqual(list(store.logs), ["hello"])
        self.assertEqual(store.t_sw_us(), 1)

    def test_capture_json_lines_skip_non_object_json(self):
        packet = LogMessagePacket(b"hello")
        text = (json.dumps(packet_to_dict(packet)) + "\n" + json.dumps("diagnostic") + "\n").encode()

        loaded, errors = load_capture(text)

        self.assertEqual(loaded, [packet])
        self.assertEqual(errors, ["line 2: JSON capture line must be an object, got str"])


class IptTests(unittest.TestCase):
    """Reflector data and IPT analysis (implementation_plan.md §1.6)."""

    def test_initiator_only_procedure_is_complete_and_ranges_from_the_initiator_pct(self):
        store, procedure = procedure_of(ipt_packets(reflector=False))
        self.assertEqual(procedure.peer_data, 1)
        self.assertTrue(procedure.complete)
        steps, mismatched = procedure.pbr_steps(store.configurations[0])
        self.assertEqual((len(steps), mismatched), (len(CHANNELS), 0))
        self.assertAlmostEqual(steps[0].measured_offset_ppm, OFFSET_PPM)
        self.assertTrue(all(sample.reflector == 1 for s in steps for sample in s.paths))
        for path in (0, 1):
            self.assertAlmostEqual(analyze_pbr(steps, path).distance_corrected_m, DISTANCE_M, delta=0.01)
        # RTT has no reflector timing: nothing to pair, no nominal turnaround substituted.
        self.assertEqual(procedure.rtt_steps(), ([], 0))

    def test_initiator_only_uses_the_initiator_tone_quality(self):
        packets = ipt_packets(paths=1, reflector=False)
        ini = packets[2]
        tone = ini.steps[2].tones[0]
        packets[2] = replace_step(ini, 2, tones=(replace(tone, quality=2),) + ini.steps[2].tones[1:])
        store, procedure = procedure_of(packets)
        steps, _ = procedure.pbr_steps(store.configurations[0])
        self.assertEqual(len(analyze_pbr(steps, 0).points), len(CHANNELS) - 1)
        self.assertEqual(len(analyze_pbr(steps, 0, high_quality_only=False).points), len(CHANNELS))

    def test_ipt_with_ras_uses_reflector_amplitude_only(self):
        store, procedure = procedure_of(ipt_packets())
        self.assertEqual(procedure.peer_data, 0)
        steps, _ = procedure.pbr_steps(store.configurations[0])
        self.assertEqual(sum(s.ipt_violations for s in steps), 0)
        self.assertEqual(steps[0].paths[0].reflector, complex(500 + CHANNELS[0], 0))
        self.assertAlmostEqual(analyze_pbr(steps, 0).distance_corrected_m, DISTANCE_M, delta=0.01)

    def test_ipt_reflector_quadrature_is_a_protocol_violation(self):
        packets = ipt_packets(paths=1)
        ref = packets[2]
        tones = ref.steps[2].tones
        packets[2] = replace_step(ref, 2, tones=(replace(tones[0], q=300),) + tones[1:])
        tones = packets[2].steps[3].tones
        packets[2] = replace_step(packets[2], 3, tones=(replace(tones[0], i=-40),) + tones[1:])
        store, procedure = procedure_of(packets)
        steps, _ = procedure.pbr_steps(store.configurations[0])
        self.assertEqual(sum(s.ipt_violations for s in steps), 2)
        # The quadrature is ignored and a negative amplitude clamped, so the phase stays the initiator's.
        self.assertEqual(steps[0].paths[0].reflector, complex(500 + CHANNELS[0], 0))
        self.assertEqual(steps[1].paths[0].reflector, 0)
        self.assertFalse(steps[0].paths[0].high_quality)
        self.assertEqual(len(analyze_pbr(steps, 0).points), len(CHANNELS) - 2)
        self.assertAlmostEqual(analyze_pbr(steps, 0).distance_corrected_m, DISTANCE_M, delta=0.01)
        # Without IPT the same reflector tone is an ordinary complex PCT.
        without = [replace(packets[0], cs_enhancements_1=0), *packets[1:]]
        store, procedure = procedure_of(without)
        steps, _ = procedure.pbr_steps(store.configurations[0])
        self.assertEqual(sum(s.ipt_violations for s in steps), 0)
        self.assertEqual(steps[0].paths[0].reflector, complex(500 + CHANNELS[0], 300))

    def test_ipt_uses_the_ipt_switch_period(self):
        store = ResultStore()
        caps = CsCapabilitiesPacket(*([1] * 31))
        store.add(replace(caps, t_sw_time=2, t_sw_ipt_time_supported=10))
        self.assertEqual(store.t_sw_us(configuration()), 2)
        self.assertEqual(store.t_sw_us(replace(configuration(), cs_enhancements_1=1)), 10)


@unittest.skipUnless(GUI_AVAILABLE, "Install the gui extra for Qt checks")
class ResultsGuiTests(unittest.TestCase):
    def test_tabs_render_every_report(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        window.show()
        for packet in synthetic_packets() + [LogMessagePacket(b"hello")]:
            window.add_packet(packet)
        window.refresh()
        app.processEvents()
        self.assertEqual(window.path_select.count(), 2)
        self.assertEqual(window.channel_table.rowCount(), len(CHANNELS))
        self.assertIn("corrected <b>3.00 m</b>", window.summary.text())
        # Results has no History tab or detail tables; the Session view shows the records.
        self.assertFalse(hasattr(window, "steps_table") or hasattr(window, "reports") or hasattr(window, "log"))
        model = window.session_view.model
        self.assertEqual(model.rowCount(), 4)
        self.assertEqual(model.data(model.index(3, 4)), "hello")
        self.assertEqual(window.rtt_table.rowCount(), 0)
        self.assertIn("0/0 RTT step pairs", window.rtt_summary.text())
        window.close()

    def test_sign_options_carry_their_own_help(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        window.show()
        for combo in (window.sign_select,):
            tips = [combo.itemData(i, Qt.ItemDataRole.ToolTipRole) for i in range(combo.count())]
            self.assertEqual(len(set(tips)), combo.count())  # one help text per option
            for index, tip in enumerate(tips):
                self.assertIn(combo.itemText(index), tip)
                self.assertIn("Δt", tip)
            self.assertIn("Δt", combo.toolTip())
        # The item tooltips need the popup open, so the control itself describes the option in use.
        for combo, label in ((window.sign_select, None),):
            seen = set()
            for index in range(combo.count()):
                combo.setCurrentIndex(index)
                tip = combo.toolTip()
                self.assertTrue(tip.startswith(f"<b>{combo.itemText(index)}</b>"))
                self.assertIn("Δt", tip)
                seen.add(tip)
                if label is not None:
                    self.assertEqual(label.toolTip(), tip)
            self.assertEqual(len(seen), combo.count())
        self.assertIn("applies to both the Mode-0 measured offset and reported frequency compensation lines",
                      window.sign_select.toolTip())
        window.close()

    def test_rtt_tab(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        window.show()
        packets = rtt_packets()
        packets[2] = replace_step(packets[2], 3, aa_quality=1)
        for packet in synthetic_packets() + packets:
            window.add_packet(packet)
        window.refresh()
        rtt_index = window.tabs.indexOf(window.rtt_page)
        window.tabs.setCurrentIndex(rtt_index)
        app.processEvents()
        self.assertEqual(window.tabs.tabText(rtt_index), "RTT")
        self.assertEqual(window.procedure_select.currentIndex(), 1)
        self.assertEqual(window.rtt_table.rowCount(), len(RTT_CHANNELS))
        self.assertIn("5/6 RTT step pairs accepted", window.rtt_summary.text())
        self.assertIn("mean <b>3.00 m</b>", window.rtt_summary.text())
        self.assertEqual(window.rtt_table.item(1, 14).text(), "no")
        self.assertTrue(window.rtt_histogram_plot.plotItem.items)
        estimates_index = window.tabs.indexOf(window.estimates_page)
        self.assertEqual(window.tabs.tabText(estimates_index), "Estimates")
        window.tabs.setCurrentIndex(estimates_index)
        self.assertFalse(window.pbr_controls.isHidden())
        self.assertFalse(window.rtt_controls.isHidden())
        trend = window.estimates_plot.plotItem.listDataItems()
        self.assertEqual([item.name() for item in trend], ["RTT mean", "RTT median", "PBR slope (raw)", "PBR slope (Mode-0 offset)",
                          "PBR slope (frequency compensation)"])
        self.assertTrue(window.estimate_curves["RTT mean"]._analysis_visible)
        self.assertTrue(window.estimate_curves["PBR slope (Mode-0 offset)"]._analysis_visible)
        self.assertFalse(window.estimates_table.isColumnHidden(4))
        self.assertFalse(window.estimates_table.isColumnHidden(8))
        self.assertEqual(window.estimates_table.rowCount(), 2)
        self.assertEqual(window.estimates_table.item(0, 4).text(), "3.00")
        window.aa_success_only.setChecked(False)
        self.assertIn("6/6 RTT step pairs accepted", window.rtt_summary.text())
        window.max_bit_errors.setValue(0)
        window.procedure_select.setCurrentIndex(0)
        self.assertEqual(window.rtt_table.rowCount(), 0)
        window.close()

    def test_follow_averages_procedures_received_since_last_redraw(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        for n in range(3):
            for packet in numbered(synthetic_packets(), n):
                window.add_packet(packet)
            if n == 0:
                window.refresh()
                self.assertEqual(window.channel_table.item(0, 2).text(), "1")
        window.refresh()
        app.processEvents()
        self.assertEqual(window.procedure_select.currentIndex(), 2)
        self.assertEqual(window.pbr_keys, ((0, 11, 1), (0, 12, 2)))
        self.assertIn("2 procedures averaged", window.summary.text())
        self.assertIn("corrected <b>3.00 m</b>", window.summary.text())
        self.assertEqual(window.channel_table.item(0, 2).text(), "2")
        window.refresh()  # nothing new: the average stays
        self.assertEqual(window.channel_table.item(0, 2).text(), "2")
        window.procedure_select.setCurrentIndex(1)
        self.assertEqual(window.channel_table.item(0, 2).text(), "1")
        self.assertIn("Procedure 1", window.summary.text())
        window.close()

    def test_estimates_keep_last_30_seconds(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        for n, arrival in enumerate((100.0, 120.0, 140.0)):
            for packet in numbered(synthetic_packets(paths=1), n):
                window.add_packet(packet, arrival)
        window.refresh()
        self.assertEqual([window.estimates_table.item(r, 0).text() for r in range(2)], ["40.000", "20.000"])
        curve = window.estimate_curves["PBR slope (Mode-0 offset)"]
        self.assertEqual(list(curve.xData), [20.0, 40.0])
        self.assertAlmostEqual(curve.yData[-1], DISTANCE_M, delta=0.01)
        self.assertTrue(window.estimate_curves["RTT mean"]._analysis_visible)
        self.assertFalse(window.estimates_table.isColumnHidden(4))
        self.assertFalse(window.estimates_table.isColumnHidden(8))
        self.assertEqual(set(window.estimates), {(0, 11, 1), (0, 12, 2)})
        self.assertIn("2 procedures (last 30 s)", window.estimates_summary.text())
        window.close()

    def test_replay_estimates_are_centered_on_selected_procedure(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        window = ResultsWidget(recording_playback=True)
        try:
            for n, arrival in enumerate((0.0, 20.0, 40.0, 60.0, 80.0)):
                for packet in numbered(synthetic_packets(paths=1), n):
                    window.add_packet(packet, arrival)
            window.refresh(average=False)

            # Procedure 2 is at 40 s; its replay window is 10–70 s.
            window.procedure_select.setCurrentIndex(2)
            app.processEvents()
            curve = window.estimate_curves["PBR slope (Mode-0 offset)"]
            self.assertEqual(list(curve.xData), [20.0, 40.0, 60.0])
            self.assertAlmostEqual(window.estimate_marker.value(), 40.0)
            self.assertIn("3 procedures (30 s around selected procedure)", window.estimates_summary.text())
        finally:
            window.close()

    def test_sign_change_refreshes_estimates(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        for packet in synthetic_packets(paths=1):
            window.add_packet(packet)
        window.refresh()
        before = list(window.estimate_curves["PBR slope (Mode-0 offset)"].yData)
        window.sign_select.setCurrentIndex(1)
        app.processEvents()
        after = list(window.estimate_curves["PBR slope (Mode-0 offset)"].yData)
        self.assertNotEqual(before, after)
        self.assertIn("PBR", window.estimates_summary.text())
        window.close()

    def test_requested_mode_refreshes_estimate_visibility(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        self.assertTrue(window.tabs.isTabVisible(window.tabs.indexOf(window.rtt_page)))
        self.assertTrue(window.tabs.isTabVisible(window.tabs.indexOf(window.pbr_page)))
        for packet in synthetic_packets(paths=1):
            window.add_packet(packet)
        window.refresh()
        self.assertTrue(window.tabs.isTabVisible(window.tabs.indexOf(window.rtt_page)))
        self.assertTrue(window.tabs.isTabVisible(window.tabs.indexOf(window.pbr_page)))
        window.set_measurement_mode(1)
        self.assertTrue(window.estimate_curves["RTT mean"]._analysis_visible)
        self.assertFalse(window.estimate_curves["PBR slope (Mode-0 offset)"]._analysis_visible)
        self.assertFalse(window.tabs.isTabVisible(window.tabs.indexOf(window.pbr_page)))
        self.assertTrue(window.tabs.isTabVisible(window.tabs.indexOf(window.rtt_page)))
        window.set_measurement_mode(2)
        self.assertFalse(window.estimate_curves["RTT mean"]._analysis_visible)
        self.assertTrue(window.estimate_curves["PBR slope (Mode-0 offset)"]._analysis_visible)
        self.assertTrue(window.tabs.isTabVisible(window.tabs.indexOf(window.pbr_page)))
        self.assertFalse(window.tabs.isTabVisible(window.tabs.indexOf(window.rtt_page)))
        for mode in (0x12, 0x32, 0x23):
            window.set_measurement_mode(mode)
            self.assertTrue(window.estimate_has_rtt)
            self.assertTrue(window.estimate_has_pbr)
            self.assertTrue(window.tabs.isTabVisible(window.tabs.indexOf(window.pbr_page)))
            self.assertTrue(window.tabs.isTabVisible(window.tabs.indexOf(window.rtt_page)))
        app.processEvents()
        window.close()

    def test_unchanged_mode_keeps_tab_and_estimates(self):
        # MainWindow.edited passes the mode on every configuration edit.
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        for packet in synthetic_packets(paths=1):
            window.add_packet(packet)
        window.refresh()
        window.set_measurement_mode(1)
        window.tabs.setCurrentWidget(window.estimates_page)
        cached = dict(window.estimates)
        self.assertTrue(cached)
        window.set_measurement_mode(1)
        self.assertIs(window.tabs.currentWidget(), window.estimates_page)
        self.assertEqual(window.estimates, cached)
        app.processEvents()
        window.close()

    def test_views_keep_only_the_newest_entries(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.results import MAX_LOGS, MAX_PACKETS
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        for n in range(MAX_PACKETS + 5):
            window.add_packet(LogMessagePacket(f"line {n}".encode()))
            window.add_packet(CsCapabilitiesPacket(*([1] * 31)))
            if n % 100 == 99:
                window.refresh()
        window.refresh()
        self.assertEqual(len(window.store.packets), MAX_PACKETS)
        self.assertEqual(window.store.packet_count, 2 * (MAX_PACKETS + 5))
        self.assertEqual(len(window.store.logs), MAX_LOGS)
        self.assertEqual(window.store.logs[-1], f"line {MAX_PACKETS + 4}")
        self.assertEqual(window.session_view.model.rowCount(), MAX_PACKETS)
        window.close()


def numbered(packets, n):
    """Procedure ``n`` of a run: the same reports with their own ACL event and counter."""
    return [packets[0]] + [replace(p, start_acl_conn_event=10 + n, procedure_counter=n) for p in packets[1:]]


class StoreLimitTests(unittest.TestCase):
    def test_oldest_procedures_are_dropped(self):
        store = ResultStore(max_procedures=2)
        for n in range(3):
            for packet in numbered(synthetic_packets(), n):
                store.add(packet, float(n))
        self.assertEqual(list(store.procedures), [(0, 11, 1), (0, 12, 2)])
        self.assertEqual(store.procedures[(0, 12, 2)].time, 2.0)
        self.assertEqual(store.origin, 0.0)


class HistoryModelTests(unittest.TestCase):
    def test_session_view_falls_back_when_history_was_closed(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        history = SessionHistory()
        window = ResultsWidget()
        try:
            window.begin_session(history)
            history.close()
            window.session_view.draw()
            self.assertEqual(window.session_view.model.rowCount(), 0)
            self.assertIsNone(window.session_history)
        finally:
            window.close()

    def test_history_view_follows_newest_without_selection_and_preserves_selection(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        try:
            window.add_packet(LogMessagePacket(b"newest"))
            view = window.session_view
            view.tree.scrollToBottom = Mock()
            view.draw()
            view.tree.scrollToBottom.assert_called_once_with()

            view.tree.setCurrentIndex(view.model.index(0, 0))
            view.tree.scrollToBottom = Mock()
            view.draw()
            # A selected record stops the view following the tail, and a row
            # that is already visible is never scrolled out from under the
            # pointer: the click that selected it must stay where the user put it.
            view.tree.scrollToBottom.assert_not_called()
            self.assertEqual(view.tree.currentIndex().row(), 0)
        finally:
            window.close()

    def _replay_view(self, procedures=4):
        """A stopped replay over a session history: the Session tab's browsing mode."""
        from PyQt6.QtWidgets import QApplication
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        history = SessionHistory()
        packets = [packet for n in range(procedures) for packet in numbered(synthetic_packets(paths=1), n)]
        for index, packet in enumerate(packets):
            history.append(packet, timestamp=float(index))
        history.flush()
        window = ResultsWidget(recording_playback=True)
        window.session_history = history
        for index, packet in enumerate(packets):
            window.store.add(packet, float(index))
        window.refresh(average=False)
        return app, window, history

    def _selected_record(self, view):
        """(highlighted record, record copied into the detail pane) as the user sees them."""
        entry = view.model.entry_for(view.tree.currentIndex())
        highlighted = None if entry is None else view.model._decoded_entry(entry).values
        table = view.selected_entry
        copied = tuple(table.item(0, column).text() for column in range(5)) if table.rowCount() else None
        return highlighted, copied

    def test_selected_row_and_detail_pane_are_the_same_record(self):
        app, window, history = self._replay_view()
        try:
            view = window.session_view
            row = next(r for r in range(view.model.rowCount())
                       if view.model.entry_for(view.model.index(r, 0)).kind == "subevent")
            view.tree.setCurrentIndex(view.model.index(row, 0))
            app.processEvents()
            highlighted, copied = self._selected_record(view)
            self.assertIsNotNone(copied)
            self.assertEqual(highlighted, copied)

            # A row the user reaches while the model is being refreshed arrives
            # with the selection signals blocked, so nothing would tell the
            # detail pane about it.  The two panes must still name one record.
            other = view.model.index(row + 1, 0)
            selection_model = view.tree.selectionModel()
            blocked = selection_model.blockSignals(True)
            view.tree.setCurrentIndex(other)
            selection_model.blockSignals(blocked)
            view.draw(force=True)
            app.processEvents()
            highlighted, copied = self._selected_record(view)
            self.assertIsNotNone(highlighted)
            self.assertEqual(highlighted, copied)
        finally:
            window.close()
            history.close()

    def test_search_keeps_the_selected_row_and_restores_it_when_cleared(self):
        app, window, history = self._replay_view()
        try:
            view = window.session_view
            row = next(r for r in range(view.model.rowCount())
                       if view.model.entry_for(view.model.index(r, 0)).kind == "subevent")
            view.tree.setCurrentIndex(view.model.index(row, 0))
            app.processEvents()
            _, copied = self._selected_record(view)

            view.search.setText("subevent")
            for _ in range(80):
                app.processEvents()
            highlighted, still_copied = self._selected_record(view)
            self.assertEqual(still_copied, copied)
            self.assertEqual(highlighted, copied)

            view.search.clear()
            for _ in range(80):
                app.processEvents()
            self.assertEqual(view.tree.currentIndex().row(), row)
            self.assertEqual(self._selected_record(view), (copied, copied))
        finally:
            window.close()
            history.close()

    def test_live_click_shows_the_record_and_keeps_following_the_tail(self):
        """A live row can be clicked; the tail goes on following the newest records (§7.9)."""
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        try:
            window.store = ResultStore(max_packets=4)
            for number in range(3):
                window.add_packet(LogMessagePacket(f"line {number}".encode()))
            window.set_running(True)
            view = window.session_view
            view.tree.setCurrentIndex(view.model.index(0, 0))
            app.processEvents()

            self.assertEqual(view.tree.currentIndex().row(), 0)
            self.assertEqual(view.selected_entry.rowCount(), 1)
            self.assertEqual(view.selected_entry.item(0, 5).text(), "Selected")
            self.assertEqual(view.record.topLevelItemCount(), 1)
            # The procedure detail reads the whole session and stays out of a live run.
            self.assertEqual(view.procedure_table.rowCount(), 0)
            view.tree.scrollToBottom = Mock()

            window.add_packet(LogMessagePacket(b"line 3"))
            view.draw()

            # The clicked record is still in the tail, so it keeps the highlight.
            self.assertEqual(view.model.data(view.model.index(view.tree.currentIndex().row(), 4)), "line 0")
            self.assertEqual(view.selected_entry.rowCount(), 1)
            view.tree.scrollToBottom.assert_called_once_with()
        finally:
            window.close()

    def test_live_eviction_drops_the_highlight_and_keeps_the_detail(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        try:
            window.store = ResultStore(max_packets=2)
            for number in range(2):
                window.add_packet(LogMessagePacket(f"line {number}".encode()))
            window.set_running(True)
            view = window.session_view
            view.tree.setCurrentIndex(view.model.index(0, 0))
            app.processEvents()
            view.tree.scrollToBottom = Mock()

            window.add_packet(LogMessagePacket(b"line 2"))
            view.draw()

            self.assertFalse(view.tree.currentIndex().isValid())
            self.assertEqual([view.model.data(view.model.index(row, 4)) for row in range(2)],
                             ["line 1", "line 2"])
            # The clicked record is a copied detail row, so it survives the
            # eviction that took its history row and its highlight away.
            self.assertEqual(view.selected_entry.rowCount(), 1)
            self.assertEqual(view.record.topLevelItemCount(), 1)
            view.tree.scrollToBottom.assert_called_once_with()
        finally:
            window.close()

    def test_session_filters_are_disabled_for_live_streams_but_available_for_playback(self):
        from PyQt6.QtWidgets import QApplication, QAbstractItemView
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        try:
            view = window.session_view
            window.set_running(True)
            self.assertFalse(view.search.isEnabled())
            self.assertFalse(view.types["log"].isEnabled())
            self.assertFalse(view.procedure_from.isEnabled())
            self.assertFalse(view.procedure_to.isEnabled())
            # Searching and filtering read the whole session; clicking a row reads
            # only the tail the view already holds, so rows stay selectable (§7.9).
            self.assertEqual(view.tree.selectionMode(), QAbstractItemView.SelectionMode.SingleSelection)

            window.set_running(False)
            self.assertTrue(view.search.isEnabled())
            self.assertTrue(view.types["log"].isEnabled())
            self.assertTrue(view.procedure_from.isEnabled())
            self.assertTrue(view.procedure_to.isEnabled())
            self.assertEqual(view.tree.selectionMode(), QAbstractItemView.SelectionMode.SingleSelection)

            playback = ResultsWidget(recording_playback=True)
            try:
                playback.set_running(True)
                playback_view = playback.session_view
                self.assertTrue(playback_view.search.isEnabled())
                self.assertTrue(playback_view.types["log"].isEnabled())
                self.assertTrue(playback_view.procedure_from.isEnabled())
                self.assertFalse(playback_view.model._live)
                self.assertEqual(playback_view.tree.selectionMode(),
                                 QAbstractItemView.SelectionMode.SingleSelection)
            finally:
                playback.close()
        finally:
            window.close()

    def test_history_model_ignores_parent_requests_for_removed_rows(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget
        from cs_app.views.session_view import HistoryModel, MemoryHistory

        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        try:
            source = MemoryHistory([(float(index), packet) for index, packet in enumerate(synthetic_packets())])
            model = HistoryModel()
            model.refresh(source, types=("subevent",))
            parent = model.index(0, 0)
            child = model.index(0, 0, parent)
            self.assertTrue(child.isValid())

            model.refresh(source, types=())
            self.assertFalse(model.parent(child).isValid())
        finally:
            window.close()

    def test_expanding_history_entry_keeps_child_parent_valid(self):
        from PyQt6.QtWidgets import QApplication, QTreeView
        from cs_app.views.session_view import HistoryModel, MemoryHistory

        app = QApplication.instance() or QApplication([])
        source = MemoryHistory([(float(index), packet)
                                for index, packet in enumerate(synthetic_packets(paths=1))])
        model = HistoryModel()
        model.refresh(source, types=("subevent", "report"))
        tree = QTreeView()
        try:
            tree.setModel(model)
            row = next(row for row in range(model.rowCount())
                       if model.rowCount(model.index(row, 0)) > 0)
            parent = model.index(row, 0)
            tree.expand(parent)
            app.processEvents()

            child = model.index(0, 0, parent)
            self.assertTrue(child.isValid())
            self.assertEqual(model.parent(child).row(), row)
        finally:
            tree.close()

    def test_live_history_entries_are_not_expandable(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.session_view import HistoryModel, MemoryHistory

        app = QApplication.instance() or QApplication([])
        source = MemoryHistory([(float(index), packet)
                                for index, packet in enumerate(synthetic_packets(paths=1))])
        model = HistoryModel()
        model.refresh(source, types=("subevent", "report"), live=True)
        row = next(row for row in range(model.rowCount())
                   if model.data(model.index(row, 2)) == "Subevent")
        parent = model.index(row, 0)
        self.assertEqual(model.rowCount(parent), 0)
        self.assertFalse(model.index(0, 0, parent).isValid())

    def test_live_history_model_requests_only_the_bounded_tail(self):
        from cs_app.views.session_view import HistoryModel, MemoryHistory

        class TrackingHistory(MemoryHistory):
            def snapshot(self, *, flush=True, limit=None):
                self.requested_limit = limit
                return super().snapshot(flush=flush, limit=limit)

        source = TrackingHistory([(float(index), LogMessagePacket(f"line {index}".encode()))
                                  for index in range(MAX_PACKETS + 1)])
        model = HistoryModel()
        model.refresh(source, types=("log",), live=True)
        self.assertEqual(source.requested_limit, MAX_PACKETS)
        self.assertEqual(model.rowCount(), MAX_PACKETS)

    def test_history_model_uses_full_session_after_stop_and_live_tail_while_running(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        history = SessionHistory()
        window = ResultsWidget()
        try:
            for number in range(1005):
                history.append(LogMessagePacket(f"line {number}".encode()), timestamp=float(number))
            history.flush()
            window.begin_session(history)
            window.set_running(False)
            view = window.session_view
            view.draw()
            self.assertEqual(view.model.rowCount(), 1005)
            window.set_running(True)
            self.assertEqual(view.model.rowCount(), 200)
            self.assertEqual(view.source_label.text(), "Live session")
            # Pause keeps the live tail until it is released; browsing filters
            # become available after the run stops.
            view.pause.setChecked(True)
            history.append(LogMessagePacket(b"line 1005"), timestamp=1005.0)
            history.flush()
            window.draw_history()
            self.assertEqual(view.model.data(view.model.index(199, 4)), "line 1004")
            view.pause.setChecked(False)
            self.assertEqual(view.model.data(view.model.index(199, 4)), "line 1005")
            window.set_running(False)
            self.assertEqual(view.source_label.text(), "Last session")
            view.search.setText("line 1004")
            for _ in range(20):
                app.processEvents()
            self.assertEqual(view.model.rowCount(), 1)
        finally:
            window.close()
            history.close()

    def test_stopped_history_indexes_outlive_the_bounded_entry_cache(self):
        """Browsing a stopped session must not leave Qt holding freed records.

        Disk mode caches only MAX_PACKETS records, so a QModelIndex that
        carried a HistoryEntry would be read back after that entry was
        dropped, and the crash it caused was a segmentation fault rather
        than a test failure.
        """
        from PyQt6.QtWidgets import QApplication
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget
        from cs_app.views.session_view import DISK_CACHE_ROWS, DISK_WINDOW_ROWS

        app = QApplication.instance() or QApplication([])
        history = SessionHistory()
        window = ResultsWidget()
        records = DISK_CACHE_ROWS + DISK_WINDOW_ROWS + 1
        try:
            for number in range(records):
                history.append(LogMessagePacket(f"line {number}".encode()), timestamp=float(number))
            history.flush()
            window.begin_session(history)
            window.set_running(False)
            model = window.session_view.model
            window.session_view.draw()
            self.assertEqual(model.rowCount(), records)

            # Walking the whole timeline evicts the earliest records.
            kept = [model.index(row, 4) for row in range(model.rowCount())]
            self.assertLessEqual(len(model._row_entries), DISK_CACHE_ROWS)
            self.assertTrue(all(index.internalPointer() is None for index in kept))
            gc.collect()
            self.assertEqual(model.data(kept[0]), "line 0")
            self.assertEqual(model.entry_for(kept[0]).index, 0)
        finally:
            window.close()
            history.close()

    def test_browsing_redraw_reads_only_the_records_it_shows(self):
        """Laying out a browsed session must not query and decode every record.

        The tree asks every row it lays out whether it has step children, and a
        browsed session lays out all of them, so answering that from the
        payload cost one index query and one decode per record on every redraw.
        """
        from PyQt6.QtWidgets import QApplication
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget
        from cs_app.views.session_view import DISK_WINDOW_ROWS

        app = QApplication.instance() or QApplication([])
        history = SessionHistory()
        window = ResultsWidget()
        records = 4 * DISK_WINDOW_ROWS
        subevent = CsInitiatorSubeventResultPacket(0, 10, 1, 0, -20, 0, 0, 0, 0, 1, 0,
                                                   (CsStep(1, 5, 5, 0, 0, -40, 1, 0, 0, 20, 0, 0, 0, 0, 0),))
        try:
            for number in range(records - 1):
                history.append(LogMessagePacket(f"line {number}".encode()), timestamp=float(number))
            history.append(subevent, timestamp=float(records))
            history.flush()
            window.begin_session(history)
            window.set_running(False)
            view, model = window.session_view, window.session_view.model
            view.draw()
            self.assertEqual(model.rowCount(), records)

            read, entries_from = history.read, history.entries_from
            calls = {"read": 0, "windows": 0}

            def counted_read(entry):
                calls["read"] += 1
                return read(entry)

            def counted_entries_from(position, count, **filters):
                calls["windows"] += 1
                return entries_from(position, count, **filters)

            history.read, history.entries_from = counted_read, counted_entries_from
            view.draw(force=True)
            self.assertLessEqual(calls["read"], 50)
            self.assertLessEqual(calls["windows"], records // DISK_WINDOW_ROWS + 2)

            # The index still says which rows can be expanded, and expanding one decodes it.
            self.assertTrue(model.hasChildren(model.index(records - 1, 0)))
            self.assertFalse(model.hasChildren(model.index(0, 0)))
            self.assertEqual(model.rowCount(model.index(records - 1, 0)), len(subevent.steps))
        finally:
            window.close()
            history.close()

    def test_moving_the_highlight_repaints_the_timeline(self):
        """One row is highlighted at a time, so the row a highlight leaves is repainted.

        The view repaints the rows a selection change touches from the
        selection model's signals, and the timeline moves the highlight with
        those signals blocked, so it asks for the repaint itself.
        """
        from PyQt6.QtWidgets import QApplication
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        history = SessionHistory()
        window = ResultsWidget()
        try:
            for number in range(20):
                history.append(LogMessagePacket(f"line {number}".encode()), timestamp=float(number))
            history.flush()
            window.begin_session(history)
            window.set_running(False)
            view, model = window.session_view, window.session_view.model
            view.draw()
            viewport = view.tree.viewport()
            viewport.update = Mock()
            for row in (2, 5, 9):
                view._select_row(model.index(row, 0))
                self.assertEqual([index.row() for index in view.tree.selectionModel().selectedRows()], [row])
            self.assertEqual(viewport.update.call_count, 3)

            viewport.update.reset_mock()
            view.draw(force=True)
            self.assertTrue(viewport.update.called)
        finally:
            window.close()
            history.close()

    def test_session_view_says_where_a_truncated_history_starts(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget
        app = QApplication.instance() or QApplication([])
        one = LogMessagePacket(b"0")
        history = SessionHistory(max_bytes=2 * (len(one.to_bytes()) + 32), segment_bytes=len(one.to_bytes()) + 32)
        window = ResultsWidget()
        try:
            for number in range(4):
                history.append(LogMessagePacket(str(number).encode()), timestamp=float(number))
            history.flush()
            window.begin_session(history)
            view = window.session_view
            view.draw()
            self.assertFalse(view.truncation_label.isHidden())
            self.assertIn("kept history starts at 2.000 s", view.truncation_label.text())
            self.assertEqual(view.model.data(view.model.index(0, 0)), "2.000 s")
            self.assertEqual(view.model.rowCount(), 2)
        finally:
            window.close()
            history.close()

    def test_history_host_and_peer_filters_keep_failures_visible(self):
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        history = SessionHistory()
        window = ResultsWidget()
        try:
            history.append_host('warning', 'host', 'start refused', timestamp=1.0)
            history.append_host('info', 'peer', 'peer ready', timestamp=2.0)
            history.flush()
            window.begin_session(history)
            window.set_running(False)
            view = window.session_view
            view.draw()
            self.assertEqual(view.model.rowCount(), 2)
            self.assertEqual(view.counts_label.text(), "1 warnings · 0 errors")
            view.types['host'].setChecked(False)
            app.processEvents()
            self.assertEqual(view.model.rowCount(), 2)  # peer plus warning host
            view.types['peer'].setChecked(False)
            app.processEvents()
            self.assertEqual(view.model.rowCount(), 1)  # warning host is never hidden
            self.assertEqual(view.model.data(view.model.index(0, 1)), "Host")
        finally:
            window.close()
            history.close()

    def test_selecting_an_evicted_procedure_loads_the_detail_pane_from_history(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        history = SessionHistory()
        window = ResultsWidget()
        try:
            for packet in synthetic_packets(paths=1):
                history.append(packet)
            history.flush()
            window.begin_session(history)
            window.set_running(False)
            view = window.session_view
            view.draw()
            for row in range(view.model.rowCount()):
                index = view.model.index(row, 0)
                if "Subevent" in view.model.data(view.model.index(row, 2)):
                    view.tree.setCurrentIndex(index)
                    app.processEvents()
                    break
            self.assertEqual([view.detail.tabText(index) for index in range(view.detail.count())],
                             ["Selected entry", "Record", "Procedure", "Subevents", "Steps"])
            self.assertIs(view.detail.currentWidget(), view.record)
            self.assertEqual(view.steps_table.rowCount(), 2 * (2 + len(CHANNELS)))
            self.assertEqual(view.procedure_table.rowCount(), 7)
            self.assertEqual(view.subevent_table.rowCount(), 2)
            # The record pane shows the selected subevent parsed.
            record = view.record.topLevelItem(0)
            self.assertEqual(record.text(0), "CsInitiatorSubeventResult")
            fields = {record.child(n).text(0): record.child(n).text(1) for n in range(record.childCount())}
            self.assertEqual(fields["procedure_counter"], "7")
        finally:
            window.close()
            history.close()

    def test_live_click_fills_the_procedure_detail_from_the_decoded_store(self):
        """A live tail fills Procedure, Subevents and Steps without reading the session.

        The store the run is already filling is keyed by the same procedure
        key as the history index, so the detail costs a lookup rather than the
        whole-session scan a live run must not do (implementation_plan.md §7.9).
        """
        from PyQt6.QtWidgets import QApplication
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        history = SessionHistory()
        window = ResultsWidget()
        try:
            window.begin_session(history)
            window.set_running(True)
            for packet in synthetic_packets(paths=1):
                history.append(packet)
                window.add_packet(packet)
            history.flush()
            view = window.session_view
            view.draw()
            self.assertTrue(view._live_tail())
            scanned = []
            history.iter_entries = lambda *a, **k: scanned.append(1) or ()
            rows = [row for row in range(view.model.rowCount())
                    if "Subevent" in (view.model.data(view.model.index(row, 2)) or "")]
            self.assertEqual(len(rows), 2)
            view.tree.setCurrentIndex(view.model.index(rows[0], 0))
            app.processEvents()
            self.assertEqual(scanned, [])
            self.assertEqual(view.procedure_table.rowCount(), 7)
            self.assertEqual(view.subevent_table.rowCount(), 2)
            self.assertEqual(view.steps_table.rowCount(), 2 * (2 + len(CHANNELS)))
            self.assertEqual([view.subevent_table.item(row, 0).text() for row in range(2)],
                             ["Initiator", "Reflector"])
            # A procedure the bounded store no longer holds leaves the three
            # tabs empty rather than reading the session for it.
            window.store.procedures.clear()
            view.tree.setCurrentIndex(view.model.index(rows[1], 0))
            app.processEvents()
            self.assertEqual(scanned, [])
            self.assertEqual(view.procedure_table.rowCount(), 0)
            self.assertEqual(view.subevent_table.rowCount(), 0)
            self.assertEqual(view.steps_table.rowCount(), 0)
        finally:
            window.close()
            history.close()

    def test_replay_history_selection_updates_all_analysis_views(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        window = ResultsWidget(recording_playback=True)
        try:
            first = numbered(synthetic_packets(paths=1), 0)
            second = numbered(rtt_packets(paths=1), 1)
            for packet in first:
                window.add_packet(packet, timestamp=0.0)
            for packet in second:
                window.add_packet(packet, timestamp=10.0)
            window.refresh(average=False)

            view = window.session_view
            first_key = (0, 10, 0)
            selected_row = next(row for row in range(view.model.rowCount())
                                if view.model.entry_for(view.model.index(row, 0)).procedure_key == first_key)
            view.tree.setCurrentIndex(view.model.index(selected_row, 0))
            app.processEvents()

            self.assertTrue(view.tree.currentIndex().isValid())
            self.assertEqual(window.procedure_select.currentData(), first_key)
            self.assertEqual(window.pbr_keys, (first_key,))
            self.assertIn("Procedure 0", window.summary.text())
            self.assertEqual(window.rtt_table.rowCount(), 0)
            self.assertTrue(window.estimate_marker.isVisible())
            self.assertAlmostEqual(window.estimate_marker.value(), 0.0)
        finally:
            window.close()

    def test_replay_selection_restores_evicted_procedure_and_neighbor(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.results import ResultStore
        from cs_app.session_history import SessionHistory
        from cs_app.views.controller_view import ControllerView
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        first = numbered(synthetic_packets(paths=1), 0)
        second = numbered(rtt_packets(paths=1), 1)
        packets = first + second
        history = SessionHistory()
        for index, packet in enumerate(packets):
            history.append(packet, timestamp=float(index))
        history.flush()
        controller = ControllerView()
        controller.replay = Mock()
        window = ResultsWidget(controller=controller, recording_playback=True)
        try:
            # Simulate the bounded live store retaining only the newest
            # procedure while Session history retains both procedures.
            window.store = ResultStore(max_procedures=1)
            for index, packet in enumerate(packets):
                window.store.add(packet, float(index))
            window.session_history = history
            window.refresh(average=False)

            first_key = (0, 10, 0)
            view = window.session_view
            selected_row = next(row for row in range(view.model.rowCount())
                                if view.model.entry_for(view.model.index(row, 0)).procedure_key == first_key)
            view.tree.setCurrentIndex(view.model.index(selected_row, 0))
            app.processEvents()

            self.assertTrue(view.tree.currentIndex().isValid())
            self.assertEqual(view.model.entry_for(view.tree.currentIndex()).procedure_key, first_key)
            self.assertEqual(window.procedure_select.currentData(), first_key)
            self.assertEqual(set(window.store.procedures), {first_key, (0, 11, 1)})
            self.assertIn("Procedure 0", window.summary.text())
            self.assertEqual(window.estimates_table.rowCount(), 2)
            controller.replay.assert_not_called()
        finally:
            window.close()
            history.close()

    def test_replay_dropdown_lists_history_procedures_the_store_dropped(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.results import ResultStore
        from cs_app.session_history import SessionHistory
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        procedures = [numbered(synthetic_packets(paths=1), n) for n in range(5)]
        history = SessionHistory()
        for index, packet in enumerate(packet for batch in procedures for packet in batch):
            history.append(packet, timestamp=float(index))
        history.flush()
        window = ResultsWidget(recording_playback=True)
        try:
            # The decoded store keeps one procedure; Session history keeps all five.
            window.store = ResultStore(max_procedures=1)
            for index, packet in enumerate(packet for batch in procedures for packet in batch):
                window.store.add(packet, float(index))
            window.session_history = history
            window.refresh(average=False)

            keys = [(0, 10 + n, n) for n in range(5)]
            selector = window.procedure_select
            self.assertEqual([selector.itemData(item) for item in range(selector.count())], keys)
            self.assertTrue(selector.itemText(0).startswith("Procedure 0 · config 0 · ACL 10 · "))
            self.assertIn("1I/1R", selector.itemText(0))
            self.assertEqual(selector.currentData(), keys[-1])

            # Choosing a procedure the store dropped decodes it on demand.
            selector.setCurrentIndex(1)
            app.processEvents()
            self.assertEqual(selector.currentData(), keys[1])
            self.assertIn(keys[1], window.store.procedures)
            self.assertEqual(window.pbr_keys, (keys[1],))
            self.assertIn("Procedure 1", window.summary.text())
            # The list still offers every procedure of the session.
            self.assertEqual([selector.itemData(item) for item in range(selector.count())], keys)
        finally:
            window.close()
            history.close()

    def test_replay_dropdown_lists_all_procedures_but_live_shows_only_current(self):
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtWidgets import QApplication, QComboBox
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        packets = (numbered(synthetic_packets(paths=1), 0), numbered(rtt_packets(paths=1), 1))
        replay = ResultsWidget(recording_playback=True)
        live = ResultsWidget()
        try:
            for batch in packets:
                for packet in batch:
                    replay.add_packet(packet)
                    live.add_packet(packet)
            replay.refresh(average=False)
            live.set_running(True)
            live.refresh(average=False)

            self.assertIsInstance(replay.procedure_select, QComboBox)
            self.assertEqual(replay.procedure_select.maxVisibleItems(), 10)
            self.assertEqual(replay.procedure_select.count(), 2)
            self.assertEqual(live.procedure_select.count(), 1)
            self.assertEqual(live.procedure_select.currentData(), (0, 11, 1))

            selector = replay.procedure_select
            selector.show()
            selector.showPopup()
            app.processEvents()
            row_height = selector.view().sizeHintForRow(0)
            frame = 2 * selector.view().frameWidth()
            # Two procedures give a two-row popup, not ten rows of empty space.
            self.assertEqual(selector.view().height(), 2 * row_height + frame)
            selector.hidePopup()

            for index in range(11):
                selector.addItem(f"Procedure {index + 1}", index)
            app.processEvents()
            selector.showPopup()
            app.processEvents()
            self.assertEqual(selector.maxVisibleItems(), 10)
            self.assertEqual(selector.view().verticalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.assertTrue(selector.view().verticalScrollBar().isVisible())
            self.assertEqual(selector.view().height(), 10 * row_height + frame)
            # The popup hangs under the selector rather than floating where the
            # selected row would cover it.
            anchor = selector.mapToGlobal(QPoint(0, selector.height()))
            popup = selector.view().window()
            self.assertIsNot(popup, selector.window())
            self.assertEqual(popup.geometry().top(), anchor.y())
            # The offscreen platform nudges a popup window by its frame width.
            self.assertLessEqual(abs(popup.geometry().left() - anchor.x()), 2)
            self.assertGreaterEqual(popup.width(), selector.width())
            selector.hidePopup()
        finally:
            replay.close()
            live.close()

    def test_hdf5_capture_uses_the_same_history_model(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.recorder import RunRecorder
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        try:
            with TemporaryDirectory() as directory:
                path = Path(directory) / "capture.h5"
                recorder = RunRecorder(path, write_config=False, description="saved\nnotes")
                recorder.record(LogMessagePacket(b"from hdf5"))
                recorder.close()
                window.open_capture_path(path)
                view = window.session_view
                self.assertEqual(view.model.rowCount(), 1)
                self.assertEqual(view.model.data(view.model.index(0, 4)), "from hdf5")
                self.assertEqual(window.description_text, "saved\nnotes")
                # The Session tab shows the capture, with its description in the header.
                self.assertEqual(view.source_label.text(), "Capture: capture.h5")
                self.assertEqual(view.description_label.text(), "saved notes")
                self.assertFalse(view.save_session_button.isEnabled())
        finally:
            window.close()

    def test_hdf5_capture_fills_the_controller_tab(self):
        """A record carries its own controller reports and the configuration its host asked for."""
        from dataclasses import fields
        from PyQt6.QtWidgets import QApplication
        from cs_app.planner.bridge import config_packet
        from cs_app.planner.model import Scenario
        from cs_app.protocol.packets import (CapabilitiesSource, ClientState, ClientStatePacket, OperationMode,
                                             PeerDataPacket, TpmPacket)
        from cs_app.recorder import RunRecorder
        from cs_app.views.controller_view import ControllerView
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        controller = ControllerView()
        window = ResultsWidget(controller=controller)
        requested = config_packet(Scenario(), {}, OperationMode.CS_INITIATOR)
        caps = replace(CsCapabilitiesPacket(*([0] * len(fields(CsCapabilitiesPacket)))),
                       source=CapabilitiesSource.LOCAL, num_antennas_supported=4)
        try:
            with TemporaryDirectory() as directory:
                path = Path(directory) / "capture.h5"
                recorder = RunRecorder(path, write_config=False)
                # A first link whose reports the teardown drops, then the one the record ends on.
                recorder.record(replace(configuration(), id=1))
                recorder.record(ClientStatePacket(ClientState.LINK_DISCONNECTED, 0, 0, 0))
                for packet in (requested, PeerDataPacket(1), TpmPacket(20)):
                    recorder.record(packet, direction="tx")
                recorder.record(caps)
                recorder.record(configuration())
                recorder.close()

                window.open_capture_path(path)

                self.assertGreater(controller.capabilities.rowCount(), 20)
                self.assertEqual(controller.capabilities.horizontalHeaderItem(1).text(), "Local")
                self.assertGreater(controller.configuration.rowCount(), 0)
                self.assertIn("ID 0", controller.configuration_box.title())
                self.assertEqual(controller.requested, requested)
                self.assertEqual(controller.requested_peer_data, 1)
                self.assertEqual(controller.requested_t_pm, 20)
                # The negotiated mode of the record decides which analyses the tabs show.
                self.assertEqual(window.measurement_mode, configuration().mode)
                # The reports of the link the record left behind are not mixed in.
                self.assertEqual(list(controller.reports.configurations), [0])
        finally:
            window.close()

    def test_opening_session_config_json_follows_hdf5_companion(self):
        from PyQt6.QtWidgets import QApplication
        from cs_app.recorder import RunRecorder
        from cs_app.views.results_view import ResultsWidget

        app = QApplication.instance() or QApplication([])
        window = ResultsWidget()
        try:
            with TemporaryDirectory() as directory:
                recording = Path(directory) / "session_hostless_cs_run.h5"
                config = Path(directory) / "config_session_hostless_cs_run.json"
                recorder = RunRecorder(recording, write_config=False)
                recorder.record(LogMessagePacket(b"from session"))
                recorder.close()
                config.write_text("{\"planner\": true}\n")

                window.open_capture_path(config)

                self.assertEqual(window.capture_path, recording)
                self.assertEqual(window.session_view.source_label.text(),
                                 "Capture: session_hostless_cs_run.h5")
                self.assertEqual(window.session_view.model.rowCount(), 1)
                self.assertEqual(window.session_view.model.data(window.session_view.model.index(0, 4)),
                                 "from session")
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
