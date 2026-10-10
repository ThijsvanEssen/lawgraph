#!/bin/sh
# Once after the deploy that brings the pages of the motions of the Eerste Kamer, at night: retrieve eerstekamer-motions
# (the page of every motion the votes name: some 700 pages at the interval of eerstekamer.nl), then normalize
# eerstekamer-motions (what each asks, its status and its signers on its Kamerstuk); ek-motions-counts.sql before and
# after; each step under the lock. Stops at the first failure and says so through the alert. After it, the daily run
# fetches the pages of the motions new votes name.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/ek-motions-steps.sh" || fail ek-motions-steps $?
