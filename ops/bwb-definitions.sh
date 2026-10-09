#!/bin/sh
# #414 at night: semantic bwb-definitions in slices of 5,000 regulations, each slice under the lock on its own
# (a poll can run in between), each going on --after the last BWB id the slice before logged ("the last read was
# BWBR… (go on with --after BWBR…)"), until a slice reads none. definitions-counts.sql before and after. Waits
# for the night before every slice, so a slice past NOT_AFTER waits for the next night and goes on from
# out/bwb-definitions.after. Stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
AFTER_FILE="$D/out/bwb-definitions.after"
mkdir -p "$D/out"
n=0
while :; do
  wait_night
  n=$((n + 1))
  [ "$n" -le 200 ] || fail "slice limit" 1
  echo "######## slice $n after $(cat "$AFTER_FILE" 2>/dev/null || echo start) $(date -u +%T)"
  SLICE=$n sh "$D/bwb-definitions-slice.sh" || fail "slice $n" $?
  after=$(cat "$AFTER_FILE" 2>/dev/null)
  [ "$after" = done ] && break
done
echo "== all slices done $(date -u +%T)"
