#!/bin/sh
# Once, after the nightly (03:00-07:00 Europe/Amsterdam): `semantic bwb` over every toestand, without --since, for the
# REFERS_TO of an article to a whole law (#1111, about 13 minutes on 1 Nov). The weekly does the same on Sunday, so this
# is only for when that cannot wait. Not in one night with backfill-0.80.30-derive.sh.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/backfill-0.80.30-bwb-steps.sh" || fail backfill-0.80.30-bwb-steps $?
