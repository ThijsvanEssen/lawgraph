#!/bin/sh
# One slice of bwb-definitions.sh under the lock: 5,000 regulations after the BWB id in out/bwb-definitions.after
# (from the start without it); writes the id to go on after, or "done" when the slice read none.
. "$(dirname "$0")/_steps.sh"
AFTER_FILE="$OPS/out/bwb-definitions.after"
after=$(cat "$AFTER_FILE" 2>/dev/null)
[ "$after" != done ] || { echo "== already done"; exit 0; }
[ -n "$after" ] || counts definitions before definitions-counts.sql
label="d${SLICE:-1}-semantic-bwb-definitions"
if [ -n "$after" ]; then
  step "$label" semantic bwb-definitions --after "$after" --limit 5000
else
  step "$label" semantic bwb-definitions --limit 5000
fi
next=$(sed -n 's/.*go on with --after \([A-Za-z0-9_]*\)).*/\1/p' "$OUT/$label.log" | tail -1)
if [ -z "$next" ] || [ "$next" = None ] || [ "$next" = "$after" ]; then
  echo done > "$AFTER_FILE"
  counts definitions after definitions-counts.sql
else
  echo "$next" > "$AFTER_FILE"
fi
echo "== slice ${SLICE:-1} done $(date -u +%T), next after: $(cat "$AFTER_FILE")"
