#!/bin/sh
# The citations between judgments read again (`semantic rechtspraak-citations` over all), so an LJN named on its
# own ("LJN BK9271", how a decision was cited before 2013) cites the judgment whose ECLI has it, and each citation
# keeps the numbers of the paragraphs that name it (meta.paragraphs, #419). In slices of LIMIT
# judgments (default 150000, about 20 minutes), each under the lock on its own so a poll can run in between, at
# night: from NOT_BEFORE (default 03) to NOT_AFTER (default 07), Europe/Amsterdam.
# Goes on where it stopped (out/relink-citations.after); stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
STATE="$D/out/relink-citations.after"
until [ "$(cat "$STATE" 2>/dev/null)" = done ]; do
  wait_night
  echo "######## slice after $(cat "$STATE" 2>/dev/null || echo the start) start $(date -u +%T)"
  sh "$D/relink-citations-slice.sh"
  rc=$?
  echo "######## slice rc $rc end $(date -u +%T)"
  [ $rc -eq 0 ] || fail relink-citations-slice $rc
done
echo "== all done $(date -u +%T)"
