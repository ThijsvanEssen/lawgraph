#!/bin/sh
# Once after the deploy that brings the pages of the motions of the Eerste Kamer, at night: retrieve eerstekamer-motions
# (the page of every motion the votes name: some 700 pages at eerstekamer.nl's interval of 2 s, over half an hour) in
# slices of 300 pages, each under the lock on its own (a poll can run in between), until none is left; then normalize
# eerstekamer-motions (what each asks, its status and its signers on its Kamerstuk). ek-motions-counts.sql before and
# after. Waits for the night before every slice, so a slice past NOT_AFTER waits for the next night and goes on with
# the pages not stored yet. Stops at the first failure and says so through the alert. After it, the daily run fetches
# the pages of the motions new votes name.
. "$(dirname "$0")/_night.sh"
STATE="$D/out/ek-motions.state"
mkdir -p "$D/out"
n=0
while :; do
  wait_night
  n=$((n + 1))
  [ "$n" -le 20 ] || fail "slice limit" 1
  echo "######## slice $n $(date -u +%T)"
  SLICE=$n sh "$D/ek-motions-slice.sh" || fail "slice $n" $?
  [ "$(cat "$STATE" 2>/dev/null)" = done ] && break
done
echo "== all slices done $(date -u +%T)"
