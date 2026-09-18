"""Working out motor speed and the noise frequencies that follow from it."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bftune import airframe
from bftune.airframe import Airframe


class TestValidation(unittest.TestCase):

    def test_rejects_impossible_geometry(self):
        for kwargs in ({"prop_inches": 0}, {"prop_inches": -5},
                       {"cells": 0}, {"kv": 0}, {"kv": -100}):
            base = {"prop_inches": 5, "cells": 6, "kv": 1900}
            base.update(kwargs)
            with self.assertRaises(ValueError, msg=str(kwargs)):
                Airframe(**base)

    def test_rejects_an_odd_pole_count(self):
        # Poles come in pairs; an odd count cannot be a real motor.
        with self.assertRaises(ValueError):
            Airframe(5, 6, 1900, motor_poles=13)

    def test_rejects_load_factors_out_of_order(self):
        with self.assertRaises(ValueError):
            Airframe(5, 6, 1900, hover_load=0.9, full_load=0.5)

    def test_rejects_a_load_factor_above_one(self):
        # A propped motor cannot exceed its no-load speed.
        with self.assertRaises(ValueError):
            Airframe(5, 6, 1900, hover_load=0.5, full_load=1.4)


class TestMotorSpeed(unittest.TestCase):

    def setUp(self):
        self.frame = Airframe(5, 6, 1900)

    def test_no_load_rpm_is_kv_times_full_voltage(self):
        self.assertAlmostEqual(self.frame.no_load_rpm, 1900 * 6 * 4.2)

    def test_loaded_voltage_is_below_full(self):
        self.assertLess(self.frame.volts_loaded, self.frame.volts_full)

    def test_hover_is_slower_than_full_throttle(self):
        self.assertLess(self.frame.hover_rpm, self.frame.full_rpm)

    def test_in_flight_rpm_never_reaches_no_load(self):
        self.assertLess(self.frame.full_rpm, self.frame.no_load_rpm)

    def test_frequency_is_rpm_over_sixty(self):
        self.assertAlmostEqual(self.frame.hover_hz, self.frame.hover_rpm / 60.0)
        self.assertAlmostEqual(self.frame.full_hz, self.frame.full_rpm / 60.0)

    def test_a_5inch_6s_lands_in_the_expected_band(self):
        # Sanity check against what a 5" 6S actually shows in a log: a couple
        # of hundred Hz hovering, into the high hundreds wide open.
        self.assertTrue(150 < self.frame.hover_hz < 350,
                        msg="%.0f Hz" % self.frame.hover_hz)
        self.assertTrue(450 < self.frame.full_hz < 750,
                        msg="%.0f Hz" % self.frame.full_hz)

    def test_higher_kv_spins_faster(self):
        self.assertGreater(Airframe(5, 6, 2400).full_hz, self.frame.full_hz)

    def test_more_cells_spin_faster_at_the_same_kv(self):
        self.assertGreater(Airframe(5, 6, 1900).full_hz,
                           Airframe(5, 4, 1900).full_hz)

    def test_load_factors_scale_the_result(self):
        lightly_loaded = Airframe(5, 6, 1900, hover_load=0.5, full_load=0.9)
        self.assertGreater(lightly_loaded.hover_hz, self.frame.hover_hz)


class TestThrustToWeight(unittest.TestCase):

    def test_the_default_hover_load_matches_a_typical_ratio(self):
        # The constant is meant to be the square law evaluated at an ordinary
        # 5 inch build, not a free-floating guess. If someone changes one
        # without the other, this catches it.
        derived = airframe.hover_load_for_twr(airframe.TYPICAL_TWR)
        self.assertAlmostEqual(derived, airframe.HOVER_LOAD, delta=0.02)

    def test_a_punchier_quad_hovers_lower(self):
        self.assertLess(airframe.hover_load_for_twr(9.0),
                        airframe.hover_load_for_twr(3.0))

    def test_the_square_law_holds(self):
        # Quadrupling thrust-to-weight should halve the hover speed.
        self.assertAlmostEqual(airframe.hover_load_for_twr(4.0) /
                               airframe.hover_load_for_twr(16.0), 2.0, places=6)

    def test_a_quad_that_cannot_lift_itself_is_rejected(self):
        for twr in (1.0, 0.5, 0.0, -2.0):
            with self.assertRaises(ValueError, msg=str(twr)):
                airframe.hover_load_for_twr(twr)

    def test_airframe_accepts_a_ratio_instead_of_a_load(self):
        frame = Airframe(5, 4, 2600, thrust_to_weight=9.0)
        self.assertAlmostEqual(frame.hover_load,
                               airframe.hover_load_for_twr(9.0))
        self.assertEqual(frame.thrust_to_weight, 9.0)

    def test_a_light_quad_puts_its_hover_noise_lower(self):
        heavy = Airframe(5, 4, 2600, thrust_to_weight=3.0)
        light = Airframe(5, 4, 2600, thrust_to_weight=9.0)
        self.assertLess(light.hover_hz, heavy.hover_hz)
        # And far enough apart to matter for where the notch floor goes.
        self.assertGreater(heavy.hover_hz - light.hover_hz, 50)

    def test_notch_floor_follows_the_ratio_down(self):
        heavy = Airframe(5, 4, 2600, thrust_to_weight=3.0).dyn_notch_range()[0]
        light = Airframe(5, 4, 2600, thrust_to_weight=9.0).dyn_notch_range()[0]
        self.assertLess(light, heavy)

    def test_the_derived_range_still_covers_its_own_airframe(self):
        for twr in (2.5, 4.0, 6.0, 9.0, 14.0):
            frame = Airframe(5, 4, 2600, thrust_to_weight=twr)
            self.assertTrue(frame.covers(*frame.dyn_notch_range()),
                            msg="TWR %s" % twr)

    def test_giving_both_is_rejected(self):
        with self.assertRaises(ValueError):
            Airframe(5, 4, 2600, hover_load=0.3, thrust_to_weight=6.0)

    def test_frames_without_a_ratio_report_none(self):
        self.assertIsNone(Airframe(5, 4, 2600).thrust_to_weight)

    def test_full_load_is_respected_when_deriving(self):
        frame = Airframe(5, 4, 2600, thrust_to_weight=4.0, full_load=0.6)
        self.assertAlmostEqual(frame.hover_load, 0.6 / 2.0)


class TestHarmonics(unittest.TestCase):

    def setUp(self):
        self.frame = Airframe(5, 6, 1900)

    def test_harmonics_are_multiples_of_the_fundamental(self):
        harmonics = self.frame.harmonics(3)
        self.assertAlmostEqual(harmonics[0], self.frame.full_hz)
        self.assertAlmostEqual(harmonics[1], self.frame.full_hz * 2)
        self.assertAlmostEqual(harmonics[2], self.frame.full_hz * 3)

    def test_count_is_respected(self):
        self.assertEqual(len(self.frame.harmonics(5)), 5)

    def test_at_least_one_harmonic_is_required(self):
        with self.assertRaises(ValueError):
            self.frame.harmonics(0)


class TestElectricalFrequency(unittest.TestCase):

    def test_erpm_uses_pole_pairs(self):
        frame = Airframe(5, 6, 1900, motor_poles=14)
        # 14 poles is 7 pole pairs, so electrical frequency is 7x mechanical.
        self.assertAlmostEqual(frame.erpm_hz(6000), (6000 / 60.0) * 7)

    def test_pole_count_changes_the_conversion(self):
        twelve = Airframe(5, 6, 1900, motor_poles=12)
        fourteen = Airframe(5, 6, 1900, motor_poles=14)
        self.assertLess(twelve.erpm_hz(6000), fourteen.erpm_hz(6000))


class TestNotchRange(unittest.TestCase):

    def test_range_brackets_the_flight_envelope(self):
        for frame in airframe.PRESETS.values():
            low, high = frame.dyn_notch_range()
            self.assertLess(low, frame.hover_hz, msg=frame.name)
            self.assertGreater(high, frame.full_hz, msg=frame.name)

    def test_covers_agrees_with_the_generated_range(self):
        for frame in airframe.PRESETS.values():
            self.assertTrue(frame.covers(*frame.dyn_notch_range()),
                            msg=frame.name)

    def test_a_too_narrow_range_is_not_covered(self):
        frame = Airframe(5, 6, 1900)
        self.assertFalse(frame.covers(100, 300))

    def test_range_is_clamped_to_what_betaflight_accepts(self):
        # A tiny very high kV motor would otherwise ask for more than the
        # firmware allows.
        frame = Airframe(1.6, 4, 12000)
        low, high = frame.dyn_notch_range()
        self.assertGreaterEqual(low, airframe.DYN_NOTCH_MIN_LIMIT)
        self.assertLessEqual(high, airframe.DYN_NOTCH_MAX_LIMIT)

    def test_range_is_never_inverted_even_when_clamped(self):
        for frame in (Airframe(1.6, 4, 12000), Airframe(15, 6, 300)):
            low, high = frame.dyn_notch_range()
            self.assertLess(low, high, msg=frame.describe())

    def test_bounds_are_whole_numbers(self):
        # They go straight into a CLI command.
        low, high = Airframe(5, 6, 1900).dyn_notch_range()
        self.assertIsInstance(low, int)
        self.assertIsInstance(high, int)

    def test_faster_setups_get_a_higher_ceiling(self):
        slow = Airframe(7, 6, 1350).dyn_notch_range()
        fast = Airframe(3, 4, 3800).dyn_notch_range()
        self.assertGreater(fast[1], slow[1])


class TestAliasing(unittest.TestCase):

    def test_ordinary_builds_are_clear_of_the_sampling_limit(self):
        for name in ("5inch-6s", "7inch-6s", "5inch-4s"):
            self.assertFalse(airframe.PRESETS[name].aliasing_risk, msg=name)

    def test_an_extreme_setup_is_flagged(self):
        self.assertTrue(Airframe(1.6, 4, 12000).aliasing_risk)


class TestPresets(unittest.TestCase):

    def test_every_preset_is_usable(self):
        for name, frame in airframe.PRESETS.items():
            self.assertGreater(frame.full_hz, frame.hover_hz, msg=name)
            self.assertIn("summary", dir(frame))
            self.assertTrue(frame.summary()["name"], msg=name)

    def test_bigger_props_turn_slower(self):
        self.assertLess(airframe.PRESETS["7inch-6s"].full_hz,
                        airframe.PRESETS["3inch-4s"].full_hz)

    def test_summary_reports_the_notch_range_it_recommends(self):
        frame = airframe.PRESETS["5inch-6s"]
        summary = frame.summary()
        self.assertEqual((summary["dyn_notch_min_hz"], summary["dyn_notch_max_hz"]),
                         frame.dyn_notch_range())


if __name__ == "__main__":
    unittest.main()
