"""
Reading what a flight actually did, from a decoded blackbox log.

Betaflight logs to a binary format. `blackbox_decode`, which ships with
Blackbox Explorer, turns that into CSV, and this reads the CSV:

    blackbox_decode LOG00001.BFL      # produces LOG00001.01.csv

What comes out is one row per loop iteration with the gyro, the setpoint the
PID controller was chasing, the individual P, I and D contributions and the
motor outputs. Three questions can be answered from that which cannot be
answered from a config file.

Where is the noise? An FFT of the gyro trace shows which frequencies are
actually present, so the notch configuration can be checked against reality
instead of against an estimate of motor RPM.

Is the quad following the sticks? Comparing gyro against setpoint gives
tracking error and overshoot. That is what P and D are for.

Is there any authority left? Motor outputs sitting at the top of their
range mean the controller has run out of room, and no amount of PID tuning
fixes a quad that is simply saturating.

numpy is required here, and only here. The rest of the toolkit is stdlib.
"""

import csv

try:
    import numpy as np
except ImportError:  # pragma: no cover - exercised by the CLI, not the tests
    np = None

# The timestamp of each row, in microseconds. blackbox_decode calls it
# "time (us)" and Blackbox Explorer's CSV export calls it "time".
_TIME_FIELDS = ("time (us)", "time")

# Motor outputs are logged in the units of the ESC protocol. DShot runs
# from 48 to 2047, the older PWM protocols from 1000 to 2000.
_DSHOT_RANGE = (48.0, 2047.0)
_PWM_RANGE = (1000.0, 2000.0)

_AXES = ("roll", "pitch", "yaw")


class MissingNumpy(RuntimeError):
    def __init__(self):
        super().__init__(
            "Log analysis needs numpy:\n\n    pip install numpy\n\n"
            "The rest of the toolkit does not.")


class Log:
    """A decoded blackbox CSV."""

    def __init__(self, columns, source=None):
        self.columns = columns
        self.source = source

    @property
    def rows(self):
        for values in self.columns.values():
            return len(values)
        return 0

    def field(self, name):
        return self.columns.get(name)

    def axis_field(self, prefix, axis):
        """
        Look up something like gyroADC[0] by axis name.

        blackbox_decode has changed its column names more than once, and
        different versions emit `gyroADC[0]`, `gyro[0]` or a spaced variant,
        so several spellings are tried before giving up.
        """
        index = _AXES.index(axis)
        for candidate in ("%s[%d]" % (prefix, index),
                          "%s [%d]" % (prefix, index),
                          "%s%d" % (prefix, index)):
            if candidate in self.columns:
                return self.columns[candidate]
        return None

    @property
    def time_s(self):
        for name in _TIME_FIELDS:
            if name in self.columns:
                return [t / 1e6 for t in self.columns[name]]
        return None

    @property
    def sample_rate_hz(self):
        """
        Logging rate, from the median gap between rows.

        The median matters: logs routinely drop iterations when the write
        cannot keep up, and a mean would be dragged off by those gaps.
        """
        times = self.time_s
        if not times or len(times) < 2:
            return None
        gaps = sorted(b - a for a, b in zip(times, times[1:]))
        mid = len(gaps) // 2
        gap = gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2.0
        return 1.0 / gap if gap > 0 else None

    @property
    def duration_s(self):
        times = self.time_s
        return (times[-1] - times[0]) if times and len(times) > 1 else None


def load(path):
    """Read a blackbox_decode CSV into a Log."""
    columns = {}
    with open(path, newline="") as handle:
        reader = csv.reader(handle)
        headers = None
        for row in reader:
            if not row:
                continue
            # Blackbox Explorer's CSV export puts a block of "key, value"
            # header lines before the real table. blackbox_decode does not.
            if headers is None:
                if len(row) < 3:
                    continue
                headers = [cell.strip() for cell in row]
                columns = {name: [] for name in headers}
                continue

            if len(row) != len(headers):
                continue
            for name, cell in zip(headers, row):
                try:
                    columns[name].append(float(cell))
                except ValueError:
                    pass

    if not headers:
        raise ValueError("No table found in %s. Is it a blackbox_decode CSV?" % path)

    # Drop columns that were entirely non-numeric, such as flight mode flags.
    columns = {name: values for name, values in columns.items() if values}
    return Log(columns, source=path)


