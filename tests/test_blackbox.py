"""
Blackbox log analysis.

The logs here are synthesised with known contents: a gyro trace built from a
tone at a chosen frequency, so the spectrum can be checked against the answer
rather than against a screenshot of another tool.
"""

import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bftune import blackbox, dump
from bftune.airframe import PRESETS

HAS_NUMPY = blackbox.np is not None
needs_numpy = unittest.skipUnless(HAS_NUMPY, "numpy is not installed")


def write_log(path, noise_hz=250.0, noise_amp=8.0, rate_hz=2000.0,
              seconds=1.0, setpoint_amp=0.0, motor_base=1200.0,
              motor_amp=200.0):
    """A synthetic blackbox_decode CSV with a known noise frequency."""
    rows = int(rate_hz * seconds)
    with open(path, "w") as handle:
        handle.write("loopIteration,time (us),axisP[0],gyroADC[0],setpoint[0],"
                     "motor[0],motor[1],motor[2],motor[3]\n")
        for i in range(rows):
            t = i / rate_hz
            noise = noise_amp * math.sin(2.0 * math.pi * noise_hz * t)
            command = setpoint_amp * math.sin(2.0 * math.pi * 2.0 * t)
            # The craft only reaches 95% of the command, plus the noise.
            gyro = command * 0.95 + noise
            motor = motor_base + motor_amp * abs(math.sin(2.0 * math.pi * 0.5 * t))
            handle.write("%d,%d,0,%.4f,%.4f,%.1f,%.1f,%.1f,%.1f\n"
                         % (i, int(t * 1e6), gyro, command,
                            motor, motor, motor, motor))
    return path


class LogFixture(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "log.csv")

    def tearDown(self):
        self.dir.cleanup()


class TestLoading(LogFixture):

    def test_reads_columns_and_rows(self):
        write_log(self.path, seconds=0.5, rate_hz=1000.0)
        log = blackbox.load(self.path)
        self.assertEqual(log.rows, 500)
        self.assertIn("gyroADC[0]", log.columns)

    def test_recovers_the_logging_rate(self):
        write_log(self.path, rate_hz=2000.0)
        log = blackbox.load(self.path)
        self.assertAlmostEqual(log.sample_rate_hz, 2000.0, delta=1.0)

    def test_recovers_the_duration(self):
        write_log(self.path, seconds=2.0, rate_hz=1000.0)
        log = blackbox.load(self.path)
        self.assertAlmostEqual(log.duration_s, 2.0, delta=0.01)

    def test_dropped_iterations_do_not_skew_the_rate(self):
        # Logs routinely lose rows when the write cannot keep up. The median
        # gap has to survive that; a mean would not.
        with open(self.path, "w") as handle:
            handle.write("loopIteration,time (us),gyroADC[0]\n")
            t = 0
            for i in range(500):
                handle.write("%d,%d,1.0\n" % (i, t))
                t += 500 if i != 250 else 50000  # one long stall
        log = blackbox.load(self.path)
        self.assertAlmostEqual(log.sample_rate_hz, 2000.0, delta=1.0)

    def test_axis_lookup_by_name(self):
        write_log(self.path)
        log = blackbox.load(self.path)
        self.assertIsNotNone(log.axis_field("gyroADC", "roll"))
        self.assertIsNone(log.axis_field("gyroADC", "yaw"))

    def test_ragged_rows_are_skipped_rather_than_crashing(self):
        with open(self.path, "w") as handle:
            handle.write("loopIteration,time (us),gyroADC[0]\n")
            handle.write("0,0,1.0\n")
            handle.write("1,500\n")          # short row
            handle.write("2,1000,3.0\n")
        log = blackbox.load(self.path)
        self.assertEqual(log.rows, 2)

    def test_a_file_with_no_table_is_rejected(self):
        with open(self.path, "w") as handle:
            handle.write("Product,Blackbox\nData version,2\n")
        with self.assertRaises(ValueError):
            blackbox.load(self.path)


