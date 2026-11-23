#!/bin/sh
# One slice of renormalize-bwb.sh: `normalize <NORMALIZE>` (default bwb; bwb-history takes whole regulations) over
# the next toestanden past the key out/<PASS>.after holds (PASS default renormalize-bwb), under the lock. How many: out/<PASS>.limit, else LIMIT (default 15000). A slice that
# took longer than 25 minutes sets the next one's to what fits in 20. With COUNTS (default bwb-preamble-counts.sql,
# empty for none) the first slice counts before and the slice that reaches the end after; that slice marks the pass
# done. A slice that ends on the key it started past (it goes nowhere) fails.
. "$(dirname "$0")/_steps.sh"
PASS=${PASS:-renormalize-bwb}
COUNTS=${COUNTS-bwb-preamble-counts.sql}
STATE="$OPS/out/$PASS.after"
after=$(cat "$STATE" 2>/dev/null)
[ "$after" = "done" ] && { echo "== the pass is done; remove $STATE for a new one"; exit 0; }
[ -n "$after" ] || [ -z "$COUNTS" ] || counts preamble before "$COUNTS"
LIMITS="$OPS/out/$PASS.limit"
limit=$(cat "$LIMITS" 2>/dev/null)
limit=${limit:-${LIMIT:-15000}}
label="b-slice-$(date -u +%Y%m%dT%H%M%S)"
began=$(date +%s)
step "$label" normalize "${NORMALIZE:-bwb}" ${after:+--after "$after"} --limit "$limit"
took=$(( $(date +%s) - began ))
done_now=$(sed -n 's/.*Normalized \([0-9]*\) BWB articles for \([0-9]*\) instruments.*/\2 toestanden, \1 articles/p' "$OUT/$label.log" | tail -1)
echo "== slice after ${after:-the start}: ${done_now:-no count in the log} in $took s"
if [ "$took" -gt 1500 ]; then
  limit=$(( limit * 1200 / took ))
  [ "$limit" -ge 1000 ] || limit=1000
  echo "$limit" > "$LIMITS"
  echo "== the slice took $took s: the next reads $limit toestanden"
fi
if grep -q 'the end, nothing to go on' "$OUT/$label.log"; then
  echo "done" > "$STATE"
  [ -z "$COUNTS" ] || counts preamble after "$COUNTS"
  echo "== the pass is done"
  exit 0
fi
next=$(sed -n 's/.*go on with --after \([^)]*\)).*/\1/p' "$OUT/$label.log" | tail -1)
if [ -z "$next" ] || [ "$next" = None ] || [ "$next" = "$after" ]; then
  printf 'failed\tlawgraph normalize %s --after %s\tthe slice goes nowhere (next: %s)\n' "${NORMALIZE:-bwb}" "$after" "${next:-none}" > "$OUT/failed"
  echo "== the slice goes nowhere: after '$after', next '${next:-none}'; stopped"
  exit 1
fi
echo "$next" > "$STATE"
echo "== next slice after $next"
