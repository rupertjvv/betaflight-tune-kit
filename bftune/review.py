"""
Checking a tune for the mistakes that are easy to make and hard to see.

Betaflight will happily accept a configuration that cannot work. The RPM
filter with bidirectional DShot switched off does nothing at all. A notch
range that stops below the motor frequency filters empty spectrum. A pole
count that does not match the motors puts every RPM notch at the wrong
frequency. None of these produce an error, a warning, or anything visible in
the Configurator: the quad just flies worse than it should and the reason is
invisible until someone reads a blackbox log.

Each finding says what is wrong, why it matters and what to do, because a
warning that only names a parameter is not much use at the field.

These are consistency checks against the airframe and against Betaflight's
own requirements. They are not a judgement about whether a tune flies well,
which is not a thing that can be decided from a config file.
"""

from .dump import MASTER

ERROR = "error"
WARNING = "warning"
NOTE = "note"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, NOTE: 2}


class Finding:
    def __init__(self, severity, title, detail, fix=None, setting=None):
        self.severity = severity
        self.title = title
        self.detail = detail
        self.fix = fix
        self.setting = setting

    def __repr__(self):
        return "<Finding %s %r>" % (self.severity, self.title)


def review(tune, frame=None):
    """
    Check a Tune, optionally against the Airframe it is meant to fly on.

    Without an airframe only the internal consistency checks run, since
    anything about frequencies needs to know what the motors are doing.
    """
    findings = []
    findings.extend(_check_rpm_filter(tune, frame))
    findings.extend(_check_notch_range(tune, frame))
    findings.extend(_check_notch_count(tune))
    findings.extend(_check_lowpass(tune))
    findings.extend(_check_dterm(tune))
    findings.extend(_check_failsafe(tune))
    findings.extend(_check_blackbox(tune, frame))
    findings.sort(key=lambda f: _SEVERITY_ORDER[f.severity])
    return findings


# Betaflight's gyro runs at 8 kHz on the targets this is aimed at. The log
# rate is the PID loop rate divided down, and the PID loop rate is the gyro
# rate divided by pid_process_denom.
ASSUMED_GYRO_HZ = 8000


def logged_rate_hz(tune, gyro_hz=ASSUMED_GYRO_HZ):
    """
    How fast the blackbox is actually sampling, or None if it cannot be told.

    blackbox_sample_rate is an exponent, not a frequency: 0 logs every PID
    iteration, 1 every second one, 2 every fourth, and so on.
    """
    denom = tune.get_int("pid_process_denom", default=1) or 1
    exponent = tune.get_int("blackbox_sample_rate")
    if exponent is None:
        return None
    return gyro_hz / float(denom) / float(2 ** exponent)


def _check_blackbox(tune, frame):
    findings = []

    device = tune.get("blackbox_device")
    if device is not None and device.upper() in ("NONE", "0"):
        findings.append(Finding(
            NOTE,
            "Blackbox logging is switched off",
            "blackbox_device is %s. Everything past a starting configuration "
            "depends on being able to see what the quad actually did, and "
            "without a log the only instrument left is how it felt." % device,
            "Set blackbox_device to whatever this board has, SDCARD or "
            "SPIFLASH, and log a flight before changing filters again.",
            "blackbox_device"))
        return findings

    rate = logged_rate_hz(tune)
    if rate is None or frame is None:
        return findings

    # Nyquist: a peak at f needs better than 2f of sampling to exist in the
    # log at all. Below that it does not merely look small, it folds down the
    # spectrum and appears as a peak at the wrong frequency.
    needed = 2.0 * frame.full_hz
    if rate < needed:
        findings.append(Finding(
            WARNING,
            "Log rate is too low to see this quad's own noise",
            "The blackbox is sampling near %.0f Hz, but the motors reach "
            "about %.0f Hz at full throttle, which needs more than %.0f Hz to "
            "record at all. Below that the peak does not just come out quiet, "
            "it folds down the spectrum and shows up at a frequency that is "
            "not there. Assumes an %d Hz gyro."
            % (rate, frame.full_hz, needed, ASSUMED_GYRO_HZ),
            "Lower blackbox_sample_rate, which logs more often, until the "
            "rate clears %.0f Hz." % needed,
            "blackbox_sample_rate"))
    elif rate < 6.0 * frame.full_hz:
        findings.append(Finding(
            NOTE,
            "Log rate covers the fundamental but not its harmonics",
            "Sampling near %.0f Hz records the %.0f Hz fundamental, but the "
            "second and third harmonics at %.0f and %.0f Hz are above what it "
            "can represent. Those are what the RPM filter's extra harmonics "
            "are aimed at, so their effect will not be visible in the log."
            % (rate, frame.full_hz, frame.full_hz * 2, frame.full_hz * 3),
            "Enough for checking the notch range. Log faster if you want to "
            "judge the higher harmonics.",
            "blackbox_sample_rate"))

    return findings


