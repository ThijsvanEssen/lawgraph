#!/bin/sh
# One slice of authored-dates.sh: `semantic graph-light --authored-dates` over the next members past the id
# out/authored-dates.after holds, under the lock. How many: out/authored-dates.limit, else LIMIT (default 500). A slice
# that took longer than 25 minutes sets the next one's to what fits in 20. The first slice counts before, the slice
# that reads nothing counts after and marks the pass done.
. "$(dirname "$0")/_steps.sh"
STATE="$OPS/out/authored-dates.after"
after=$(cat "$STATE" 2>/dev/null)
[ "$after" = done ] && { echo "== the pass is done; remove $STATE for a new one"; exit 0; }
[ -n "$after" ] || counts dated before authored-dates-counts.sql
LIMITS="$OPS/out/authored-dates.limit"
limit=$(cat "$LIMITS" 2>/dev/null)
limit=${limit:-${LIMIT:-500}}
label="ad-slice-$(date -u +%Y%m%dT%H%M%S)"
began=$(date +%s)
step "$label" semantic graph-light --authored-dates ${after:+--after "$after"} --limit "$limit"
took=$(( $(date +%s) - began ))
if [ "$took" -gt 1500 ]; then
  limit=$(( limit * 1200 / took ))
  [ "$limit" -ge 10 ] || limit=10
  echo "$limit" > "$LIMITS"
  echo "== the slice took $took s: the next reads $limit members"
fi
next=$(sed -n 's/.*go on with --after \([^)]*\)).*/\1/p' "$OUT/$label.log" | tail -1)
if [ -z "$next" ]; then
  echo done > "$STATE"
  counts dated after authored-dates-counts.sql
  echo "== the pass is done"
else
  echo "$next" > "$STATE"
  echo "== next slice after $next"
fi
