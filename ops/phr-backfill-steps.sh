#!/bin/sh
# The steps of phr-backfill.sh, under the lock: every conclusion of the Parket the index lists (35 pages) and is not
# stored, then normalize what that retrieve stored. phr-gap-counts.sql before and after.
# A hard limit of 20 minutes a step (`timeout`; exit 124 fails the step): a run that stops goes on where it was, and
# normalizes from the start of the first run (out/phr-backfill-steps/started, removed when all is done). The
# relations (semantic rechtspraak-conclusions, ADVISES_ON) and the feed are left to the next nightly run.
. "$(dirname "$0")/_steps.sh"
L="timeout 20m $L"
[ -s "$OUT/started" ] || date -u +%Y-%m-%dT%H:%M:%S+00:00 > "$OUT/started"
started=$(cat "$OUT/started")
echo "== normalize since $started"
counts phr before phr-gap-counts.sql
step 1-retrieve retrieve rechtspraak --court PHR --mode full
step 2-normalize normalize rechtspraak --since "$started"
counts phr after phr-gap-counts.sql
rm -f "$OUT/started"
echo "== all done $(date -u +%T)"
