#!/bin/sh
# Once, after the nightly (03:00-07:00 Europe/Amsterdam): the trigger of instruments changed in 0.80.30 (#1108), so its
# digest did. `semantic graph-derive instruments` writes every row of the table again, which raises the data version.
# Not in one night with backfill-0.80.30-bwb.sh.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/backfill-0.80.30-derive-steps.sh" || fail backfill-0.80.30-derive-steps $?
