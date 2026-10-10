#!/bin/sh
# Once after the deploy that brings the pages of the members of the Eerste Kamer, at night: retrieve eerstekamer-persons
# (the page of every sitting member and of every person a change since 2003 links: a few hundred pages at the
# interval of eerstekamer.nl), then normalize eerstekamer-persons (their periods in its factions); ek-persons-counts.sql
# before and after; each step under the lock. Stops at the first failure and says so through the alert. After it, the
# daily run fetches the pages a new change links, the weekly every sitting member's again.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/ek-persons-steps.sh" || fail ek-persons-steps $?
