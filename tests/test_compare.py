"""Comparing two tunes setting by setting."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bftune import categories, compare, dump

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
BEFORE = os.path.join(FIXTURES, "example_diff.txt")
AFTER = os.path.join(FIXTURES, "example_diff_after.txt")


class TestCompare(unittest.TestCase):

    def setUp(self):
        self.before = dump.parse_file(BEFORE)
        self.after = dump.parse_file(AFTER)
        self.changes = compare.compare(self.before, self.after)

    def _find(self, name, scope=dump.MASTER):
        for change in self.changes:
            if change.name == name and change.scope == scope:
                return change
        return None

    def test_identical_tunes_have_no_differences(self):
        self.assertEqual(compare.compare(self.before, self.before), [])

    def test_a_changed_master_setting_is_found(self):
        change = self._find("dyn_notch_max_hz")
        self.assertIsNotNone(change)
        self.assertEqual(change.kind, compare.CHANGED)
        self.assertEqual((change.before, change.after), ("400", "700"))

    def test_a_changed_profile_setting_is_found_in_its_own_scope(self):
        change = self._find("p_roll", "profile 0")
        self.assertIsNotNone(change)
        self.assertEqual((change.before, change.after), ("45", "52"))

    def test_a_new_setting_is_reported_as_added(self):
        change = self._find("simplified_gyro_filter_multiplier")
        self.assertIsNotNone(change)
        self.assertEqual(change.kind, compare.ADDED)
        self.assertEqual(change.after, "90")

    def test_a_dropped_setting_is_reported_as_removed(self):
        before = dump.parse("set p_roll = 45\nset d_roll = 40")
        after = dump.parse("set p_roll = 45")
        changes = compare.compare(before, after)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].kind, compare.REMOVED)
        self.assertEqual(changes[0].before, "40")

    def test_unchanged_settings_are_not_reported(self):
        self.assertIsNone(self._find("gyro_lpf1_static_hz"))
        self.assertIsNone(self._find("i_roll", "profile 0"))

    def test_changes_carry_their_category(self):
        self.assertEqual(self._find("p_roll", "profile 0").category,
                         categories.PID)
        self.assertEqual(self._find("dyn_notch_max_hz").category,
                         categories.FILTER)


class TestChangeArithmetic(unittest.TestCase):

    def test_numeric_delta(self):
        change = compare.Change(compare.CHANGED, "master", "x", "40", "50")
        self.assertAlmostEqual(change.delta(), 10.0)
        self.assertAlmostEqual(change.percent(), 25.0)

    def test_negative_delta(self):
        change = compare.Change(compare.CHANGED, "master", "x", "50", "40")
        self.assertAlmostEqual(change.delta(), -10.0)

    def test_non_numeric_values_do_not_raise(self):
        change = compare.Change(compare.CHANGED, "master", "gyro_to_use",
                                "FIRST", "BOTH")
        self.assertIsNone(change.delta())
        self.assertIsNone(change.percent())

    def test_percent_change_from_zero_is_undefined(self):
        change = compare.Change(compare.CHANGED, "master", "x", "0", "40")
        self.assertAlmostEqual(change.delta(), 40.0)
        self.assertIsNone(change.percent())

    def test_added_settings_have_no_delta(self):
        change = compare.Change(compare.ADDED, "master", "x", after="40")
        self.assertIsNone(change.delta())


class TestReport(unittest.TestCase):

    def test_identical_tunes_say_so(self):
        tune = dump.parse_file(BEFORE)
        report = compare.format_report(compare.compare(tune, tune), tune, tune)
        self.assertIn("No differences", report)

    def test_report_groups_by_category(self):
        before = dump.parse_file(BEFORE)
        after = dump.parse_file(AFTER)
        report = compare.format_report(compare.compare(before, after),
                                       before, after)
        self.assertIn("Filters", report)
        self.assertIn("PID", report)
        self.assertIn("dyn_notch_max_hz: 400 -> 700", report)

    def test_report_labels_profile_scoped_changes(self):
        before = dump.parse_file(BEFORE)
        after = dump.parse_file(AFTER)
        report = compare.format_report(compare.compare(before, after),
                                       before, after)
        self.assertIn("[profile 0]", report)

    def test_report_warns_when_firmware_versions_differ(self):
        before = dump.parse("# Betaflight / STM32F405 (S405) 4.4.2 Jun  5 2023\n"
                            "set p_roll = 45")
        after = dump.parse("# Betaflight / STM32F405 (S405) 4.5.0 Jan  1 2024\n"
                           "set p_roll = 50")
        report = compare.format_report(compare.compare(before, after),
                                       before, after)
        self.assertIn("Firmware differs", report)

    def test_report_shows_percentage_for_meaningful_moves(self):
        before = dump.parse("set p_roll = 40")
        after = dump.parse("set p_roll = 50")
        report = compare.format_report(compare.compare(before, after))
        self.assertIn("+25%", report)


if __name__ == "__main__":
    unittest.main()
