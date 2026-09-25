"""
Comparing two tunes.

The Configurator will show you a `diff` against firmware defaults, but not
against your own previous tune. After a few flying sessions of small changes
that is the thing you actually want: what is different between the tune that
flew well on Saturday and the one that does not now.
"""

from . import categories
from .dump import MASTER

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"


class Change:
    def __init__(self, kind, scope, name, before=None, after=None):
        self.kind = kind
        self.scope = scope
        self.name = name
        self.before = before
        self.after = after

    @property
    def category(self):
        return categories.categorise(self.name)

    def describe(self):
        if self.kind == ADDED:
            return "%s = %s (new)" % (self.name, self.after)
        if self.kind == REMOVED:
            return "%s removed (was %s)" % (self.name, self.before)
        return "%s: %s -> %s" % (self.name, self.before, self.after)

    def delta(self):
        """
        Numeric change, or None if either side is not a plain number.

        Values in a dump are strings, and plenty of them are not numbers at
        all (`gyro_to_use = FIRST`), so this has to fail softly.
        """
        try:
            return float(self.after) - float(self.before)
        except (TypeError, ValueError):
            return None

    def percent(self):
        try:
            before = float(self.before)
        except (TypeError, ValueError):
            return None
        if before == 0:
            return None
        return 100.0 * (float(self.after) - before) / before

    def __repr__(self):
        return "<Change %s %s %s>" % (self.kind, self.scope, self.name)


def compare(before, after):
    """Every difference between two Tune objects, ordered by scope then name."""
    changes = []

    scopes = sorted(set(before.settings) | set(after.settings),
                    key=lambda s: (s != MASTER, s))

    for scope in scopes:
        old = before.settings.get(scope, {})
        new = after.settings.get(scope, {})

        for name in sorted(set(old) | set(new)):
            if name not in old:
                changes.append(Change(ADDED, scope, name, after=new[name]))
            elif name not in new:
                changes.append(Change(REMOVED, scope, name, before=old[name]))
            elif old[name] != new[name]:
                changes.append(Change(CHANGED, scope, name, old[name], new[name]))

    return changes


def by_category(changes):
    """{category: [Change, ...]}, for grouped display."""
    grouped = {}
    for change in changes:
        grouped.setdefault(change.category, []).append(change)
    return grouped


def format_report(changes, before=None, after=None):
    """A readable summary of a comparison."""
    lines = []

    if before is not None and after is not None:
        lines.append("%s  ->  %s" % (_label(before), _label(after)))
        if before.version and after.version and before.version != after.version:
            lines.append("")
            lines.append("Firmware differs (%s -> %s). Some of the changes below "
                         "will be" % (before.version, after.version))
            lines.append("defaults moving or parameters being renamed, not "
                         "choices you made.")
        lines.append("")

    if not changes:
        lines.append("No differences.")
        return "\n".join(lines)

    lines.append("%d difference%s" % (len(changes), "" if len(changes) == 1 else "s"))

    grouped = by_category(changes)
    for category in categories.ORDER:
        section = grouped.get(category)
        if not section:
            continue

        title = categories.TITLES[category]
        lines.append("")
        lines.append(title)
        lines.append("-" * len(title))

        current_scope = None
        for change in sorted(section, key=lambda c: (c.scope != MASTER, c.scope, c.name)):
            if change.scope != current_scope:
                current_scope = change.scope
                if current_scope != MASTER:
                    lines.append("  [%s]" % current_scope)

            note = ""
            pct = change.percent()
            if pct is not None and abs(pct) >= 1:
                note = "  (%+.0f%%)" % pct
            lines.append("  %s%s" % (change.describe(), note))

    return "\n".join(lines)


def _label(tune):
    parts = []
    if tune.source:
        parts.append(str(tune.source))
    if tune.version:
        parts.append("BF %s" % tune.version)
    if tune.target:
        parts.append(tune.target)
    return ", ".join(parts) or "tune"
