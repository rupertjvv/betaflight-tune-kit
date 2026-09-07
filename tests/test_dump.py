"""Parsing CLI dumps."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bftune import dump

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
EXAMPLE = os.path.join(FIXTURES, "example_diff.txt")


class TestParsing(unittest.TestCase):

    def setUp(self):
        self.tune = dump.parse_file(EXAMPLE)

    def test_reads_firmware_version_and_target(self):
        self.assertEqual(self.tune.version, "4.4.2")
        self.assertEqual(self.tune.target, "STM32F405")

    def test_reads_the_board(self):
        self.assertEqual(self.tune.board, "MATEKF405")

    def test_master_settings_land_in_master(self):
        self.assertEqual(self.tune.get("dyn_notch_max_hz"), "400")
        self.assertEqual(self.tune.get("dshot_bidir"), "OFF")

    def test_profile_settings_are_kept_separate(self):
        self.assertEqual(self.tune.get("p_roll", "profile 0"), "45")
        # A profile setting must not leak into master.
        self.assertIsNone(self.tune.get("p_roll"))

    def test_rate_profile_settings_are_kept_separate(self):
        self.assertEqual(self.tune.get("roll_rc_rate", "rateprofile 0"), "12")
        self.assertIsNone(self.tune.get("roll_rc_rate", "profile 0"))

    def test_scopes_are_listed_master_first(self):
        self.assertEqual(self.tune.scopes(),
                         [dump.MASTER, "profile 0", "rateprofile 0"])

    def test_profiles_and_rate_profiles_are_distinguished(self):
        self.assertEqual(self.tune.profiles(), ["profile 0"])
        self.assertEqual(self.tune.rate_profiles(), ["rateprofile 0"])

    def test_ints_are_converted_on_request(self):
        self.assertEqual(self.tune.get_int("dyn_notch_max_hz"), 400)

    def test_non_numeric_values_fall_back_rather_than_raising(self):
        # gyro_to_use is FIRST, not a number.
        self.assertEqual(self.tune.get_int("gyro_to_use", default=-1), -1)

    def test_missing_settings_return_the_default(self):
        self.assertIsNone(self.tune.get("no_such_setting"))
        self.assertEqual(self.tune.get_int("no_such_setting", default=7), 7)

    def test_features_track_the_leading_minus(self):
        features = self.tune.features()
        self.assertIn("RX_SERIAL", features)
        self.assertIn("AIRMODE", features)
        self.assertNotIn("RX_PARALLEL_PWM", features)

    def test_non_set_commands_are_preserved(self):
        self.assertIn("serial 0 64 115200 57600 0 115200", self.tune.commands)


class TestParsingEdgeCases(unittest.TestCase):

    def test_empty_input_gives_an_empty_tune(self):
        tune = dump.parse("")
        self.assertEqual(tune.scopes(), [dump.MASTER])
        self.assertEqual(tune.settings[dump.MASTER], {})

    def test_whitespace_around_the_equals_is_tolerated(self):
        tune = dump.parse("set  p_roll   =    45  ")
        self.assertEqual(tune.get("p_roll"), "45")

    def test_values_with_spaces_survive(self):
        tune = dump.parse("set osd_warnings = 1 2 3")
        self.assertEqual(tune.get("osd_warnings"), "1 2 3")

    def test_comments_are_ignored(self):
        tune = dump.parse("# set p_roll = 999\nset p_roll = 45")
        self.assertEqual(tune.get("p_roll"), "45")

    def test_later_values_win(self):
        tune = dump.parse("set p_roll = 40\nset p_roll = 45")
        self.assertEqual(tune.get("p_roll"), "45")

    def test_multiple_profiles_are_kept_apart(self):
        tune = dump.parse(
            "profile 0\nset p_roll = 45\nprofile 1\nset p_roll = 60\n")
        self.assertEqual(tune.get("p_roll", "profile 0"), "45")
        self.assertEqual(tune.get("p_roll", "profile 1"), "60")

    def test_settings_before_any_profile_belong_to_master(self):
        tune = dump.parse("set gyro_lpf1_static_hz = 250\nprofile 0\nset p_roll = 45")
        self.assertEqual(tune.get("gyro_lpf1_static_hz"), "250")

    def test_an_unknown_setting_name_is_kept(self):
        # Betaflight adds parameters every release; the parser must not need
        # to know them in advance.
        tune = dump.parse("set some_future_parameter = 12")
        self.assertEqual(tune.get("some_future_parameter"), "12")

    def test_empty_profile_still_appears(self):
        tune = dump.parse("profile 2\n")
        self.assertIn("profile 2", tune.scopes())

    def test_profiles_sort_numerically_not_lexically(self):
        text = "".join("profile %d\nset p_roll = %d\n" % (i, i)
                       for i in (0, 2, 10, 1))
        tune = dump.parse(text)
        self.assertEqual(tune.profiles(),
                         ["profile 0", "profile 1", "profile 2", "profile 10"])


class TestRoundTrip(unittest.TestCase):

    def test_values_survive_a_round_trip(self):
        original = dump.parse_file(EXAMPLE)
        reparsed = dump.parse(original.to_cli())

        for scope, name in original.names():
            self.assertEqual(reparsed.get(name, scope),
                             original.get(name, scope),
                             msg="%s %s" % (scope, name))

    def test_scopes_survive_a_round_trip(self):
        original = dump.parse_file(EXAMPLE)
        reparsed = dump.parse(original.to_cli())
        self.assertEqual(reparsed.scopes(), original.scopes())

    def test_output_ends_with_save(self):
        tune = dump.parse_file(EXAMPLE)
        self.assertEqual(tune.to_cli().strip().splitlines()[-1], "save")

    def test_profile_settings_are_emitted_behind_their_selector(self):
        tune = dump.parse_file(EXAMPLE)
        lines = tune.to_cli().splitlines()
        selector = lines.index("profile 0")
        p_roll = next(i for i, l in enumerate(lines) if l.startswith("set p_roll"))
        self.assertGreater(p_roll, selector)

    def test_set_writes_into_the_named_scope(self):
        tune = dump.parse_file(EXAMPLE)
        tune.set("p_roll", 60, "profile 0")
        self.assertEqual(tune.get("p_roll", "profile 0"), "60")
        self.assertIsNone(tune.get("p_roll"))

    def test_set_accepts_numbers(self):
        tune = dump.Tune()
        tune.set("dyn_notch_max_hz", 700)
        self.assertEqual(tune.get("dyn_notch_max_hz"), "700")


if __name__ == "__main__":
    unittest.main()
