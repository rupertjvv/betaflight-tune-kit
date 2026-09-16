"""
Working out where a given quad's motor noise will sit.

Propeller noise is not spread evenly across the spectrum. It is concentrated
at the motor rotation frequency and its harmonics, which is why Betaflight
filters it with tracking notches rather than a fixed lowpass. Where those
notches need to reach is decided by the motor's RPM range, and that follows
from kV, pack voltage and how hard the props load the motor.

The arithmetic here is deliberately plain:

    no-load RPM      = kV * volts
    in-flight RPM    = no-load RPM * load factor
    fundamental Hz   = RPM / 60
    harmonic n Hz    = fundamental * n

The one soft number is the load factor. A propeller is a load, so a motor
never reaches its no-load speed in flight, and how far short it falls depends
on the prop, the airframe and the air. It cannot be derived from a spec
sheet, so it is an explicit, documented, adjustable assumption rather than
something buried in a constant. The defaults below are conservative: they
spread the band wider than a typical quad needs, because a notch range that
is too wide costs a little filter delay, while one that is too narrow leaves
the noise it was supposed to catch untouched.

Nothing here replaces looking at a blackbox log. It gets you a sane starting
configuration so the first flight is worth logging.
"""

import math

# Betaflight's own limits, which the recommendations are clamped to.
DYN_NOTCH_MIN_LIMIT = 60
DYN_NOTCH_MAX_LIMIT = 1000

# Fraction of no-load RPM the motors actually turn at. Hover sits low in the
# range; the top of the band is what the notches must still reach on a hard
# punch out.
#
# The hover default is not free-floating: a fixed pitch propeller produces
# thrust roughly in proportion to the square of its speed, so a quad hovers
# at the fraction of its full throttle speed that produces its own weight,
#
#     RPM_hover / RPM_full = sqrt(1 / thrust-to-weight)
#
# and 0.35 out of 0.80 is what that gives for a thrust-to-weight near 5,
# which is an ordinary 5 inch freestyle build. Lighter and punchier quads
# hover lower and put their noise lower with it, which is what
# hover_load_for_twr exists to work out. See TYPICAL_TWR.
HOVER_LOAD = 0.35
FULL_LOAD = 0.80

# The thrust-to-weight the HOVER_LOAD default corresponds to.
TYPICAL_TWR = 5.0

# A pack is only at 4.2 V per cell for a few seconds. Sag under load is what
# the motors see for most of the flight.
CELL_VOLTS_FULL = 4.2
CELL_VOLTS_LOADED = 3.7

# Most quad motors are 12N14P, so 14 poles, 7 pole pairs. This matters for
# the RPM filter, which reads eRPM from the ESC and needs the pole count to
# convert it to mechanical RPM.
DEFAULT_MOTOR_POLES = 14


def hover_load_for_twr(thrust_to_weight, full_load=FULL_LOAD):
    """
    The hover load factor implied by a thrust-to-weight ratio.

    A fixed pitch propeller's static thrust goes roughly as the square of its
    speed. To hover, the four motors together have to produce the aircraft's
    weight, which is 1/TWR of what they produce wide open, so

        RPM_hover / RPM_full = sqrt(1 / TWR)

    This is worth deriving rather than assuming because it moves a long way
    across real builds. A heavy 7 inch at 3:1 hovers near half its full
    speed; a light 5 inch at 9:1 hovers near a third of it, and puts its
    hover noise a hundred Hz lower as a result. Guessing one number for both
    puts the notch floor above the noise on the light one.

    The square law is an approximation. It ignores the airflow the craft is
    already sitting in and the way the motor's own efficiency moves across
    its range, both of which push real hover RPM slightly above this. It is
    still much closer than a constant.
    """
    if thrust_to_weight <= 1:
        raise ValueError("thrust-to-weight must exceed 1, or it cannot hover")
    return full_load / math.sqrt(thrust_to_weight)


