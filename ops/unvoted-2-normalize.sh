#!/bin/sh
# Backfill step 2 of 2: the Besluit records stored since step 1 began, normalized: a decision on its case
# without an outcome (passed null), its decision_kind the BesluitSoort.
. "$(dirname "$0")/_steps.sh"
since=$(cat "$OPS/out/unvoted-backfill.since" 2>/dev/null)
[ -n "$since" ] || { echo "== no out/unvoted-backfill.since: run unvoted-1-retrieve.sh first"; exit 1; }
echo "== since $since"
step u2-normalize-tk-dossiers normalize tk-dossiers --since "$since"
counts unvoted after unvoted-counts.sql
echo "== all done $(date -u +%T)"
