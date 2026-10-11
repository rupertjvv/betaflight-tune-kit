"""Command line entry point: python -m bftune <command>."""

import argparse
import sys

from . import __version__, airframe, blackbox, compare, dump, plan, review


def build_airframe(args):
    """An Airframe from either a preset name or the individual numbers."""
    if args.preset:
        if args.preset not in airframe.PRESETS:
            raise SystemExit("Unknown preset %r. Available: %s"
                             % (args.preset, ", ".join(sorted(airframe.PRESETS))))
        frame = airframe.PRESETS[args.preset]
    else:
        missing = [name for name in ("prop", "cells", "kv")
                   if getattr(args, name) is None]
        if missing:
            raise SystemExit("Need --preset, or all of --prop, --cells and --kv "
                             "(missing: %s)" % ", ".join("--" + m for m in missing))
        frame = airframe.Airframe(
            args.prop, args.cells, args.kv,
            weight_g=args.weight,
            motor_poles=args.poles,
            bidirectional_dshot=args.bidir)

    overrides = (args.hover_load, args.full_load, args.twr)
    if not any(value is not None for value in overrides):
        return frame

    if args.hover_load is not None and args.twr is not None:
        raise SystemExit("Give --hover-load or --twr, not both. --twr derives "
                         "the hover load from thrust-to-weight.")

    full_load = args.full_load if args.full_load is not None else frame.full_load
    hover_load = args.hover_load
    if hover_load is None and args.twr is None:
        hover_load = frame.hover_load

    try:
        return airframe.Airframe(
            frame.prop_inches, frame.cells, frame.kv,
            weight_g=frame.weight_g,
            motor_poles=frame.motor_poles,
            hover_load=hover_load,
            full_load=full_load,
            thrust_to_weight=args.twr,
            bidirectional_dshot=frame.bidirectional_dshot,
            name=frame.name)
    except ValueError as exc:
        raise SystemExit(str(exc))


def add_airframe_args(parser):
    group = parser.add_argument_group("airframe")
    group.add_argument("--preset", help="one of: %s"
                       % ", ".join(sorted(airframe.PRESETS)))
    group.add_argument("--prop", type=float, help="prop diameter in inches")
    group.add_argument("--cells", type=int, help="battery cells in series (S)")
    group.add_argument("--kv", type=float, help="motor kV")
    group.add_argument("--weight", type=float, help="all up weight in grams")
    group.add_argument("--poles", type=int,
                       default=airframe.DEFAULT_MOTOR_POLES,
                       help="motor poles (default: %d, i.e. 12N14P)"
                            % airframe.DEFAULT_MOTOR_POLES)
    group.add_argument("--bidir", action="store_true",
                       help="ESCs support bidirectional DShot")
    group.add_argument("--twr", type=float, metavar="RATIO",
                       help="thrust-to-weight ratio. Derives the hover load "
                            "from it, since thrust goes as the square of prop "
                            "speed. Better than assuming a constant on a build "
                            "that is unusually light or heavy. The default "
                            "hover load corresponds to about %.0f:1"
                            % airframe.TYPICAL_TWR)
    group.add_argument("--hover-load", type=float,
                       help="fraction of no-load RPM in a hover (default: "
                            "%.2f). Use --twr instead when the ratio is known"
                            % airframe.HOVER_LOAD)
    group.add_argument("--full-load", type=float,
                       help="fraction of no-load RPM at full throttle "
                            "(default: %.2f)" % airframe.FULL_LOAD)


def cmd_show(args):
    tune = dump.parse_file(args.dump)
    print("%s" % (tune.source or "tune"))
    if tune.version:
        print("Betaflight %s on %s" % (tune.version, tune.target or "?"))
    if tune.board:
        print("board %s" % tune.board)
    print()
    for scope in tune.scopes():
        values = tune.settings[scope]
        if not values:
            continue
        print("%s  (%d settings)" % (scope, len(values)))
        if args.verbose:
            for name in sorted(values):
                print("  set %s = %s" % (name, values[name]))
    features = tune.features()
    if features:
        print()
        print("features: %s" % ", ".join(sorted(features)))
    return 0


def cmd_compare(args):
    before = dump.parse_file(args.before)
    after = dump.parse_file(args.after)
    changes = compare.compare(before, after)
    print(compare.format_report(changes, before, after))
    return 0


def cmd_plan(args):
    frame = build_airframe(args)
    generated = plan.filter_plan(frame, harmonics=args.harmonics)

    if args.cli:
        print(plan.to_cli(generated))
        return 0

    print(plan.format_report(frame, generated))

    if args.apply:
        tune = dump.parse_file(args.apply)
        plan.apply_to(tune, generated)
        if args.output:
            with open(args.output, "w") as handle:
                handle.write(tune.to_cli())
                handle.write("\n")
            print()
            print("Written to %s" % args.output)
        else:
            print()
            print(tune.to_cli())
    return 0


def cmd_review(args):
    tune = dump.parse_file(args.dump)
    frame = build_airframe(args) if (args.preset or args.prop) else None
    findings = review.review(tune, frame)
    print(review.format_report(findings, tune, frame))
    return 1 if any(f.severity == review.ERROR for f in findings) else 0


def cmd_analyse(args):
    log = blackbox.load(args.log)
    frame = build_airframe(args) if (args.preset or args.prop) else None
    tune = dump.parse_file(args.dump) if args.dump else None
    print(blackbox.format_report(log, frame, tune, axis=args.axis))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bftune",
        description="Tooling for Betaflight tunes: parse, compare, plan "
                    "filters, review and analyse logs.")
    parser.add_argument("--version", action="version",
                        version="bftune %s" % __version__)
    sub = parser.add_subparsers(dest="command")

    show = sub.add_parser("show", help="summarise a CLI dump")
    show.add_argument("dump")
    show.add_argument("-v", "--verbose", action="store_true",
                      help="list every setting")
    show.set_defaults(func=cmd_show)

    comp = sub.add_parser("compare", help="diff two dumps")
    comp.add_argument("before")
    comp.add_argument("after")
    comp.set_defaults(func=cmd_compare)

    pln = sub.add_parser("plan", help="filter settings for an airframe")
    add_airframe_args(pln)
    pln.add_argument("--harmonics", type=int, default=3,
                     help="RPM filter harmonics (default: 3)")
    pln.add_argument("--cli", action="store_true",
                     help="print only the CLI commands")
    pln.add_argument("--apply", metavar="DUMP",
                     help="write the plan into an existing dump")
    pln.add_argument("--output", metavar="FILE",
                     help="where to write the result of --apply")
    pln.set_defaults(func=cmd_plan)

    rev = sub.add_parser("review", help="check a dump for broken configurations")
    rev.add_argument("dump")
    add_airframe_args(rev)
    rev.set_defaults(func=cmd_review)

    ana = sub.add_parser("analyse", help="read a decoded blackbox CSV")
    ana.add_argument("log")
    ana.add_argument("--dump", help="check the log against this tune")
    ana.add_argument("--axis", default="roll", choices=("roll", "pitch", "yaw"))
    add_airframe_args(ana)
    ana.set_defaults(func=cmd_analyse)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2

    try:
        return args.func(args)
    except blackbox.MissingNumpy as exc:
        raise SystemExit(str(exc))
    except (OSError, ValueError) as exc:
        raise SystemExit("%s: %s" % (type(exc).__name__, exc))


if __name__ == "__main__":
    sys.exit(main())