def _check_rpm_filter(tune, frame):
    harmonics = tune.get_int("rpm_filter_harmonics", default=None)
    bidir = tune.get("dshot_bidir", default=None)
    poles = tune.get_int("motor_poles", default=None)

    rpm_on = harmonics is not None and harmonics > 0
    bidir_on = bidir in ("ON", "1")

    if rpm_on and bidir is not None and not bidir_on:
        # Nothing else about the RPM filter is worth reporting while it has
        # no data to work from.
        return [Finding(
            ERROR,
            "RPM filter is configured but has no data",
            "rpm_filter_harmonics is %d, but dshot_bidir is %s. The RPM filter "
            "places its notches from ESC telemetry, and without "
            "bidirectional DShot that telemetry never arrives, so the filter "
            "does nothing while still costing loop time." % (harmonics, bidir),
            "Set dshot_bidir = ON, or set rpm_filter_harmonics = 0 and rely "
            "on the dynamic notch.",
            "rpm_filter_harmonics")]

    findings = []

    if bidir_on and not rpm_on:
        findings.append(Finding(
            WARNING,
            "Bidirectional DShot is on but the RPM filter is off",
            "The ESCs are sending RPM telemetry and nothing is using it. The "
            "RPM filter is the most targeted filtering Betaflight has, and "
            "running without it usually means leaning harder on lowpasses, "
            "which costs more delay.",
            "Set rpm_filter_harmonics = 3.",
            "rpm_filter_harmonics"))

    if rpm_on and frame is not None and poles is not None:
        if poles != frame.motor_poles:
            findings.append(Finding(
                ERROR,
                "Motor pole count does not match the airframe",
                "motor_poles is %d but the airframe is set up as %d. The "
                "flight controller converts ESC eRPM to shaft RPM with this "
                "number, so if it is wrong every RPM notch sits at the wrong "
                "frequency, by the ratio of the two values."
                % (poles, frame.motor_poles),
                "Set motor_poles = %d, counting the magnets inside the bell "
                "if you are unsure." % frame.motor_poles,
                "motor_poles"))

    if rpm_on and harmonics > 3:
        findings.append(Finding(
            NOTE,
            "More RPM harmonics than usual",
            "rpm_filter_harmonics is %d. Each harmonic is a notch per motor, "
            "so this is %d notches of processing, and the higher harmonics "
            "carry progressively less energy." % (harmonics, harmonics * 4),
            "3 is the usual setting unless a log shows energy higher up.",
            "rpm_filter_harmonics"))

    return findings


def _check_notch_range(tune, frame):
    low = tune.get_int("dyn_notch_min_hz")
    high = tune.get_int("dyn_notch_max_hz")

    if low is None and high is None:
        return []

    findings = []

    if low is not None and high is not None and low >= high:
        findings.append(Finding(
            ERROR,
            "Dynamic notch range is inverted",
            "dyn_notch_min_hz is %d and dyn_notch_max_hz is %d, so the band "
            "is empty and the notches have nowhere to go." % (low, high),
            "Put the minimum below the maximum.",
            "dyn_notch_min_hz"))
        return findings

    if frame is None:
        return findings

    if high is not None and high < frame.full_hz:
        findings.append(Finding(
            WARNING,
            "Dynamic notch cannot reach full throttle noise",
            "dyn_notch_max_hz is %d Hz, but the motors reach about %.0f Hz at "
            "full throttle on a fresh pack. Above the ceiling the notches "
            "simply stop tracking, so the noisiest part of the throttle range "
            "is the least filtered." % (high, frame.full_hz),
            "Set dyn_notch_max_hz = %d." % frame.dyn_notch_range()[1],
            "dyn_notch_max_hz"))

    if low is not None and low > frame.hover_hz:
        findings.append(Finding(
            WARNING,
            "Dynamic notch floor is above hover noise",
            "dyn_notch_min_hz is %d Hz, but the motors sit near %.0f Hz in a "
            "hover. The quad spends most of its flight below the floor, where "
            "the notches will not follow." % (low, frame.hover_hz),
            "Set dyn_notch_min_hz = %d." % frame.dyn_notch_range()[0],
            "dyn_notch_min_hz"))

    if frame.aliasing_risk:
        findings.append(Finding(
            NOTE,
            "Third harmonic is close to the sampling limit",
            "Full throttle puts the third harmonic near %.0f Hz. Betaflight's "
            "8 kHz loop can only represent content up to about 4 kHz, so "
            "anything above that folds back down the spectrum instead of "
            "being filtered." % (frame.full_hz * 3),
            "Nothing to change in the config. It is a reason not to chase a "
            "high frequency peak in a log that may not really be there."))

    return findings


