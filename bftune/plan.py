"""
Turning an airframe into a filter configuration you can paste into the CLI.

Scope note, because it decides what this module does and does not do.

Filter frequencies follow from motor RPM, which follows from kV, voltage and
prop loading. That is arithmetic, and it is what this generates.

PID values do not work that way. They depend on frame stiffness, arm length,
motor response, prop pitch, weight distribution and what the pilot wants the
quad to feel like, none of which are in a spec sheet. Tools that print a PID
table from a prop size are guessing, and a guess delivered in a fixed-width
table reads as authority it has not earned. So this module does not generate
PIDs. Betaflight's defaults are a genuinely good starting point, and the way
to move off them is the sliders in the Configurator plus a blackbox log.

What the filter plan changes is worth stating plainly too: it is a starting
configuration, not a tune. It gets the notches looking in the right part of
the spectrum so that the first flight produces a log worth reading.
"""

from . import dump


def filter_plan(frame, harmonics=3):
    """
    Filter settings for an airframe, as {setting: (value, reason)}.

    Only settings there is a reason to move from default are included. A plan
    that restates every default buries the few lines that matter.
    """
    low, high = frame.dyn_notch_range()
    plan = {}

    plan["dyn_notch_min_hz"] = (
        low,
        "Below the ~%.0f Hz the motors turn at in a hover, so the notches can "
        "track down to the throttle setting the quad spends most of its time "
        "at." % frame.hover_hz)

    plan["dyn_notch_max_hz"] = (
        high,
        "Above the ~%.0f Hz they reach at full throttle on a fresh pack. The "
        "notches stop tracking past the ceiling, so it has to clear the "
        "noisiest case." % frame.full_hz)

    if frame.bidirectional_dshot:
        plan["dshot_bidir"] = (
            "ON",
            "Required for the RPM filter: it is how the ESCs report motor "
            "speed back to the flight controller.")
        plan["rpm_filter_harmonics"] = (
            harmonics,
            "Notches the first %d multiples of each motor's own frequency. "
            "Because it is told the RPM rather than searching for it, it is "
            "both narrower and faster to react than the dynamic notch."
            % harmonics)
        plan["motor_poles"] = (
            frame.motor_poles,
            "Used to convert the ESC's electrical RPM to shaft RPM. Wrong "
            "here puts every RPM notch at the wrong frequency, in proportion.")
        plan["dyn_notch_count"] = (
            3,
            "With the RPM filter carrying the motor harmonics, the dynamic "
            "notch is left to catch frame resonance, and needs fewer notches "
            "to do it.")
    else:
        plan["dyn_notch_count"] = (
            4,
            "Without RPM telemetry the dynamic notch is the only thing "
            "tracking motor noise, so it gets an extra notch to work with.")

    return plan


def to_cli(plan):
    """Render a plan as CLI commands."""
    lines = []
    for name in sorted(plan):
        value, _ = plan[name]
        lines.append("set %s = %s" % (name, value))
    lines.append("save")
    return "\n".join(lines)


def apply_to(tune, plan, scope=dump.MASTER):
    """Write a plan into a Tune, returning it, so a full dump can be re-emitted."""
    for name, (value, _) in plan.items():
        tune.set(name, value, scope)
    return tune


def format_report(frame, plan):
    lines = []
    lines.append(frame.name)
    lines.append("=" * len(frame.name))
    lines.append("")

    lines.append("Motor speed")
    lines.append("-----------")
    lines.append("  kV %.0f on %dS" % (frame.kv, frame.cells))
    lines.append("  %.1f V loaded, %.1f V fresh"
                 % (frame.volts_loaded, frame.volts_full))
    lines.append("  no load        %6.0f rpm" % frame.no_load_rpm)
    lines.append("  hover (%.0f%%)    %6.0f rpm   %5.0f Hz"
                 % (frame.hover_load * 100, frame.hover_rpm, frame.hover_hz))
    if frame.thrust_to_weight:
        lines.append("                 from %.1f:1 thrust to weight, since "
                     "thrust goes as" % frame.thrust_to_weight)
        lines.append("                 the square of prop speed")
    lines.append("  full  (%.0f%%)    %6.0f rpm   %5.0f Hz"
                 % (frame.full_load * 100, frame.full_rpm, frame.full_hz))
    lines.append("")
    lines.append("  Harmonics at full throttle: %s"
                 % ", ".join("%.0f Hz" % h for h in frame.harmonics(3)))
    if frame.bidirectional_dshot:
        lines.append("  ESC reports %.0f Hz electrical at full throttle "
                     "(%d poles)."
                     % (frame.erpm_hz(frame.full_rpm), frame.motor_poles))
    lines.append("")

    lines.append("Filter plan")
    lines.append("-----------")
    for name in sorted(plan):
        value, reason = plan[name]
        lines.append("")
        lines.append("  set %s = %s" % (name, value))
        lines.append("    %s" % _wrap(reason))

    lines.append("")
    lines.append("Paste-ready")
    lines.append("-----------")
    lines.append("")
    for line in to_cli(plan).splitlines():
        lines.append("  %s" % line)

    lines.append("")
    lines.append(_wrap(
        "This is a starting configuration, not a tune. The load factors "
        "behind the RPM estimates are assumptions, not measurements. Fly it, "
        "log it, and check the peaks in the log against these numbers "
        "before trusting them."))

    if frame.aliasing_risk:
        lines.append("")
        lines.append(_wrap(
            "Note: the third harmonic lands near %.0f Hz, close to what an "
            "8 kHz loop can represent. Peaks reported above roughly 4 kHz may "
            "be aliases rather than real content." % (frame.full_hz * 3)))

    return "\n".join(lines)


def _wrap(text, width=70, indent=4):
    import textwrap
    return textwrap.fill(text, width=width).replace("\n", "\n" + " " * indent)
