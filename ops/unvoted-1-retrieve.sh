#!/bin/sh
# Backfill step 1 of 2 (unvoted-backfill.sh): every Besluit without a vote on an amendment or a motion
# (withdrawn, postponed, held, lapsed: about 25,000). Measured on the OData: about 100 pages of 250 at 2 to 7 s.
# Keeps the moment it began for the normalize of step 2.
. "$(dirname "$0")/_steps.sh"
counts unvoted before unvoted-counts.sql
since=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
echo "$since" > "$OPS/out/unvoted-backfill.since"
echo "== since $since (for unvoted-2-normalize.sh)"
step u1-retrieve-tk-dossiers-unvoted retrieve tk-dossiers --mode unvoted
echo "== all done $(date -u +%T)"
