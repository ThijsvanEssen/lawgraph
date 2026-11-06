#!/bin/sh
# One slice of renormalize-judgments-head.sh, under the lock: `normalize rechtspraak` over the next LIMIT (default 30000,
# about 15 minutes) judgment records past the key out/renormalize-judgments-head.after holds, from the start when it
# holds none. The pass is done once the slice went past UNTIL: the key where the renormalize pass of renormalize-rvs.sh
# went on with 0.80.29 (31 Oct), the first release that writes props.law_references (#1084, 0.80.27).
. "$(dirname "$0")/_steps.sh"
UNTIL=0e807740ad8216ac8a8032d4087735bbcd08376c
STATE="$OPS/out/renormalize-judgments-head.after"
after=$(cat "$STATE" 2>/dev/null)
[ "$after" = done ] && { echo "== the head is done; remove $STATE for a new one"; exit 0; }
label="h-slice-$(date -u +%Y%m%dT%H%M%S)"
step "$label" normalize rechtspraak ${after:+--after "$after"} --limit "${LIMIT:-30000}"
next=$(sed -n 's/.*go on with --after \([^)]*\)).*/\1/p' "$OUT/$label.log" | tail -1)
if [ -z "$next" ] || [ "$next" = None ] || awk -v a="$next" -v b="$UNTIL" 'BEGIN { exit !(a "" > b "") }'; then
  echo done > "$STATE"
  echo "== the head is done (last key ${next:-none})"
else
  echo "$next" > "$STATE"
  echo "== next slice after $next"
fi
