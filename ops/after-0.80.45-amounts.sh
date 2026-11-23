#!/bin/sh
# One slice of step 3 of after-0.80.45.sh, under the lock: `semantic bwb-amounts` over the next AMOUNTS_SLICE
# (default 5000) regulations past the BWB id out/after-0.80.45-amounts.after holds. A slice that reads fewer than that
# reached the end and marks the pass done; one that ends on the id it started past fails.
. "$(dirname "$0")/_steps.sh"
STATE="$OPS/out/after-0.80.45-amounts.after"
after=$(cat "$STATE" 2>/dev/null)
[ "$after" = "done" ] && { echo "== the pass is done"; exit 0; }
limit=${AMOUNTS_SLICE:-5000}
label="amounts-$(date -u +%Y%m%dT%H%M%S)"
step "$label" semantic bwb-amounts ${after:+--after "$after"} --limit "$limit"
read_now=$(sed -n 's/.*Amounts: \([0-9]*\) regulations read.*/\1/p' "$OUT/$label.log" | tail -1)
next=$(sed -n 's/.*go on with --after \([^)]*\)).*/\1/p' "$OUT/$label.log" | tail -1)
echo "== slice after ${after:-the start}: ${read_now:-no count in the log} regulations, last $next"
if [ -n "$read_now" ] && [ "$read_now" -lt "$limit" ]; then
  echo "done" > "$STATE"
  echo "== the pass is done"
  exit 0
fi
if [ -z "$next" ] || [ "$next" = None ] || [ "$next" = "$after" ]; then
  printf 'failed\tlawgraph semantic bwb-amounts --after %s\tthe slice goes nowhere (next: %s)\n' "$after" "${next:-none}" > "$OUT/failed"
  echo "== the slice goes nowhere: after '$after', next '${next:-none}'; stopped"
  exit 1
fi
echo "$next" > "$STATE"
echo "== next slice after $next"
