#!/bin/sh
# One slice of relink-judgments.sh: `semantic rechtspraak` over the next LIMIT judgments (default 100000) past
# the key out/relink-judgments.after holds, under the lock. The first slice counts before, the slice that
# reads nothing counts after and marks the pass done.
. "$(dirname "$0")/_steps.sh"
STATE="$OPS/out/relink-judgments.after"
after=$(cat "$STATE" 2>/dev/null)
[ "$after" = done ] && { echo "== the pass is done; remove $STATE for a new one"; exit 0; }
[ -n "$after" ] || counts relink before unresolved-laws-check.sql
label="r-slice-$(date -u +%Y%m%dT%H%M%S)"
step "$label" semantic rechtspraak ${after:+--after "$after"} --limit "${LIMIT:-100000}"
next=$(sed -n 's/.*go on with --after \([^)]*\)).*/\1/p' "$OUT/$label.log" | tail -1)
if [ -z "$next" ] || [ "$next" = None ]; then
  echo done > "$STATE"
  counts relink after unresolved-laws-check.sql
  counts aliases after alias-claims-counts.sql
  echo "== the pass is done"
else
  echo "$next" > "$STATE"
  echo "== next slice after $next"
fi
