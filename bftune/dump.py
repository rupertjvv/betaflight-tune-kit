"""
Parsing and writing Betaflight CLI dumps.

A `diff all` or `dump all` is a flat script of CLI commands with section
markers as comments. Settings appear as `set <name> = <value>`, and which
profile they belong to depends on the most recent `profile N` or
`rateprofile N` line above them, so the file cannot be read line by line
without tracking that state.

Nothing here has a whitelist of setting names. Betaflight renames parameters
between releases (`gyro_lowpass_hz` became `gyro_lpf1_static_hz` in 4.3, for
one), so unknown names are kept verbatim and round-trip unchanged rather than
being dropped. Only the code that has to reason about meaning, in categories
and review, knows specific names.
"""

import re

MASTER = "master"

_SET = re.compile(r"^set\s+([A-Za-z0-9_]+)\s*=\s*(.*)$")
_PROFILE = re.compile(r"^profile\s+(\d+)$")
_RATEPROFILE = re.compile(r"^rateprofile\s+(\d+)$")
_VERSION = re.compile(r"^#\s*Betaflight\s*/\s*(\S+).*?\s(\d+\.\d+\.\d+)")


class Tune:
    """Everything a dump carries, addressable by scope."""

    def __init__(self):
        # scope -> {name: value}. Scope is "master", "profile 0", etc.
        self.settings = {}
        # Non-`set` commands, kept in order so a dump can be rebuilt.
        self.commands = []
        self.board = None
        self.target = None
        self.version = None
        self.source = None

    # -- reading -------------------------------------------------------

    def get(self, name, scope=MASTER, default=None):
        return self.settings.get(scope, {}).get(name, default)

    def get_int(self, name, scope=MASTER, default=None):
        raw = self.get(name, scope)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def scopes(self):
        """Scope names, master first, then profiles in numeric order."""
        def key(scope):
            if scope == MASTER:
                return (0, 0, "")
            kind, _, index = scope.partition(" ")
            return (1 if kind == "profile" else 2, int(index), kind)

        return sorted(self.settings, key=key)

    def profiles(self):
        return [s for s in self.scopes() if s.startswith("profile ")]

    def rate_profiles(self):
        return [s for s in self.scopes() if s.startswith("rateprofile ")]

    def names(self):
        """Every (scope, name) pair present."""
        return {(scope, name)
                for scope, values in self.settings.items()
                for name in values}

    def features(self):
        """Enabled features. A leading '-' in the dump means disabled."""
        enabled = set()
        for command in self.commands:
            if command.startswith("feature "):
                value = command[len("feature "):].strip()
                if value.startswith("-"):
                    enabled.discard(value[1:])
                else:
                    enabled.add(value)
        return enabled

    # -- writing -------------------------------------------------------

    def set(self, name, value, scope=MASTER):
        self.settings.setdefault(scope, {})[name] = str(value)

    def to_cli(self):
        """
        Render back to CLI commands, ready to paste into the Configurator.

        Ordering follows the shape Betaflight itself emits: master settings
        first, then each profile behind its own selector, so applying the
        output puts every value back in the scope it came from.
        """
        lines = []
        if self.version:
            lines.append("# Betaflight %s" % self.version)
        lines.extend(self.commands)

        for scope in self.scopes():
            if scope != MASTER:
                lines.append("")
                lines.append(scope)
            for name in sorted(self.settings[scope]):
                lines.append("set %s = %s" % (name, self.settings[scope][name]))

        lines.append("")
        lines.append("save")
        return "\n".join(lines)


def parse(text, source=None):
    """Parse dump text into a Tune."""
    tune = Tune()
    tune.source = source
    scope = MASTER

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("#"):
            match = _VERSION.match(line)
            if match:
                tune.target = match.group(1)
                tune.version = match.group(2)
            continue

        match = _PROFILE.match(line)
        if match:
            scope = "profile %s" % match.group(1)
            tune.settings.setdefault(scope, {})
            continue

        match = _RATEPROFILE.match(line)
        if match:
            scope = "rateprofile %s" % match.group(1)
            tune.settings.setdefault(scope, {})
            continue

        match = _SET.match(line)
        if match:
            tune.settings.setdefault(scope, {})[match.group(1)] = match.group(2).strip()
            continue

        # `save` is an action, not configuration; re-emitted by to_cli anyway.
        if line == "save":
            continue

        if line.startswith("board_name "):
            tune.board = line.split(None, 1)[1].strip()
        if line.startswith("manufacturer_id ") and not tune.board:
            tune.board = line.split(None, 1)[1].strip()

        tune.commands.append(line)

    tune.settings.setdefault(MASTER, {})
    return tune


def parse_file(path):
    with open(path) as handle:
        return parse(handle.read(), source=path)
