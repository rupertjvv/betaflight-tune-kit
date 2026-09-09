"""
Grouping setting names into the things a pilot actually thinks about.

Betaflight has well over 500 settings and a `diff all` between two tunes can
easily run to fifty lines. Sorting them into PID, filter, rate and so on is
what turns that into something readable.

Classification is by pattern, not by a fixed list of names. Parameters get
renamed between releases and new ones appear every version, so a list would
silently mis-sort a dump from any firmware other than the one it was written
against. Patterns survive that, and anything genuinely unrecognised lands in
"other" where it is still shown rather than quietly dropped.
"""

import re

PID = "pid"
FILTER = "filter"
RATES = "rates"
RC = "rc"
MOTOR = "motor"
RX = "rx"
FAILSAFE = "failsafe"
OSD = "osd"
GPS = "gps"
OTHER = "other"

ORDER = [PID, FILTER, RATES, RC, MOTOR, RX, FAILSAFE, GPS, OSD, OTHER]

TITLES = {
    PID: "PID",
    FILTER: "Filters",
    RATES: "Rates",
    RC: "RC and feel",
    MOTOR: "Motors and ESC",
    RX: "Receiver",
    FAILSAFE: "Failsafe",
    OSD: "OSD",
    GPS: "GPS",
    OTHER: "Other",
}

# Order matters: the first pattern to match wins, so the specific ones that
# would otherwise be caught by a broader rule are listed above it.
_RULES = [
    # Anti-gravity, iterm behaviour and feedforward are all PID loop terms
    # even though their names do not start with p_/i_/d_.
    (PID, r"^(p|i|d|f)_(roll|pitch|yaw)$"),
    (PID, r"^d_(min|max)"),
    (PID, r"^(anti_gravity|iterm|itermrelax|abs_control|integrated_yaw)"),
    (PID, r"^(feedforward|ff)_"),
    (PID, r"^(pid|pidsum|tpa|thrust_linear|acro_trainer|angle|horizon)"),
    (PID, r"^(level|small_angle|crash_)"),

    # Filtering: lowpasses, notches, RPM filtering and the simplified sliders.
    (FILTER, r"^(gyro|dterm)_(lpf|notch|lowpass|soft)"),
    (FILTER, r"^dyn_(notch|lpf)"),
    (FILTER, r"^(rpm_filter|dshot_bidir)"),
    (FILTER, r"^simplified_"),
    (FILTER, r"^gyro_(filter|hardware_lpf|to_use|calib)"),

    (RATES, r"^(roll|pitch|yaw)_(rc_rate|srate|expo|rate_limit)$"),
    (RATES, r"^(rates_type|thr_mid|thr_expo|throttle_limit)"),

    (RC, r"^(rc_|deadband|yaw_deadband|rc_smoothing)"),

    (MOTOR, r"^(motor_|min_throttle|max_throttle|dshot|esc_|idle_|mixer)"),
    (MOTOR, r"^(3d_|throttle_boost|motor_output)"),

    (RX, r"^(rx_|serialrx|spektrum|sbus|crsf|ghst|msp_override|bind)"),

    (FAILSAFE, r"^(failsafe|rxfail)"),

    (GPS, r"^(gps|nav|rescue|imu_)"),

    (OSD, r"^(osd|vbat|amperage|ibata|current_meter|battery_)"),
]

_COMPILED = [(name, re.compile(pattern)) for name, pattern in _RULES]


def categorise(setting):
    """Which category a setting name belongs to."""
    for name, pattern in _COMPILED:
        if pattern.search(setting):
            return name
    return OTHER


def group(names):
    """Sort an iterable of setting names into {category: [name, ...]}."""
    grouped = {}
    for name in names:
        grouped.setdefault(categorise(name), []).append(name)
    for names_in_group in grouped.values():
        names_in_group.sort()
    return grouped


def in_order(grouped):
    """Yield (category, title, names) in display order, skipping empties."""
    for category in ORDER:
        if grouped.get(category):
            yield category, TITLES[category], grouped[category]
