#!/bin/sh
# `semantic rechtspraak-referrals` over all, once, at night after the nightly: the step of the weekly run of 25 Oct
# that failed on the deadlock of ensure_schema at connect (#970, fixed in 0.80.10). Minutes. `expand-graph` of that
# weekly run is left to the next one (1 Nov): it reads these edges (the rulings that answer no decision, retrieve
# --mode gaps) but runs for hours. Stops at a failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/rechtspraak-referrals-steps.sh" || fail rechtspraak-referrals-steps $?