@needs_numpy
class TestSpectrum(LogFixture):

    def test_finds_the_frequency_that_was_put_in(self):
        write_log(self.path, noise_hz=250.0, rate_hz=2000.0, seconds=2.0)
        log = blackbox.load(self.path)
        report = blackbox.noise_report(log)
        top_hz = report["peaks"][0][0]
        self.assertAlmostEqual(top_hz, 250.0, delta=5.0)

    def test_finds_a_different_frequency_too(self):
        write_log(self.path, noise_hz=420.0, rate_hz=2000.0, seconds=2.0)
        log = blackbox.load(self.path)
        self.assertAlmostEqual(blackbox.noise_report(log)["peaks"][0][0],
                               420.0, delta=5.0)

    def test_amplitude_is_recovered_roughly(self):
        write_log(self.path, noise_hz=250.0, noise_amp=10.0,
                  rate_hz=2000.0, seconds=2.0)
        log = blackbox.load(self.path)
        peak_amp = blackbox.noise_report(log)["peaks"][0][1]
        # The Hann window costs about half the amplitude, so allow for it.
        self.assertGreater(peak_amp, 3.0)

    def test_louder_noise_reports_a_higher_rms(self):
        write_log(self.path, noise_amp=4.0)
        quiet = blackbox.noise_report(blackbox.load(self.path))["rms"]
        write_log(self.path, noise_amp=16.0)
        loud = blackbox.noise_report(blackbox.load(self.path))["rms"]
        self.assertGreater(loud, quiet * 2)

    def test_stick_input_does_not_masquerade_as_noise(self):
        # A 2 Hz stick sweep is the pilot flying, not something to filter.
        write_log(self.path, noise_hz=300.0, noise_amp=5.0,
                  setpoint_amp=200.0, rate_hz=2000.0, seconds=2.0)
        log = blackbox.load(self.path)
        peaks = blackbox.noise_report(log)["peaks"]
        self.assertTrue(all(f > 30.0 for f, _ in peaks), msg=str(peaks))
        self.assertAlmostEqual(peaks[0][0], 300.0, delta=10.0)

    def test_spectrum_stops_at_the_requested_ceiling(self):
        write_log(self.path, rate_hz=2000.0, seconds=1.0)
        log = blackbox.load(self.path)
        freqs, _ = blackbox.spectrum(log.field("gyroADC[0]"),
                                     log.sample_rate_hz, max_hz=400.0)
        self.assertLessEqual(float(freqs[-1]), 400.0)

    def test_too_few_samples_is_rejected(self):
        with self.assertRaises(ValueError):
            blackbox.spectrum([1.0, 2.0, 3.0], 1000.0)

    def test_a_bad_sample_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            blackbox.spectrum([1.0] * 64, 0)


@needs_numpy
class TestTracking(LogFixture):

    def test_perfect_tracking_reports_almost_no_error(self):
        write_log(self.path, noise_amp=0.0, setpoint_amp=0.0)
        log = blackbox.load(self.path)
        self.assertLess(blackbox.tracking_report(log)["mean_abs_error"], 0.01)

    def test_a_craft_that_falls_short_reports_error(self):
        write_log(self.path, noise_amp=0.0, setpoint_amp=400.0)
        log = blackbox.load(self.path)
        report = blackbox.tracking_report(log)
        # The synthetic craft reaches 95% of what it is asked for.
        self.assertGreater(report["mean_abs_error"], 1.0)
        self.assertAlmostEqual(report["max_setpoint"], 400.0, delta=1.0)

    def test_error_while_moving_is_reported_separately(self):
        write_log(self.path, noise_amp=0.0, setpoint_amp=400.0)
        log = blackbox.load(self.path)
        report = blackbox.tracking_report(log)
        self.assertIsNotNone(report["moving_mean_abs_error"])
        self.assertGreater(report["moving_mean_abs_error"],
                           report["mean_abs_error"])

    def test_missing_setpoint_column_is_rejected(self):
        with open(self.path, "w") as handle:
            handle.write("loopIteration,time (us),gyroADC[0]\n")
            for i in range(100):
                handle.write("%d,%d,1.0\n" % (i, i * 500))
        log = blackbox.load(self.path)
        with self.assertRaises(ValueError):
            blackbox.tracking_report(log)