def spectrum(samples, sample_rate_hz, max_hz=1000.0):
    """
    Amplitude spectrum of a signal, up to max_hz.

    A Hann window is applied first. Without it the abrupt ends of the sample
    leak energy across every bin, which on a gyro trace looks like broadband
    noise that is not really there.
    """
    if np is None:
        raise MissingNumpy()
    if sample_rate_hz is None or sample_rate_hz <= 0:
        raise ValueError("need a positive sample rate")

    data = np.asarray(samples, dtype=float)
    if data.size < 16:
        raise ValueError("not enough samples for a spectrum")

    data = data - data.mean()
    windowed = data * np.hanning(data.size)

    magnitude = np.abs(np.fft.rfft(windowed)) * (2.0 / data.size)
    freqs = np.fft.rfftfreq(data.size, d=1.0 / sample_rate_hz)

    keep = freqs <= max_hz
    return freqs[keep], magnitude[keep]


def peaks(freqs, magnitude, count=5, min_hz=30.0, floor_ratio=0.05):
    """
    The strongest local maxima in a spectrum.

    Everything below min_hz is skipped: that end holds the quad's own
    movement and the pilot's stick inputs, which are signal rather than noise
    and would otherwise dominate every result.

    Peaks below floor_ratio of the strongest one are dropped as well. Every
    spectrum has local maxima all the way along it, most of them rounding
    error, and reporting a 0.00 amplitude "peak" next to a real one invites
    someone to go filtering empty spectrum.
    """
    if np is None:
        raise MissingNumpy()

    found = []
    for i in range(1, len(magnitude) - 1):
        if freqs[i] < min_hz:
            continue
        if magnitude[i] >= magnitude[i - 1] and magnitude[i] > magnitude[i + 1]:
            found.append((float(freqs[i]), float(magnitude[i])))

    if not found:
        return []

    found.sort(key=lambda pair: pair[1], reverse=True)
    cutoff = found[0][1] * floor_ratio
    return [pair for pair in found[:count] if pair[1] >= cutoff]


def noise_report(log, axis="roll", max_hz=1000.0):
    """Where the noise on one axis sits."""
    gyro = log.axis_field("gyroADC", axis) or log.axis_field("gyroUnfilt", axis)
    if gyro is None:
        raise ValueError("No gyro column for %s in %s" % (axis, log.source))

    rate = log.sample_rate_hz
    freqs, magnitude = spectrum(gyro, rate, max_hz)

    return {
        "axis": axis,
        "sample_rate_hz": rate,
        "peaks": peaks(freqs, magnitude),
        "rms": float(np.sqrt(np.mean(np.square(np.asarray(gyro) - np.mean(gyro))))),
    }


def tracking_report(log, axis="roll"):
    """
    How closely the quad followed the sticks on one axis.

    Mean absolute error is the headline number. The 95th percentile is there
    too, because a tune can track well on average and still overshoot badly
    on the fast direction changes that are the whole point of looking.
    """
    if np is None:
        raise MissingNumpy()

    gyro = log.axis_field("gyroADC", axis)
    setpoint = log.axis_field("setpoint", axis)
    if gyro is None or setpoint is None:
        raise ValueError("Need both gyro and setpoint columns for %s" % axis)

    length = min(len(gyro), len(setpoint))
    gyro = np.asarray(gyro[:length], dtype=float)
    setpoint = np.asarray(setpoint[:length], dtype=float)

    error = gyro - setpoint
    moving = np.abs(setpoint) > 20.0  # only judge tracking while being flown

    return {
        "axis": axis,
        "mean_abs_error": float(np.mean(np.abs(error))),
        "p95_abs_error": float(np.percentile(np.abs(error), 95)),
        "moving_mean_abs_error": (float(np.mean(np.abs(error[moving])))
                                  if moving.any() else None),
        "max_setpoint": float(np.max(np.abs(setpoint))),
    }


def saturation_report(log, motors=4, ceiling=0.97):
    """
    How often the motor outputs ran out of headroom.

    A motor pinned at its maximum cannot be commanded any harder, so the
    controller has lost authority on that corner regardless of what the PID
    values are. Persistent saturation is a propulsion or weight problem
    wearing a tuning problem's clothes.
    """
    if np is None:
        raise MissingNumpy()

    outputs = []
    for index in range(motors):
        for candidate in ("motor[%d]" % index, "motor %d" % index):
            if candidate in log.columns:
                outputs.append(np.asarray(log.columns[candidate], dtype=float))
                break

    if not outputs:
        return None

    length = min(len(o) for o in outputs)
    stacked = np.vstack([o[:length] for o in outputs])

    # Judge against the protocol's full range, not the range this flight
    # happened to use, or the busiest moment of every flight would read as
    # pinned. A log that never leaves 1000 to 2000 is taken as PWM, since
    # DShot idles well below 1000.
    low, high = _PWM_RANGE
    if stacked.min() < low or stacked.max() > high:
        low, high = _DSHOT_RANGE

    normalised = (stacked - low) / (high - low)
    saturated = normalised >= ceiling

    return {
        "motors": len(outputs),
        "range": (low, high),
        "saturated_pct": float(100.0 * saturated.mean()),
        "per_motor_pct": [float(100.0 * row.mean()) for row in saturated],
        "any_motor_pct": float(100.0 * saturated.any(axis=0).mean()),
    }


