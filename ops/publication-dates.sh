#!/bin/sh
# At night, once after the deploy of the release that reads the day of publication of a Staatsblad AMvB and a
# Staatscourant regulation from the meta of its record: their documents again (publication-dates-steps.sh, one lock,
# a few minutes). Stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/publication-dates-steps.sh" || fail publication-dates-steps $?
