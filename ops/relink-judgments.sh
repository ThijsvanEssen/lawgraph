#!/bin/sh
# The article citations of every judgment linked again (`semantic rechtspraak` over all), so the laws the linker
# now knows by another name take their citations over: the code beside its versions (Rv), a title without its
# year (Vreemdelingenwet). In slices of LIMIT judgments (default 100000), each under the lock on its own so a
# poll can run in between, at night: from NOT_BEFORE (default 03) to NOT_AFTER (default 07), Europe/Amsterdam.
# Goes on where it stopped (out/relink-judgments.after); stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
STATE="$D/out/relink-judgments.after"
until [ "$(cat "$STATE" 2>/dev/null)" = done ]; do
  wait_night
  echo "######## slice after $(cat "$STATE" 2>/dev/null || echo the start) start $(date -u +%T)"
  sh "$D/relink-judgments-slice.sh"
  rc=$?
  echo "######## slice rc $rc end $(date -u +%T)"
  [ $rc -eq 0 ] || fail relink-judgments-slice $rc
done
echo "== all done $(date -u +%T)"
