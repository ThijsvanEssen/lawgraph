#!/bin/sh
# Once, after the nightly (03:00-07:00 Europe/Amsterdam): the name of each bill of the Eerste Kamer (#1109), from the
# whole list of bills: the nightly reads only the first pages of that list.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/backfill-0.80.30-bills-steps.sh" || fail backfill-0.80.30-bills-steps $?
