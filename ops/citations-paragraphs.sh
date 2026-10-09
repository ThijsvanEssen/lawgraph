#!/bin/sh
# #419 at night, once: `semantic rechtspraak-citations` over every judgment in slices, so each citation between
# judgments keeps the numbers of the paragraphs that name it (meta.paragraphs); the weekly run leaves this step to
# the daily one. Each slice under the lock on its own (a poll can run in between), going on --after the record
# key the slice before logged, until a slice reads none. citation-paragraphs-counts.sql before and after. Waits
# for the night before every slice, so a slice past NOT_AFTER waits for the next night and goes on from
# out/citations-paragraphs.after. Stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
AFTER_FILE="$D/out/citations-paragraphs.after"
mkdir -p "$D/out"
n=0
while :; do
  wait_night
  n=$((n + 1))
  [ "$n" -le 200 ] || fail "slice limit" 1
  echo "######## slice $n after $(cat "$AFTER_FILE" 2>/dev/null || echo start) $(date -u +%T)"
  SLICE=$n sh "$D/citations-paragraphs-slice.sh" || fail "slice $n" $?
  [ "$(cat "$AFTER_FILE" 2>/dev/null)" = done ] && break
done
echo "== all slices done $(date -u +%T)"
