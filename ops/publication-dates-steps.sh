#!/bin/sh
# The steps of publication-dates.sh, under the lock: normalize staatscourant and staatsblad over every stored record
# (no --since: the records do not change, only what normalize reads of their meta), so each document gets the day of
# publication the SRU gave (`published`, written by the creators step of retrieve). publication-dates-counts.sql
# before and after.
. "$(dirname "$0")/_steps.sh"
counts dates before publication-dates-counts.sql
step 1-normalize-staatscourant normalize staatscourant
step 2-normalize-staatsblad normalize staatsblad
counts dates after publication-dates-counts.sql
echo "== all done $(date -u +%T)"