def _check_notch_count(tune):
    count = tune.get_int("dyn_notch_count")
    q = tune.get_int("dyn_notch_q")
    findings = []

    if count is not None and count > 5:
        findings.append(Finding(
            WARNING,
            "Unusually many dynamic notches",
            "dyn_notch_count is %d. Each notch costs loop time and a little "
            "phase delay, and past about three the returns fall off quickly."
            % count,
            "3 is the default and suits most builds.",
            "dyn_notch_count"))

    if q is not None and q > 500:
        findings.append(Finding(
            NOTE,
            "Very narrow dynamic notches",
            "dyn_notch_q is %d, which makes each notch sharp. Sharp notches "
            "remove less of the signal, but they also have to be centred "
            "accurately to catch anything at all." % q,
            "Worth widening towards 300 if a log shows peaks surviving the "
            "notches.",
            "dyn_notch_q"))

    return findings


def _check_lowpass(tune):
    findings = []

    static = tune.get_int("gyro_lpf1_static_hz")
    dyn_min = tune.get_int("gyro_lpf1_dyn_min_hz")
    dyn_max = tune.get_int("gyro_lpf1_dyn_max_hz")

    if dyn_min is not None and dyn_max is not None and 0 < dyn_max < dyn_min:
        findings.append(Finding(
            ERROR,
            "Gyro dynamic lowpass range is inverted",
            "gyro_lpf1_dyn_min_hz is %d and gyro_lpf1_dyn_max_hz is %d."
            % (dyn_min, dyn_max),
            "Put the minimum below the maximum.",
            "gyro_lpf1_dyn_min_hz"))

    if static is not None and static == 0 and not dyn_min:
        findings.append(Finding(
            WARNING,
            "Gyro lowpass 1 is disabled entirely",
            "gyro_lpf1_static_hz is 0 with no dynamic lowpass configured. "
            "This is sometimes done deliberately on a very clean build "
            "running the RPM filter, but it leaves nothing between broadband "
            "motor noise and the PID loop.",
            "Deliberate on a clean build with the RPM filter working. Worth "
            "confirming against a log if it was not.",
            "gyro_lpf1_static_hz"))

    return findings


def _check_dterm(tune):
    findings = []

    for scope in tune.profiles() or [MASTER]:
        d_roll = tune.get_int("d_roll", scope)
        d_min = tune.get_int("d_min_roll", scope)

        if d_roll is not None and d_min is not None and d_min > d_roll:
            findings.append(Finding(
                WARNING,
                "D min is above D max",
                "In %s, d_min_roll is %d while d_roll is %d. D min is the "
                "floor that D falls back to when the quad is not being "
                "commanded, so it is meant to sit below the maximum. "
                "Betaflight will ignore D min when it is set higher."
                % (scope, d_min, d_roll),
                "Set d_min_roll below d_roll, or set it to 0 to switch the "
                "feature off.",
                "d_min_roll"))

        dterm_lpf = tune.get_int("dterm_lpf1_static_hz", scope)
        if dterm_lpf is not None and dterm_lpf > 250:
            findings.append(Finding(
                NOTE,
                "D term lowpass is set high",
                "In %s, dterm_lpf1_static_hz is %d. A high cutoff keeps D "
                "responsive but lets more motor noise through onto the term "
                "that amplifies it most, which shows up as hot motors before "
                "it shows up in the way the quad flies." % (scope, dterm_lpf),
                "Reasonable on a build with the RPM filter working. Check "
                "motor temperature after a flight.",
                "dterm_lpf1_static_hz"))

    return findings


def _check_failsafe(tune):
    procedure = tune.get("failsafe_procedure")
    if procedure is None:
        return []

    if procedure.upper() in ("DROP", "0"):
        return [Finding(
            NOTE,
            "Failsafe is set to drop",
            "failsafe_procedure is %s, so the quad cuts motors on signal "
            "loss. That is the right choice for a bando or close range "
            "freestyle, and the wrong one if it is ever out of gliding "
            "distance." % procedure,
            "Deliberate for most freestyle. Worth revisiting for anything "
            "flown far from you.",
            "failsafe_procedure")]

    return []


def format_report(findings, tune=None, frame=None):
    lines = []

    if tune is not None:
        label = tune.source or "tune"
        if tune.version:
            detail = "Betaflight %s" % tune.version
            if tune.target:
                detail += ", %s" % tune.target
            label += "  (%s)" % detail
        lines.append(label)
    if frame is not None:
        lines.append("against %s" % frame.name)
    if lines:
        lines.append("")

    if not findings:
        lines.append("No problems found.")
        return "\n".join(lines)

    counts = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    lines.append(", ".join("%d %s%s" % (counts[s], s, "" if counts[s] == 1 else "s")
                           for s in (ERROR, WARNING, NOTE) if s in counts))

    for finding in findings:
        lines.append("")
        lines.append("[%s] %s" % (finding.severity.upper(), finding.title))
        lines.append("  %s" % _wrap(finding.detail))
        if finding.fix:
            lines.append("  Fix: %s" % _wrap(finding.fix, indent=7))

    return "\n".join(lines)


def _wrap(text, width=72, indent=2):
    import textwrap
    body = textwrap.fill(text, width=width)
    return body.replace("\n", "\n" + " " * indent)