def format_report(log, frame=None, tune=None, axis="roll"):
    lines = []
    lines.append(log.source or "log")
    rate = log.sample_rate_hz
    duration = log.duration_s
    if rate:
        lines.append("%d rows, %.1f s, logged at %.0f Hz"
                     % (log.rows, duration or 0, rate))
    lines.append("")

    noise = noise_report(log, axis)
    lines.append("Gyro noise on %s" % axis)
    lines.append("-" * (len("Gyro noise on ") + len(axis)))
    lines.append("  RMS %.1f deg/s" % noise["rms"])
    if noise["peaks"]:
        lines.append("  Strongest frequencies:")
        for freq, amplitude in noise["peaks"]:
            lines.append("    %6.0f Hz   %.2f" % (freq, amplitude))
    else:
        lines.append("  No distinct peaks found.")

    if frame is not None and noise["peaks"]:
        lines.append("")
        lines.extend(_compare_against_frame(noise, frame))

    if tune is not None and noise["peaks"]:
        lines.append("")
        lines.extend(_compare_against_notches(noise, tune))

    try:
        tracking = tracking_report(log, axis)
    except ValueError:
        tracking = None

    if tracking:
        lines.append("")
        lines.append("Setpoint tracking on %s" % axis)
        lines.append("-" * (len("Setpoint tracking on ") + len(axis)))
        lines.append("  mean error   %.1f deg/s" % tracking["mean_abs_error"])
        lines.append("  95th pct     %.1f deg/s" % tracking["p95_abs_error"])
        if tracking["moving_mean_abs_error"] is not None:
            lines.append("  while moving %.1f deg/s"
                         % tracking["moving_mean_abs_error"])
        lines.append("  max commanded %.0f deg/s" % tracking["max_setpoint"])

    saturation = saturation_report(log)
    if saturation:
        lines.append("")
        lines.append("Motor headroom")
        lines.append("--------------")
        lines.append("  %.1f%% of the log had at least one motor at its ceiling"
                     % saturation["any_motor_pct"])
        for index, pct in enumerate(saturation["per_motor_pct"]):
            lines.append("    motor %d  %.1f%%" % (index + 1, pct))
        if saturation["any_motor_pct"] > 10:
            lines.append("")
            lines.append("  Over 10% saturated. The controller is out of "
                         "authority for that")
            lines.append("  part of the flight, which no PID change will "
                         "recover.")

    return "\n".join(lines)


def _compare_against_frame(noise, frame):
    lines = ["Against the airframe estimate"]
    lines.append("-" * len(lines[0]))
    lines.append("  Motors should run %.0f Hz hovering, %.0f Hz at full throttle."
                 % (frame.hover_hz, frame.full_hz))

    top = noise["peaks"][0][0]
    if frame.hover_hz * 0.6 <= top <= frame.full_hz * 1.3:
        lines.append("  The strongest peak at %.0f Hz falls in that band, so it "
                     "is motor noise." % top)
    else:
        lines.append("  The strongest peak at %.0f Hz sits outside it. Frame "
                     "resonance and loose" % top)
        lines.append("  hardware show up this way, and neither is a filtering "
                     "problem.")
    return lines


def _compare_against_notches(noise, tune):
    low = tune.get_int("dyn_notch_min_hz")
    high = tune.get_int("dyn_notch_max_hz")
    lines = ["Against the configured notch range"]
    lines.append("-" * len(lines[0]))

    if low is None or high is None:
        lines.append("  No dynamic notch range set in the tune.")
        return lines

    lines.append("  Configured %d to %d Hz." % (low, high))
    outside = [f for f, _ in noise["peaks"] if not low <= f <= high]
    if outside:
        lines.append("  Outside that range: %s."
                     % ", ".join("%.0f Hz" % f for f in outside))
        lines.append("  The notches cannot track peaks they do not cover.")
    else:
        lines.append("  Every peak found falls inside it.")
    return lines
