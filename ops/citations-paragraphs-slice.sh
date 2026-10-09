#!/bin/sh
# One slice of citations-paragraphs.sh under the lock: `semantic rechtspraak-citations` over the next judgments
# after the record key in out/citations-paragraphs.after (from the start without it); writes the key to go on
# after, or "done" when the slice read none. How many: out/citations-paragraphs.limit, else LIMIT (default
# 100000); a slice that took longer than 25 minutes sets the next one's to what fits in 20.
. "$(dirname "$0")/_steps.sh"
AFTER_FILE="$OPS/out/citations-paragraphs.after"
LIMIT_FILE="$OPS/out/citations-paragraphs.limit"
after=$(cat "$AFTER_FILE" 2>/dev/null)
[ "$after" != done ] || { echo "== already done"; exit 0; }
[ -n "$after" ] || counts paragraphs before citation-paragraphs-counts.sql
limit=$(cat "$LIMIT_FILE" 2>/dev/null)
limit=${limit:-${LIMIT:-100000}}
label="c${SLICE:-1}-semantic-rechtspraak-citations"
began=$(date +%s)
step "$label" semantic rechtspraak-citations ${after:+--after "$after"} --limit "$limit"
took=$(( $(date +%s) - began ))
if [ "$took" -gt 1500 ]; then
  limit=$(( limit * 1200 / took ))
  [ "$limit" -ge 1000 ] || limit=1000
  echo "$limit" > "$LIMIT_FILE"
  echo "== the slice took $took s: the next reads $limit judgments"
fi
next=$(sed -n 's/.*go on with --after \([^)]*\)).*/\1/p' "$OUT/$label.log" | tail -1)
if [ -z "$next" ] || [ "$next" = None ] || [ "$next" = "$after" ]; then
  echo done > "$AFTER_FILE"
  counts paragraphs after citation-paragraphs-counts.sql
else
  echo "$next" > "$AFTER_FILE"
fi
echo "== slice ${SLICE:-1} done $(date -u +%T), next after: $(cat "$AFTER_FILE")"
