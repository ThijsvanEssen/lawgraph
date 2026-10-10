#!/bin/sh
# One slice of renormalize-judgments.sh: `normalize rechtspraak` over the next judgment records past the key
# out/renormalize-judgments.after holds, under the lock. How many: out/renormalize-judgments.limit, else LIMIT (default
# 90000). A slice that took longer than 25 minutes sets the next one's to what fits in 20. The first slice
# counts before, the slice that reads nothing counts after and marks the pass done.
. "$(dirname "$0")/_steps.sh"
STATE="$OPS/out/renormalize-judgments.after"
after=$(cat "$STATE" 2>/dev/null)
[ "$after" = done ] && { echo "== the pass is done; remove $STATE for a new one"; exit 0; }
[ -n "$after" ] || counts footnotes before judgment-footnotes-counts.sql
LIMITS="$OPS/out/renormalize-judgments.limit"
limit=$(cat "$LIMITS" 2>/dev/null)
limit=${limit:-${LIMIT:-90000}}
label="n-slice-$(date -u +%Y%m%dT%H%M%S)"
began=$(date +%s)
step "$label" normalize rechtspraak ${after:+--after "$after"} --limit "$limit"
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
  counts footnotes after judgment-footnotes-counts.sql
  echo "== the pass is done"
else
  echo "$next" > "$STATE"
  echo "== next slice after $next"
fi
