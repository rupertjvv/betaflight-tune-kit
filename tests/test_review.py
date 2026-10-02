"""The review checks, and the filter plan they are meant to agree with."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bftune import dump, plan, review
from bftune.airframe import PRESETS, Airframe

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
EXAMPLE = os.path.join(FIXTURES, "example_diff.txt")


def titles(findings):
    return [f.title for f in findings]


def find(findings, fragment):
    for finding in findings:
        if fragment.lower() in finding.title.lower():
            return finding
    return None


class TestRpmFilter(unittest.TestCase):

    def test_rpm_filter_without_bidirectional_dshot_is_an_error(self):
        tune = dump.parse("set rpm_filter_harmonics = 3\nset dshot_bidir = OFF")
        finding = find(review.review(tune), "no data")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.ERROR)

    def test_the_fixture_trips_that_check(self):
        # The example dump has the RPM filter on with dshot_bidir OFF, which
        # is the single most common way to have no filtering while believing
        # you do.
        findings = review.review(dump.parse_file(EXAMPLE))
        self.assertIsNotNone(find(findings, "no data"))

    def test_a_correctly_configured_rpm_filter_is_quiet(self):
        tune = dump.parse("set rpm_filter_harmonics = 3\nset dshot_bidir = ON")
        self.assertIsNone(find(review.review(tune), "no data"))

    def test_bidirectional_dshot_without_the_rpm_filter_is_a_warning(self):
        tune = dump.parse("set rpm_filter_harmonics = 0\nset dshot_bidir = ON")
        finding = find(review.review(tune), "RPM filter is off")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.WARNING)

    def test_mismatched_pole_count_is_an_error(self):
        tune = dump.parse("set rpm_filter_harmonics = 3\n"
                          "set dshot_bidir = ON\nset motor_poles = 12")
        frame = Airframe(5, 6, 1900, motor_poles=14, bidirectional_dshot=True)
        finding = find(review.review(tune, frame), "pole count")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.ERROR)

    def test_matching_pole_count_is_quiet(self):
        tune = dump.parse("set rpm_filter_harmonics = 3\n"
                          "set dshot_bidir = ON\nset motor_poles = 14")
        frame = Airframe(5, 6, 1900, motor_poles=14, bidirectional_dshot=True)
        self.assertIsNone(find(review.review(tune, frame), "pole count"))

    def test_excessive_harmonics_are_noted(self):
        tune = dump.parse("set rpm_filter_harmonics = 6\nset dshot_bidir = ON")
        finding = find(review.review(tune), "harmonics")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.NOTE)


class TestNotchRange(unittest.TestCase):

    def test_inverted_range_is_an_error(self):
        tune = dump.parse("set dyn_notch_min_hz = 600\nset dyn_notch_max_hz = 200")
        finding = find(review.review(tune), "inverted")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.ERROR)

    def test_ceiling_below_full_throttle_noise_is_a_warning(self):
        tune = dump.parse("set dyn_notch_min_hz = 100\nset dyn_notch_max_hz = 300")
        finding = find(review.review(tune, PRESETS["5inch-6s"]), "full throttle")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.WARNING)

    def test_floor_above_hover_noise_is_a_warning(self):
        frame = PRESETS["5inch-6s"]
        tune = dump.parse("set dyn_notch_min_hz = %d\nset dyn_notch_max_hz = 900"
                          % int(frame.hover_hz + 100))
        finding = find(review.review(tune, frame), "floor")
        self.assertIsNotNone(finding)

    def test_a_range_matching_the_airframe_is_quiet(self):
        frame = PRESETS["5inch-6s"]
        low, high = frame.dyn_notch_range()
        tune = dump.parse("set dyn_notch_min_hz = %d\nset dyn_notch_max_hz = %d"
                          % (low, high))
        findings = review.review(tune, frame)
        self.assertIsNone(find(findings, "full throttle"))
        self.assertIsNone(find(findings, "floor"))

    def test_frequency_checks_are_skipped_without_an_airframe(self):
        tune = dump.parse("set dyn_notch_min_hz = 100\nset dyn_notch_max_hz = 300")
        self.assertIsNone(find(review.review(tune), "full throttle"))

    def test_the_plan_it_generates_passes_its_own_review(self):
        # The two halves of the tool must not disagree with each other.
        for name, frame in PRESETS.items():
            generated = plan.filter_plan(frame)
            tune = plan.apply_to(dump.Tune(), generated)
            findings = review.review(tune, frame)
            problems = [f for f in findings
                        if f.severity in (review.ERROR, review.WARNING)]
            self.assertEqual(problems, [],
                             msg="%s: %s" % (name, titles(problems)))


class TestNotchCount(unittest.TestCase):

    def test_too_many_notches_is_a_warning(self):
        tune = dump.parse("set dyn_notch_count = 8")
        self.assertIsNotNone(find(review.review(tune), "many dynamic notches"))

    def test_the_default_count_is_quiet(self):
        tune = dump.parse("set dyn_notch_count = 3")
        self.assertIsNone(find(review.review(tune), "many dynamic notches"))

    def test_a_very_high_q_is_noted(self):
        tune = dump.parse("set dyn_notch_q = 800")
        self.assertIsNotNone(find(review.review(tune), "narrow"))


class TestLowpass(unittest.TestCase):

    def test_inverted_dynamic_lowpass_is_an_error(self):
        tune = dump.parse("set gyro_lpf1_dyn_min_hz = 500\n"
                          "set gyro_lpf1_dyn_max_hz = 200")
        finding = find(review.review(tune), "lowpass range is inverted")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.ERROR)

    def test_disabled_lowpass_is_a_warning(self):
        tune = dump.parse("set gyro_lpf1_static_hz = 0")
        self.assertIsNotNone(find(review.review(tune), "disabled"))

    def test_a_normal_lowpass_is_quiet(self):
        tune = dump.parse("set gyro_lpf1_static_hz = 250")
        self.assertIsNone(find(review.review(tune), "disabled"))


class TestDterm(unittest.TestCase):

    def test_d_min_above_d_max_is_a_warning(self):
        tune = dump.parse("profile 0\nset d_roll = 30\nset d_min_roll = 40")
        finding = find(review.review(tune), "D min")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.WARNING)

    def test_the_normal_ordering_is_quiet(self):
        tune = dump.parse("profile 0\nset d_roll = 40\nset d_min_roll = 30")
        self.assertIsNone(find(review.review(tune), "D min"))

    def test_a_high_dterm_lowpass_is_noted(self):
        tune = dump.parse("profile 0\nset dterm_lpf1_static_hz = 300")
        self.assertIsNotNone(find(review.review(tune), "D term lowpass"))

    def test_each_profile_is_checked(self):
        tune = dump.parse("profile 0\nset d_roll = 40\nset d_min_roll = 30\n"
                          "profile 1\nset d_roll = 30\nset d_min_roll = 45\n")
        finding = find(review.review(tune), "D min")
        self.assertIsNotNone(finding)
        self.assertIn("profile 1", finding.detail)


class TestFailsafe(unittest.TestCase):

    def test_drop_is_noted_not_condemned(self):
        tune = dump.parse("set failsafe_procedure = DROP")
        finding = find(review.review(tune), "failsafe")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.NOTE)

    def test_other_procedures_are_quiet(self):
        tune = dump.parse("set failsafe_procedure = GPS_RESCUE")
        self.assertIsNone(find(review.review(tune), "failsafe"))


class TestBlackbox(unittest.TestCase):

    def test_logging_switched_off_is_noted(self):
        tune = dump.parse("set blackbox_device = NONE")
        finding = find(review.review(tune), "logging is switched off")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.NOTE)

    def test_a_configured_device_is_quiet(self):
        tune = dump.parse("set blackbox_device = SDCARD")
        self.assertIsNone(find(review.review(tune), "logging is switched off"))

    def test_log_rate_is_derived_from_the_divider(self):
        # blackbox_sample_rate is an exponent: 0 every iteration, 1 every
        # second, 2 every fourth.
        tune = dump.parse("set pid_process_denom = 1\nset blackbox_sample_rate = 0")
        self.assertAlmostEqual(review.logged_rate_hz(tune), 8000.0)

        tune = dump.parse("set pid_process_denom = 1\nset blackbox_sample_rate = 2")
        self.assertAlmostEqual(review.logged_rate_hz(tune), 2000.0)

    def test_loop_divider_lowers_the_rate_too(self):
        tune = dump.parse("set pid_process_denom = 2\nset blackbox_sample_rate = 1")
        self.assertAlmostEqual(review.logged_rate_hz(tune), 2000.0)

    def test_rate_is_unknown_without_the_setting(self):
        self.assertIsNone(review.logged_rate_hz(dump.parse("")))

    def test_a_log_too_slow_for_the_noise_is_a_warning(self):
        # 500 Hz cannot represent a 582 Hz peak at all.
        tune = dump.parse("set blackbox_device = SDCARD\n"
                          "set pid_process_denom = 1\n"
                          "set blackbox_sample_rate = 4")
        frame = Airframe(5, 4, 2600)
        finding = find(review.review(tune, frame), "too low")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.WARNING)

    def test_a_fast_enough_log_is_quiet(self):
        tune = dump.parse("set blackbox_device = SDCARD\n"
                          "set pid_process_denom = 1\n"
                          "set blackbox_sample_rate = 0")
        frame = Airframe(5, 4, 2600)
        findings = review.review(tune, frame)
        self.assertIsNone(find(findings, "too low"))
        self.assertIsNone(find(findings, "harmonics"))

    def test_a_rate_covering_only_the_fundamental_is_noted(self):
        tune = dump.parse("set blackbox_device = SDCARD\n"
                          "set pid_process_denom = 1\n"
                          "set blackbox_sample_rate = 2")
        frame = Airframe(5, 4, 2600)
        finding = find(review.review(tune, frame), "not its harmonics")
        self.assertIsNotNone(finding)
        self.assertEqual(finding.severity, review.NOTE)

    def test_rate_checks_need_an_airframe(self):
        tune = dump.parse("set blackbox_device = SDCARD\n"
                          "set blackbox_sample_rate = 4")
        self.assertIsNone(find(review.review(tune), "too low"))

    def test_a_disabled_device_short_circuits_the_rate_checks(self):
        # No point complaining about the rate of a log that is not happening.
        tune = dump.parse("set blackbox_device = NONE\n"
                          "set blackbox_sample_rate = 4")
        self.assertIsNone(find(review.review(tune, Airframe(5, 4, 2600)), "too low"))


class TestReportShape(unittest.TestCase):

    def test_an_empty_tune_produces_nothing(self):
        self.assertEqual(review.review(dump.Tune()), [])

    def test_a_clean_tune_says_so(self):
        report = review.format_report([], dump.Tune())
        self.assertIn("No problems found", report)

    def test_errors_are_listed_before_notes(self):
        findings = review.review(dump.parse_file(EXAMPLE))
        severities = [f.severity for f in findings]
        self.assertEqual(severities, sorted(
            severities, key=lambda s: review._SEVERITY_ORDER[s]))

    def test_every_finding_says_what_to_do(self):
        for finding in review.review(dump.parse_file(EXAMPLE)):
            self.assertTrue(finding.detail, msg=finding.title)
            self.assertTrue(finding.fix, msg=finding.title)

    def test_report_includes_the_fixes(self):
        findings = review.review(dump.parse_file(EXAMPLE))
        report = review.format_report(findings, dump.parse_file(EXAMPLE))
        self.assertIn("Fix:", report)
        self.assertIn("ERROR", report)


class TestPlan(unittest.TestCase):

    def test_plan_covers_the_airframe_it_was_built_for(self):
        for name, frame in PRESETS.items():
            generated = plan.filter_plan(frame)
            low = generated["dyn_notch_min_hz"][0]
            high = generated["dyn_notch_max_hz"][0]
            self.assertTrue(frame.covers(low, high), msg=name)

    def test_bidirectional_builds_get_the_rpm_filter(self):
        frame = Airframe(5, 6, 1900, bidirectional_dshot=True)
        generated = plan.filter_plan(frame)
        self.assertEqual(generated["dshot_bidir"][0], "ON")
        self.assertEqual(generated["rpm_filter_harmonics"][0], 3)
        self.assertEqual(generated["motor_poles"][0], frame.motor_poles)

    def test_builds_without_telemetry_do_not_get_it(self):
        generated = plan.filter_plan(Airframe(5, 6, 1900))
        self.assertNotIn("rpm_filter_harmonics", generated)
        self.assertNotIn("dshot_bidir", generated)

    def test_builds_without_telemetry_get_more_dynamic_notches(self):
        with_rpm = plan.filter_plan(Airframe(5, 6, 1900, bidirectional_dshot=True))
        without = plan.filter_plan(Airframe(5, 6, 1900))
        self.assertGreater(without["dyn_notch_count"][0],
                           with_rpm["dyn_notch_count"][0])

    def test_every_setting_carries_a_reason(self):
        for _, (value, reason) in plan.filter_plan(PRESETS["5inch-6s"]).items():
            self.assertIsNotNone(value)
            self.assertGreater(len(reason), 30)

    def test_cli_output_is_valid_and_round_trips(self):
        generated = plan.filter_plan(PRESETS["5inch-6s"])
        parsed = dump.parse(plan.to_cli(generated))
        for name, (value, _) in generated.items():
            self.assertEqual(parsed.get(name), str(value))

    def test_applying_a_plan_leaves_other_settings_alone(self):
        tune = dump.parse_file(EXAMPLE)
        original_p_roll = tune.get("p_roll", "profile 0")

        plan.apply_to(tune, plan.filter_plan(PRESETS["5inch-6s"]))

        self.assertEqual(tune.get("p_roll", "profile 0"), original_p_roll)
        self.assertEqual(tune.get("dshot_bidir"), "ON")

    def test_applying_a_plan_fixes_the_fixtures_errors(self):
        tune = dump.parse_file(EXAMPLE)
        frame = PRESETS["5inch-6s"]
        self.assertTrue([f for f in review.review(tune, frame)
                         if f.severity == review.ERROR])

        plan.apply_to(tune, plan.filter_plan(frame))

        remaining = [f for f in review.review(tune, frame)
                     if f.severity == review.ERROR]
        self.assertEqual(remaining, [], msg=titles(remaining))

    def test_report_mentions_that_it_is_a_starting_point(self):
        frame = PRESETS["5inch-6s"]
        report = plan.format_report(frame, plan.filter_plan(frame))
        self.assertIn("starting configuration", report)
        self.assertIn("not a tune", report)


if __name__ == "__main__":
    unittest.main()