class Airframe:
    """The handful of numbers that decide where the noise lands."""

    def __init__(self, prop_inches, cells, kv, weight_g=None,
                 motor_poles=DEFAULT_MOTOR_POLES,
                 hover_load=None, full_load=FULL_LOAD,
                 thrust_to_weight=None,
                 bidirectional_dshot=False, name=None):
        if prop_inches <= 0:
            raise ValueError("prop size must be positive")
        if cells <= 0:
            raise ValueError("cell count must be positive")
        if kv <= 0:
            raise ValueError("kV must be positive")
        if motor_poles <= 0 or motor_poles % 2:
            raise ValueError("motor poles must be a positive even number")

        if hover_load is not None and thrust_to_weight is not None:
            raise ValueError("give hover_load or thrust_to_weight, not both")

        # Deriving the hover load from thrust-to-weight is the better route
        # when the ratio is known, because it is the thing that physically
        # decides where the quad sits on the throttle.
        self.thrust_to_weight = thrust_to_weight
        if thrust_to_weight is not None:
            hover_load = hover_load_for_twr(thrust_to_weight, full_load)
        elif hover_load is None:
            hover_load = HOVER_LOAD

        if not 0 < hover_load <= full_load <= 1.0:
            raise ValueError("load factors must satisfy 0 < hover <= full <= 1")

        self.prop_inches = float(prop_inches)
        self.cells = int(cells)
        self.kv = float(kv)
        self.weight_g = weight_g
        self.motor_poles = int(motor_poles)
        self.hover_load = float(hover_load)
        self.full_load = float(full_load)
        self.bidirectional_dshot = bool(bidirectional_dshot)
        self.name = name or self.describe()

    def describe(self):
        return '%g" %dS %.0fkV' % (self.prop_inches, self.cells, self.kv)

    @property
    def volts_full(self):
        return self.cells * CELL_VOLTS_FULL

    @property
    def volts_loaded(self):
        return self.cells * CELL_VOLTS_LOADED

    @property
    def no_load_rpm(self):
        """Motor speed with no propeller, on a full pack. The ceiling."""
        return self.kv * self.volts_full

    def rpm_at(self, load, volts=None):
        """In-flight motor RPM at a given fraction of no-load speed."""
        if volts is None:
            volts = self.volts_loaded
        return self.kv * volts * load

    @property
    def hover_rpm(self):
        return self.rpm_at(self.hover_load)

    @property
    def full_rpm(self):
        # Punch outs happen on a fresh pack, so use the higher voltage here.
        return self.rpm_at(self.full_load, self.volts_full)

    @property
    def hover_hz(self):
        """Fundamental noise frequency in a hover."""
        return self.hover_rpm / 60.0

    @property
    def full_hz(self):
        """Fundamental at full throttle on a fresh pack."""
        return self.full_rpm / 60.0

    def harmonics(self, count=3, load=None):
        """The first `count` harmonics of the fundamental, in Hz."""
        if count < 1:
            raise ValueError("need at least one harmonic")
        base = self.full_hz if load is None else self.rpm_at(load) / 60.0
        return [base * n for n in range(1, count + 1)]

    def erpm_hz(self, rpm):
        """
        Electrical frequency the ESC reports for a given mechanical RPM.

        Bidirectional DShot telemetry is in eRPM, and the flight controller
        divides by the pole pairs to recover shaft speed. Setting motor_poles
        wrongly is a common cause of an RPM filter that notches the wrong
        frequency and appears to do nothing.
        """
        return rpm * (self.motor_poles / 2.0) / 60.0

    @property
    def aliasing_risk(self):
        """
        Whether the third harmonic is near the edge of what the gyro can see.

        Betaflight runs its loop at 8 kHz on most targets, so content above
        about 4 kHz folds back down the spectrum rather than being filtered
        out, and no notch placed by frequency will catch it.
        """
        return self.full_hz * 3 > 4000

    def dyn_notch_range(self, margin=0.6, headroom=1.15):
        """
        The dynamic notch band this airframe needs.

        The bottom sits well under the hover fundamental. The margin is
        generous on purpose and errs low: the load factor behind the hover
        estimate is the softest number here, and a floor set above the real
        hover noise leaves exactly the noise the notches exist for
        unfiltered. Set it too low instead and the cost is only that the
        notches have more range to search.

        The top clears the full throttle fundamental, because a notch that
        cannot reach the noise contributes delay and nothing else.
        """
        low = int(math.floor(self.hover_hz * margin))
        high = int(math.ceil(self.full_hz * headroom))

        low = max(DYN_NOTCH_MIN_LIMIT, low)
        high = min(DYN_NOTCH_MAX_LIMIT, high)
        if high <= low:
            high = min(DYN_NOTCH_MAX_LIMIT, low + 100)
        return low, high

    def covers(self, low_hz, high_hz):
        """Does a configured notch range actually contain this quad's noise?"""
        return low_hz <= self.hover_hz and high_hz >= self.full_hz

    def summary(self):
        low, high = self.dyn_notch_range()
        return {
            "name": self.name,
            "prop_inches": self.prop_inches,
            "cells": self.cells,
            "kv": self.kv,
            "motor_poles": self.motor_poles,
            "volts_loaded": self.volts_loaded,
            "volts_full": self.volts_full,
            "no_load_rpm": self.no_load_rpm,
            "hover_rpm": self.hover_rpm,
            "full_rpm": self.full_rpm,
            "hover_hz": self.hover_hz,
            "full_hz": self.full_hz,
            "harmonics": self.harmonics(3),
            "dyn_notch_min_hz": low,
            "dyn_notch_max_hz": high,
            "bidirectional_dshot": self.bidirectional_dshot,
        }


# A few common builds, so the CLI can be tried without knowing every number.
PRESETS = {
    "5inch-6s": Airframe(5, 6, 1900, weight_g=650, bidirectional_dshot=True,
                         name='5" 6S freestyle'),
    "5inch-4s": Airframe(5, 4, 2400, weight_g=600, bidirectional_dshot=True,
                         name='5" 4S freestyle'),
    "7inch-6s": Airframe(7, 6, 1350, weight_g=1100, bidirectional_dshot=True,
                         name='7" 6S long range'),
    "3inch-4s": Airframe(3, 4, 3800, weight_g=250, bidirectional_dshot=True,
                         name='3" 4S cinewhoop'),
    "toothpick-2s": Airframe(2.5, 2, 6000, weight_g=90,
                             name='2.5" 2S toothpick'),
}
