#!/bin/sh
# One night of the backfill of the XML of the Tweede Kamer papers (tk-backfill-steps.sh), after the nightly (03:00-07:00
# Europe/Amsterdam). Run it once a night until `lawgraph gaps` has no Kamerstukken without XML left (about 27 nights for
# 96,000 papers). Stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/tk-backfill-steps.sh" || fail tk-backfill-steps $?
