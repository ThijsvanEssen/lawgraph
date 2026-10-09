#!/bin/sh
# #413 at night: every stored Staatsblad note read again (normalize staatsblad without --since, 9,875 XMLs,
# minutes), then semantic staatsblad (EXPLAINS by bwb_id, then by title), with staatsblad-counts.sql before
# and after; one lock for the two steps. Stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/staatsblad-notes-steps.sh" || fail staatsblad-notes-steps $?
