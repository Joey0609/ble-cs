"""Standalone cs_planner: timing examples, boundary checks and package independence."""

import ast
from dataclasses import replace
import json
from pathlib import Path
import unittest

from cs_planner.channels import HAT, X_PATTERN, cr1, shape_sequence
from cs_planner.model import (ALLOWED_CHANNELS, Scenario, build_schedule, channel_map_bytes, check_encoding, dumps,
                              enabled_channels, loads, step_segments, validate)

PYTHON_DIR = Path(__file__).resolve().parents[1]


def imported_modules(package: Path):
    """Absolute module names imported anywhere under a package directory."""
    names = set()
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module)
    return names


class PackageIndependenceTests(unittest.TestCase):
    def test_cs_planner_does_not_import_cs_app(self):
        self.assertFalse({n for n in imported_modules(PYTHON_DIR / "cs_planner") if n.split(".")[0] == "cs_app"})

    def test_cs_app_does_not_import_cs_planner(self):
        self.assertFalse({n for n in imported_modules(PYTHON_DIR / "cs_app") if n.split(".")[0] == "cs_planner"})

    def test_reads_existing_planner_file_with_host_settings(self):
        s = loads((PYTHON_DIR / "cs-plan.json").read_text(encoding="utf-8"))
        self.assertEqual(s.configuration.channel_map.hex(), "fcff7ffcffffffffff1f")
        self.assertEqual(json.loads(dumps(s, {"host_settings": {"gap_role": 1}}))["host_settings"], {"gap_role": 1})


