# betaflight-tune-kit

Command line tooling for Betaflight tunes: read a CLI dump, diff two of your own
tunes, work out filter frequencies from the airframe, check a config for
settings that cannot work, and read a blackbox log against all of it.

Everything except log analysis is standard library only.

## Status

Early days. The CLI dump parser is in; the airframe model, planner, review and
log analysis are on the way.
