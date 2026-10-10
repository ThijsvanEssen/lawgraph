#!/bin/sh
# One slice of ek-motions.sh under the lock: 300 pages of motions not stored yet; when the retrieve logs none left, normalize
# eerstekamer-motions and writes "done" to out/ek-motions.state.
. "$(dirname "$0")/_steps.sh"
STATE="$OPS/out/ek-motions.state"
state=$(cat "$STATE" 2>/dev/null)
[ "$state" != done ] || { echo "== already done"; exit 0; }
[ -n "$state" ] || counts motions before ek-motions-counts.sql
echo started > "$STATE"
label="m${SLICE:-1}-retrieve-eerstekamer-motions"
step "$label" retrieve eerstekamer-motions --limit 300
left=$(sed -n 's/.*Eerste Kamer motion pages: .* \([0-9][0-9]*\) left after it.*/\1/p' "$OUT/$label.log" | tail -1)
[ -n "$left" ] || { echo "== no count of the pages left in $label.log"; exit 1; }
if [ "$left" -eq 0 ]; then
  step m-normalize-eerstekamer-motions normalize eerstekamer-motions
  echo done > "$STATE"
  counts motions after ek-motions-counts.sql
fi
echo "== slice ${SLICE:-1} done $(date -u +%T), pages left: $left"