@needs_numpy
class TestSaturation(LogFixture):

    def test_a_flight_with_headroom_reports_no_saturation(self):
        write_log(self.path, motor_base=1000.0, motor_amp=200.0)
        log = blackbox.load(self.path)
        report = blackbox.saturation_report(log)
        self.assertIsNotNone(report)
        self.assertEqual(report["motors"], 4)
        self.assertEqual(report["any_motor_pct"], 0.0)

    def test_the_busiest_moment_of_a_flight_is_not_saturation(self):
        # DShot motors peaking at 1400 still had a third of their range left.
        write_log(self.path, motor_base=200.0, motor_amp=1200.0)
        report = blackbox.saturation_report(blackbox.load(self.path))
        self.assertEqual(report["any_motor_pct"], 0.0)

    def test_motors_at_the_top_of_the_dshot_range_are_saturated(self):
        write_log(self.path, motor_base=1500.0, motor_amp=547.0)
        report = blackbox.saturation_report(blackbox.load(self.path))
        self.assertGreater(report["any_motor_pct"], 10.0)

    def test_motors_at_the_top_of_the_pwm_range_are_saturated(self):
        write_log(self.path, motor_base=1000.0, motor_amp=1000.0)
        report = blackbox.saturation_report(blackbox.load(self.path))
        self.assertEqual(report["range"], (1000.0, 2000.0))
        self.assertGreater(report["any_motor_pct"], 10.0)

    def test_all_four_motors_are_found(self):
        write_log(self.path)
        report = blackbox.saturation_report(blackbox.load(self.path))
        self.assertEqual(len(report["per_motor_pct"]), 4)

    def test_a_log_without_motor_columns_returns_nothing(self):
        with open(self.path, "w") as handle:
            handle.write("loopIteration,time (us),gyroADC[0]\n")
            for i in range(100):
                handle.write("%d,%d,1.0\n" % (i, i * 500))
        self.assertIsNone(blackbox.saturation_report(blackbox.load(self.path)))

    def test_constant_motor_output_is_not_reported_as_saturated(self):
        with open(self.path, "w") as handle:
            handle.write("loopIteration,time (us),gyroADC[0],motor[0]\n")
            for i in range(100):
                handle.write("%d,%d,1.0,1500\n" % (i, i * 500))
        report = blackbox.saturation_report(blackbox.load(self.path))
        self.assertEqual(report["any_motor_pct"], 0.0)


@needs_numpy
class TestReport(LogFixture):

    def test_report_names_the_peak_it_found(self):
        write_log(self.path, noise_hz=250.0, rate_hz=2000.0, seconds=2.0)
        log = blackbox.load(self.path)
        report = blackbox.format_report(log)
        self.assertIn("Gyro noise", report)
        self.assertIn("250 Hz", report)

    def test_report_checks_peaks_against_the_notch_range(self):
        write_log(self.path, noise_hz=800.0, rate_hz=4000.0, seconds=2.0)
        log = blackbox.load(self.path)
        tune = dump.parse("set dyn_notch_min_hz = 100\nset dyn_notch_max_hz = 400")
        report = blackbox.format_report(log, tune=tune)
        self.assertIn("Outside that range", report)

    def test_report_is_quiet_when_the_notches_cover_everything(self):
        write_log(self.path, noise_hz=250.0, rate_hz=2000.0, seconds=2.0)
        log = blackbox.load(self.path)
        tune = dump.parse("set dyn_notch_min_hz = 100\nset dyn_notch_max_hz = 600")
        report = blackbox.format_report(log, tune=tune)
        self.assertIn("falls inside it", report)

    def test_report_identifies_motor_noise_against_the_airframe(self):
        frame = PRESETS["5inch-6s"]
        write_log(self.path, noise_hz=frame.hover_hz, rate_hz=2000.0, seconds=2.0)
        log = blackbox.load(self.path)
        report = blackbox.format_report(log, frame=frame)
        self.assertIn("motor noise", report)

    def test_report_flags_a_peak_outside_the_motor_band(self):
        frame = PRESETS["7inch-6s"]
        write_log(self.path, noise_hz=900.0, rate_hz=4000.0, seconds=2.0)
        log = blackbox.load(self.path)
        report = blackbox.format_report(log, frame=frame)
        self.assertIn("outside it", report)


class TestWithoutNumpy(LogFixture):

    def test_loading_a_log_needs_no_numpy(self):
        # Parsing is stdlib only, so a log can be inspected on a machine
        # without numpy installed even though analysis cannot run.
        write_log(self.path, seconds=0.2, rate_hz=1000.0)
        log = blackbox.load(self.path)
        self.assertEqual(log.rows, 200)
        self.assertIsNotNone(log.sample_rate_hz)


if __name__ == "__main__":
    unittest.main()
