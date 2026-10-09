#!/bin/sh
# #378 backfill, step 2 of 3: the Zaak records stored since step 1 began, normalized: props.replaces_cases.
. "$(dirname "$0")/_steps.sh"
since=$(cat "$OPS/out/revises-backfill.since" 2>/dev/null)
[ -n "$since" ] || { echo "== no out/revises-backfill.since: run revises-1-retrieve.sh first"; exit 1; }
echo "== since $since"
step r2-normalize-tk normalize tk --since "$since"
echo "== all done $(date -u +%T)"
