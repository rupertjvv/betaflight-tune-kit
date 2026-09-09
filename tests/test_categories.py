"""Classifying setting names into the groups a pilot thinks in."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bftune import categories


class TestCategorise(unittest.TestCase):

    def test_pid_loop_terms(self):
        for name in ("p_roll", "i_pitch", "d_yaw", "d_min_roll",
                     "anti_gravity_gain", "feedforward_transition"):
            self.assertEqual(categories.categorise(name), categories.PID, name)

    def test_filters(self):
        for name in ("gyro_lpf1_static_hz", "dterm_notch_hz", "dyn_notch_max_hz",
                     "rpm_filter_harmonics", "dshot_bidir", "simplified_gyro_filter"):
            self.assertEqual(categories.categorise(name), categories.FILTER, name)

    def test_rates_and_rc(self):
        self.assertEqual(categories.categorise("roll_rc_rate"), categories.RATES)
        self.assertEqual(categories.categorise("rc_smoothing"), categories.RC)

    def test_unknown_names_land_in_other_rather_than_being_dropped(self):
        self.assertEqual(categories.categorise("some_future_setting"),
                         categories.OTHER)

    def test_first_matching_rule_wins(self):
        # d_min_roll is a PID term, not a generic "motor" despite the prefix soup.
        self.assertEqual(categories.categorise("d_min_roll"), categories.PID)


class TestGrouping(unittest.TestCase):

    def test_group_sorts_names_within_each_category(self):
        grouped = categories.group(["p_roll", "d_roll", "dyn_notch_max_hz"])
        self.assertEqual(grouped[categories.PID], ["d_roll", "p_roll"])
        self.assertEqual(grouped[categories.FILTER], ["dyn_notch_max_hz"])

    def test_in_order_skips_empty_categories_and_follows_display_order(self):
        grouped = categories.group(["dyn_notch_max_hz", "p_roll"])
        seen = [category for category, _title, _names in categories.in_order(grouped)]
        self.assertEqual(seen, [categories.PID, categories.FILTER])


if __name__ == "__main__":
    unittest.main()
