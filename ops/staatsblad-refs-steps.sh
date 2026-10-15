#!/bin/sh
# The steps of staatsblad-refs.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
counts refs before staatsblad-refs-counts.sql
echo "== r1-fill start $(date -u +%T)"
.venv/bin/python "$OPS/staatsblad-refs.py" > "$OUT/r1-fill.log" 2>&1 || { tail -5 "$OUT/r1-fill.log"; exit 1; }
tail -1 "$OUT/r1-fill.log"
step r2-retrieve-staatsblad retrieve staatsblad
counts refs after staatsblad-refs-counts.sql
echo "== all done $(date -u +%T)"
