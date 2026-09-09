# betaflight-tune-kit

Command line tooling for Betaflight tunes: read a CLI dump, diff two of your own
tunes, work out filter frequencies from the airframe, check a config for
settings that cannot work, and read a blackbox log against all of it.

Everything except log analysis is standard library only.

## Status

Early days, built up a piece at a time. In so far:

- **dump** — parse a `diff all` into an addressable tune and re-emit it unchanged.
- **categories** — sort setting names into the groups a pilot thinks in.

Still to come: the airframe model, the filter planner, config review and
blackbox log analysis.
