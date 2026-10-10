#!/bin/sh
# One slice of relink-citations.sh: `semantic rechtspraak-citations` over the next judgments past the key
# out/relink-citations.after holds, under the lock. How many: out/relink-citations.limit, else LIMIT (default
# 150000). A slice that took longer than 25 minutes sets the next one's to what fits in 20. The first slice
# counts before, the slice that reads nothing counts after and marks the pass done.
. "$(dirname "$0")/_steps.sh"
STATE="$OPS/out/relink-citations.after"
after=$(cat "$STATE" 2>/dev/null)
[ "$after" = done ] && { echo "== the pass is done; remove $STATE for a new one"; exit 0; }
[ -n "$after" ] || { counts ljn before ljn-citations-counts.sql; counts paragraphs before citation-paragraphs-counts.sql; }
LIMITS="$OPS/out/relink-citations.limit"
limit=$(cat "$LIMITS" 2>/dev/null)
limit=${limit:-${LIMIT:-150000}}
label="c-slice-$(date -u +%Y%m%dT%H%M%S)"
began=$(date +%s)
step "$label" semantic rechtspraak-citations ${after:+--after "$after"} --limit "$limit"
took=$(( $(date +%s) - began ))
if [ "$took" -gt 1500 ]; then
  limit=$(( limit * 1200 / took ))
  [ "$limit" -ge 1000 ] || limit=1000
  echo "$limit" > "$LIMITS"
  echo "== the slice took $took s: the next reads $limit judgments"
fi
next=$(sed -n 's/.*go on with --after \([^)]*\)).*/\1/p' "$OUT/$label.log" | tail -1)
if [ -z "$next" ] || [ "$next" = None ]; then
  echo done > "$STATE"
  counts ljn after ljn-citations-counts.sql
  counts paragraphs after citation-paragraphs-counts.sql
  echo "== the pass is done"
else
  echo "$next" > "$STATE"
  echo "== next slice after $next"
fi