class PlannerTimingTests(unittest.TestCase):
    def setUp(self):
        # Timing fixtures exercise the four-path case explicitly. The application
        # default is A1:B1 because the client has one local antenna.
        scenario = Scenario()
        # The timing examples use 32-bit sounding and a main-mode run of 4.
        self.s = replace(scenario, main_steps=4, configuration=replace(
            scenario.configuration, rtt_type=1, min_main_mode_steps=4, max_main_mode_steps=4),
            procedure=replace(scenario.procedure, tone_antenna_config_selection=3,
                              max_procedure_len=700, procedure_interval=14))

    def test_scenario_uses_mandatory_timing_defaults(self):
        c = Scenario().configuration
        self.assertEqual((c.t_ip1_time_us, c.t_ip2_time_us, c.t_fcs_time_us, c.t_pm_time_us),
                         (145, 145, 150, 40))

    def test_timing_help_lists_values_and_controller_selection_factors(self):
        from cs_planner.control_help import (CONTROLLER_SELECTED_WARNING, CONTROL_DETAILS, EXAMPLE_CONTROL_HELP,
                                             TAB_HELP, TIMING_MANDATORY_VALUES)
        expected = {
            "configuration.t_ip1_time_us": "10, 20, 30, 40, 50, 60, 80, 145 µs",
            "configuration.t_ip2_time_us": "10, 20, 30, 40, 50, 60, 80, 145 µs",
            "configuration.t_fcs_time_us": "15, 20, 30, 40, 50, 60, 80, 100, 120, 150 µs",
            "configuration.t_pm_time_us": "10, 20, 40 µs",
        }
        factors = (
            "Channel Sounding Configuration procedure",
            "Channel Sounding Capabilities Exchange",
            "local controller's capability bitmask",
            "peer controller's capability bitmask/constraint",
            "mandatory or conditional support",
        )
        for key, values in expected.items():
            tooltip = EXAMPLE_CONTROL_HELP[key]
            standard = CONTROL_DETAILS[key].standard
            selection = CONTROL_DETAILS[key].selection
            mandatory = TIMING_MANDATORY_VALUES[key]
            self.assertIn(f"Possible values: {values}.", tooltip)
            self.assertIn(f"Possible values: {values}.", standard)
            self.assertIn(f"mandatory supported value is {mandatory}", tooltip)
            self.assertIn(f"mandatory supported value is {mandatory}", standard)
            self.assertIn(f"mandatory supported value is {mandatory}", selection)
            self.assertNotIn("Warning:", standard)
            self.assertNotIn("Warning:", selection)
            for factor in factors:
                self.assertIn(factor, tooltip, key)
                self.assertIn(factor, selection, key)
            if key == "configuration.t_ip2_time_us":
                self.assertIn("reflector's T_IP2_IPT capability", tooltip)
                self.assertIn("reflector's T_IP2_IPT capability", selection)
        self.assertTrue(all(factor in TAB_HELP["CS modes"][-1] for factor in factors))
        self.assertIn("Possible values are T_IP1/T_IP2 = 10, 20, 30, 40, 50, 60, 80 or 145 µs", CONTROLLER_SELECTED_WARNING)

    def test_baseline_modes_and_mode3_guard_periods(self):
        # LE 2M, 32-bit sounding, four paths, SW=2, PM=40, IP1/IP2=145.
        expected = {0: 297, 1: 239, 2: 575, 3: 679}
        for mode, duration in expected.items():
            parts = step_segments(self.s, mode)
            self.assertEqual(sum(x.duration for x in parts), duration)
            self.assertEqual(parts[-1].start + parts[-1].duration, duration)
        mode3 = step_segments(self.s, 3)
        self.assertEqual([x.label for x in mode3].count("T_GD"), 2)
        self.assertIn("T_IP2", [x.label for x in mode3])

    def test_mode0_never_inherits_rtt_sequence(self):
        s = replace(self.s, configuration=replace(self.s.configuration, rtt_type=6, cs_sync_phy=1))
        self.assertEqual(sum(x.duration for x in step_segments(s, 0)), 333)
        self.assertEqual(sum(x.duration for x in step_segments(s, 1)), 499)

    def test_extension_slots_included_in_both_directions(self):
        parts = step_segments(self.s, 2)
        self.assertEqual(sum(p.duration for p in parts if p.label == "Extension"), 80)
        self.assertEqual(len([p for p in parts if p.label == "T_SW"]), 10)

    def test_exact_boundary_no_trailing_frequency_gap(self):
        # 2*297 + 4*575 + 5*150 = 3644 µs for four measurements.
        p = replace(self.s.procedure, subevent_len=3644)
        result = build_schedule(replace(self.s, procedure=p, target_steps=4))
        self.assertTrue(result.complete)
        self.assertEqual(len(result.subevents), 1)
        self.assertEqual(result.duration, 3644)
        smaller = build_schedule(replace(self.s, procedure=replace(p, subevent_len=3643), target_steps=4))
        self.assertTrue(smaller.complete)
        self.assertEqual(len(smaller.subevents), 2)

    def test_event_spacing_and_last_subevent_slot(self):
        # 18 measurements per full subevent; 72 measurements => 4 subevents.
        result = build_schedule(self.s)
        self.assertTrue(result.complete)
        self.assertEqual([se.start for se in result.subevents],
                         [0, 7500, 30000, 37500, 60000, 67500, 90000, 97500,
                          120000, 127500, 150000, 157500, 180000, 187500, 210000])
        self.assertEqual(result.event_count, 8)
        self.assertEqual(result.duration, 212194)

    def test_repetition_costs_time_without_advancing_workload(self):
        s = replace(self.s, configuration=replace(self.s.configuration, main_mode_repetition=3))
        result = build_schedule(s)
        self.assertEqual(result.completed_steps, 72)
        self.assertEqual(len(result.subevents), 28)
        self.assertEqual(sum(st.repeated for se in result.subevents for st in se.steps), 68)

    def test_cadence_continues_across_subevents(self):
        s = replace(self.s, configuration=replace(self.s.configuration, mode=0x12), target_steps=50)
        result = build_schedule(s)
        fresh = [st.mode for se in result.subevents for st in se.steps if st.mode and not st.repeated]
        self.assertEqual(fresh, [1 if i % 5 == 4 else 2 for i in range(50)])

    def test_unused_mode_fields_hold_their_defaults(self):
        from cs_planner.model import (PBR_FIELDS, PBR_HOST_FIELDS, RTT_FIELDS, RTT_HOST_FIELDS, SUB_MODE_FIELDS,
                                 apply_mode_defaults, scenario_value, unused_fields, unused_host_fields)
        self.assertEqual(unused_fields(1), SUB_MODE_FIELDS + PBR_FIELDS)
        self.assertEqual(unused_fields(2), SUB_MODE_FIELDS + RTT_FIELDS)
        self.assertEqual(unused_fields(3), SUB_MODE_FIELDS)
        for mode in (0x12, 0x32, 0x23):
            self.assertEqual(unused_fields(mode), ())
            self.assertEqual(unused_host_fields(mode), ())
        self.assertEqual(unused_host_fields(1), PBR_HOST_FIELDS)
        self.assertEqual(unused_host_fields(2), RTT_HOST_FIELDS)
        self.assertEqual(unused_fields("2"), ())
        default = Scenario()
        self.assertEqual(apply_mode_defaults(default), default)
        self.assertEqual(validate(default), [])
        c = replace(self.s.configuration, mode=1, t_pm_time_us=40, cs_enhancements_1=1, min_main_mode_steps=6)
        s = apply_mode_defaults(replace(self.s, configuration=c, t_sw_us=10, main_steps=6))
        for key in SUB_MODE_FIELDS + PBR_FIELDS:
            self.assertEqual(scenario_value(s, key), scenario_value(default, key), key)
        self.assertEqual(s.configuration.rtt_type, 1)  # Mode 1 uses the RTT sequence
        # Controllers report the reserved main-mode step fields as 0 without a sub-mode.
        from cs_planner.model import inactive_fields
        self.assertEqual(inactive_fields(replace(default, procedure=replace(default.procedure, subevents_per_event=1)))
                         ["procedure.subevent_interval"], 0)
        self.assertIn("t_sw_us", inactive_fields(replace(default, configuration=replace(default.configuration, cs_enhancements_1=1))))
        self.assertEqual(unused_host_fields(3, 1), ("creation_context",))
        reported = replace(self.s, configuration=replace(self.s.configuration, min_main_mode_steps=0,
                                                         max_main_mode_steps=0), main_steps=0)
        self.assertEqual(validate(apply_mode_defaults(reported)), [])

    def test_duration_limit_is_not_successful_workload_completion(self):
        s = replace(self.s, procedure=replace(self.s.procedure, max_procedure_len=10))
        result = build_schedule(s)
        self.assertFalse(result.complete)
        self.assertLess(result.completed_steps, s.target_steps)
        self.assertLessEqual(result.duration, 6250)
        self.assertEqual(len(result.subevents), 1)

    def test_unfittable_prefix_does_not_emit_mode0_only_subevent(self):
        c = replace(self.s.configuration, mode=3, cs_sync_phy=1, rtt_type=6,
                    mode_0_steps=3, t_ip1_time_us=145, t_ip2_time_us=145,
                    t_pm_time_us=40, t_fcs_time_us=150)
        s = replace(self.s, configuration=c, t_sw_us=10,
                    procedure=replace(self.s.procedure, subevent_len=1250))
        result = build_schedule(s)
        self.assertFalse(result.subevents)
        self.assertIn("No fresh step fits", result.stop_reason)

    def test_step_and_subevent_limits(self):
        # Enough channel cycles that the step/subevent limits, not channels, close the procedure.
        s = replace(self.s, target_steps=256, configuration=replace(self.s.configuration, channel_map_repetition=4),
                    procedure=replace(self.s.procedure,
            subevent_len=50000, subevents_per_event=1, subevent_interval=0,
            event_interval=2, max_procedure_len=300, procedure_interval=8))
        result = build_schedule(s)
        self.assertFalse(result.complete)
        self.assertLessEqual(sum(len(se.steps) for se in result.subevents), 256)
        self.assertTrue(all(len(se.steps) <= 160 for se in result.subevents))
        self.assertLessEqual(len(result.subevents), 32)

    def test_supervision_timeout_strict_boundary(self):
        a = replace(self.s.connection, latency=4, timeout=30)
        errors = validate(replace(self.s, connection=a))
        self.assertTrue(any("Supervision" in e for e in errors))
        self.assertFalse(any("Supervision" in e for e in validate(replace(self.s, connection=replace(a, timeout=31)))))

    def test_invalid_schedules_are_reported(self):
        for p in (replace(self.s.procedure, subevent_interval=8),
                  replace(self.s.procedure, subevents_per_event=1),
                  replace(self.s.procedure, config_id=3)):
            result = build_schedule(replace(self.s, procedure=p))
            self.assertTrue(result.errors)
            self.assertFalse(result.subevents)

    def test_operation_mode_and_ipt_validation(self):
        c = self.s.configuration

        def errors(**changes):
            return validate(replace(self.s, configuration=replace(c, **changes)))
        self.assertFalse(errors(role=1))
        self.assertTrue(any("Operation mode" in e for e in errors(role=2)))
        self.assertTrue(any("IPT bit" in e for e in errors(cs_enhancements_1=2)))
        self.assertTrue(any("IPT needs" in e for e in errors(mode=1, cs_enhancements_1=1)))
        for mode in (2, 3, 0x12, 0x32, 0x23):
            self.assertFalse(errors(mode=mode, cs_enhancements_1=1), hex(mode))
        ipt = replace(self.s, configuration=replace(c, cs_enhancements_1=1, role=1))
        self.assertEqual(loads(dumps(ipt)), ipt)
        # IPT substitutes T_SW_IPT for T_SW; with equal values the durations match.
        duration = lambda s, mode: sum(part.duration for part in step_segments(s, mode))
        self.assertEqual(duration(ipt, 2), duration(self.s, 2))
        labels = {part.label for part in step_segments(ipt, 2)}
        self.assertIn("T_SW_IPT", labels)
        self.assertIn("T_IP2 (IPT)", labels)
        self.assertNotIn("T_SW", labels)
        slower = replace(ipt, t_sw_ipt_us=10)
        paths = 4  # this timing fixture explicitly uses A4:B1
        self.assertEqual(duration(slower, 2) - duration(ipt, 2), 2 * (paths + 1) * (10 - 2))
        self.assertEqual(duration(replace(self.s, t_sw_ipt_us=10), 2), duration(self.s, 2))  # ignored without IPT
        self.assertTrue(any("Unsupported IPT" in e for e in validate(replace(ipt, t_sw_ipt_us=3))))
        self.assertTrue(any(note.startswith("IPT requested") and "45 µs" in note for note in build_schedule(ipt).notes))
        self.assertTrue(any(note.startswith("IPT requested") for note in build_schedule(ipt).notes))

    def test_planner_file_round_trip_and_field_widths(self):
        restored = loads(dumps(self.s))
        self.assertEqual(restored, self.s)
        self.assertFalse(check_encoding(restored))
        self.assertTrue(check_encoding(replace(self.s, procedure=replace(self.s.procedure, selected_tx_power=200))))
        with self.assertRaises(ValueError):
            loads(dumps(replace(self.s, connection=replace(self.s.connection, interval=1))))

    def test_import_rejects_fractional_indices_and_boolean_counts(self):
        for key, value in (("preview_count", 2.5), ("target_steps", True)):
            with self.assertRaises(ValueError):
                loads(dumps(replace(self.s, **{key: value})))

    def test_single_procedure_does_not_require_repeat_spacing(self):
        p = replace(self.s.procedure, procedure_count=1, procedure_interval=1)
        self.assertTrue(build_schedule(replace(self.s, procedure=p)).complete)
        repeated = build_schedule(replace(self.s, procedure=replace(p, procedure_count=2)))
        self.assertTrue(any("repetition interval" in e for e in repeated.errors))

    def test_spacing_and_timeout_corrections_give_sufficient_values(self):
        bad = replace(self.s, procedure=replace(self.s.procedure, subevent_interval=1))
        errors = validate(bad)
        self.assertTrue(all("\nCorrect: " in e for e in errors))
        self.assertTrue(any("at least 9 × 625 µs" in e for e in errors))
        self.assertFalse(validate(replace(bad, procedure=replace(bad.procedure, subevent_interval=9))))
        bad = replace(self.s, connection=replace(self.s.connection, latency=4, timeout=30))
        self.assertTrue(any("at least 31 × 10 ms" in e for e in validate(bad)))
        self.assertFalse(validate(replace(bad, connection=replace(bad.connection, timeout=31))))

    def test_cs_event_leaves_a_millisecond_of_the_acl_interval(self):
        # The 2026-09-24/25 client runs: a 37 ms subevent in a 37.5 ms interval, refused with HCI 0x20.
        a = replace(self.s.connection, interval_min=30, interval_max=30, interval=30)
        p = replace(self.s.procedure, subevents_per_event=1, subevent_interval=0, event_interval=2,
                    subevent_len=37000, max_procedure_len=80, procedure_interval=2)
        errors = validate(replace(self.s, connection=a, procedure=p))
        self.assertTrue(any("at least 1000 µs shorter than the ACL interval" in e and "at most 36500 µs" in e
                            for e in errors))
        self.assertFalse(validate(replace(self.s, connection=a, procedure=replace(p, subevent_len=36500))))
        # The controller caps the reservation at the procedure budget: 20 × 625 µs fits.
        self.assertFalse(validate(replace(self.s, connection=a, procedure=replace(p, max_procedure_len=20))))

    def test_timeout_fix_does_not_recommend_out_of_range_value(self):
        bad = replace(self.s, connection=replace(self.s.connection, latency=499,
                      interval=3200, interval_min=3200, interval_max=3200))
        self.assertTrue(any("required timeout exceeds" in e and "Reduce Peripheral latency" in e for e in validate(bad)))

    def test_early_closure_identifies_budget_to_change(self):
        result = build_schedule(replace(self.s, procedure=replace(self.s.procedure, max_procedure_len=10)))
        self.assertIn("Increase Procedure budget to at least 15 × 625 µs", result.stop_reason)
        more = build_schedule(replace(self.s, procedure=replace(self.s.procedure, max_procedure_len=15)))
        self.assertGreater(more.completed_steps, result.completed_steps)

    def test_channel_map_helpers_round_trip_and_default_uses_all_allowed(self):
        self.assertEqual(len(ALLOWED_CHANNELS), 72)
        self.assertEqual(enabled_channels(self.s.configuration.channel_map), ALLOWED_CHANNELS)
        channels = (2, 3, 40, 76)
        self.assertEqual(enabled_channels(channel_map_bytes(channels)), channels)

    def test_channel_map_validation_counts_allowed_channels(self):
        def with_map(channels):
            return replace(self.s, configuration=replace(self.s.configuration, channel_map=channel_map_bytes(channels)))
        self.assertFalse(validate(with_map(range(2, 17))))
        self.assertTrue(any("currently 14" in e for e in validate(with_map(range(2, 16)))))
        self.assertTrue(any("clear reserved" in e for e in validate(with_map((*range(2, 17), 24)))))

    def test_csa3c_parameters_checked_only_when_selected(self):
        c = replace(self.s.configuration, ch3c_jump=0, ch3c_shape=5)
        self.assertFalse(validate(replace(self.s, configuration=c)))
        bad = replace(self.s, configuration=replace(c, channel_selection_type=1))
        self.assertTrue(any("CSA #3c" in e for e in validate(bad)))
        good = replace(bad, configuration=replace(bad.configuration, ch3c_jump=8, ch3c_shape=1))
        self.assertFalse(validate(good))

    def test_cr1_is_a_permutation(self):
        import random
        channels = list(range(2, 40))
        shuffled = cr1(random.Random(3), channels)
        self.assertEqual(sorted(shuffled), channels)
        self.assertNotEqual(shuffled, channels)

    def test_csa3c_shapes_follow_table_4_2(self):
        # Jump 2: rising ramp from 1, falling ramp from 76; hat keeps the ramps separate.
        hat = shape_sequence(HAT, 2, iteration=0, start_jitter=0)
        self.assertEqual(hat[:3], [1, 3, 5])
        self.assertEqual(hat[39:42], [76, 74, 72])
        # Jump 3 (seq1 = 77 > seq2 = 0): X interleaves the falling and rising ramps, s1 first.
        self.assertEqual(shape_sequence(X_PATTERN, 3, 0, 0)[:4], [77, 0, 74, 3])
        # Offset shifts starts; out-of-range leading values (78 + 2 = 80) are skipped.
        self.assertEqual(shape_sequence(HAT, 4, 0, 2)[:2], [2, 6])

    def test_non_mode0_channels_cover_map_once_per_3b_cycle(self):
        channels = (*range(2, 23),)
        s = replace(self.s, target_steps=21, configuration=replace(self.s.configuration, channel_map=channel_map_bytes(channels)))
        result = build_schedule(s)
        self.assertTrue(result.complete)
        steps = [st for se in result.subevents for st in se.steps]
        self.assertEqual(sorted(st.channel for st in steps if st.mode), list(channels))
        self.assertTrue(all(st.channel in channels for st in steps))
        self.assertEqual(result.channel_cycles, 1)

    def test_procedure_closes_when_channel_cycles_are_exhausted(self):
        result = build_schedule(replace(self.s, target_steps=100))
        self.assertFalse(result.complete)
        self.assertEqual(result.completed_steps, 72)
        self.assertIn("Increase Map repetition to at least 2", result.stop_reason)
        s = replace(self.s, target_steps=100, configuration=replace(self.s.configuration, channel_map_repetition=2))
        self.assertTrue(build_schedule(s).complete)

    def test_mode1_submode_and_repeated_steps_reuse_channels(self):
        c = replace(self.s.configuration, mode=0x12, main_mode_repetition=2)
        result = build_schedule(replace(self.s, configuration=c, target_steps=50))
        steps = [st for se in result.subevents for st in se.steps]
        for before, step in zip(steps, steps[1:]):
            if step.mode == 1 and not step.repeated:
                self.assertEqual(step.channel, before.channel)
        second, first = result.subevents[1], result.subevents[0]
        fresh_main = [st for st in first.steps if st.mode == 2 and not st.repeated][-2:]
        repeated = [st for st in second.steps if st.repeated]
        self.assertEqual([(st.mode, st.channel) for st in repeated], [(st.mode, st.channel) for st in fresh_main])

    def test_channel_seed_changes_example_but_not_timing(self):
        a = build_schedule(self.s)
        b = build_schedule(replace(self.s, channel_seed=2))
        self.assertEqual([(st.start, st.mode) for se in a.subevents for st in se.steps],
                         [(st.start, st.mode) for se in b.subevents for st in se.steps])
        self.assertNotEqual([st.channel for se in a.subevents for st in se.steps],
                            [st.channel for se in b.subevents for st in se.steps])

    def test_csa3c_schedule_and_repetition_limit(self):
        c = replace(self.s.configuration, channel_selection_type=1, ch3c_shape=X_PATTERN, ch3c_jump=6, channel_map_repetition=3)
        result = build_schedule(replace(self.s, configuration=c, target_steps=100))
        self.assertTrue(result.complete, result.stop_reason)
        self.assertTrue(all(st.channel in ALLOWED_CHANNELS for se in result.subevents for st in se.steps))
        errors = validate(replace(self.s, configuration=replace(c, ch3c_jump=2)))
        self.assertTrue(any("allows at most 1" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
