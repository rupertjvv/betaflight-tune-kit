# betaflight-tune-kit

Command line tooling for Betaflight tunes: read a CLI dump, diff two of your own
tunes, work out filter frequencies from the airframe, check a config for settings
that cannot work, and read a blackbox log against all of it.

Where propeller noise lands in the spectrum is decided by how fast the motors
turn, and that follows from kV, pack voltage and prop loading. I wanted the
notch filter range worked out for the build in front of me rather than copied
from a number someone else's quad liked.

## Running it

Clone it. Everything except `analyse` is standard library only, and `analyse`
needs numpy (`pip install numpy`).

```
python -m bftune plan    --preset 5inch-6s
python -m bftune review  mytune.txt --preset 5inch-6s
python -m bftune compare saturday.txt sunday.txt
python -m bftune analyse LOG00001.01.csv --dump mytune.txt --preset 5inch-6s
python -m bftune show    mytune.txt
```

The presets are `5inch-6s`, `5inch-4s`, `7inch-6s`, `3inch-4s` and
`toothpick-2s`, or give `--prop`, `--cells` and `--kv` directly. `plan --cli`
prints just the commands to paste. `analyse` reads a log once `blackbox_decode`
has turned it into CSV.

`review` on the deliberately broken dump in `tests/fixtures/`:

```
$ python -m bftune review tests/fixtures/example_diff.txt --preset 5inch-6s
tests/fixtures/example_diff.txt  (Betaflight 4.4.2, STM32F405)
against 5" 6S freestyle

1 error, 1 warning, 1 note

[ERROR] RPM filter is configured but has no data
  rpm_filter_harmonics is 3, but dshot_bidir is OFF. The RPM filter places
  its notches from ESC telemetry, and without bidirectional DShot that
  telemetry never arrives, so the filter does nothing while still costing
  loop time.
  Fix: Set dshot_bidir = ON, or set rpm_filter_harmonics = 0 and rely on the
       dynamic notch.
...
```

It exits non-zero when it finds an error, so it drops into a script.

## Worth knowing

 - The motor speed estimate rests on one assumption: how far short of no-load
   RPM the motors run with a prop on. The defaults, 0.35 hovering and 0.80 at
   full throttle, spread the notch band wide on purpose, since a band that is
   too narrow misses the noise and one that is too wide only costs a little
   delay. `--twr` works the hover figure out from thrust-to-weight instead.
 - It does not generate PID values. Those depend on the frame, the motors and
   how you want the quad to feel, none of which are in a spec sheet.
 - I wrote and tested it against Betaflight 4.4 dumps. The parser keeps setting
   names it does not know rather than dropping them, but `plan` and `review`
   rely on specific parameter names.
 - Change one thing at a time and keep a copy of a `diff all` that flew.

## Tests

```
python -m unittest discover -s tests
```

176 tests, no hardware. The log analysis is checked against synthetic gyro
traces built at a known frequency, and the dump fixtures are written by hand
rather than taken from a real aircraft.

Rupert van Vuuren. BEng Electrical and Electronic Engineering, Stellenbosch
University.
