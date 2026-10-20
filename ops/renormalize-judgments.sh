#!/bin/sh
# Every judgment normalized again from its stored XML (`normalize rechtspraak` over all), so it keeps its footnotes
# (props.footnotes), which `semantic rechtspraak` then reads. In slices of LIMIT judgments (default 90000, about 25
# minutes), each under the lock on its own so a poll can run in between, at night: from NOT_BEFORE (default 03) to
# NOT_AFTER (default 07), Europe/Amsterdam. The relink after it (relink-judgments.sh, or the weekly) links the
# citations of the footnotes.
# Goes on where it stopped (out/renormalize-judgments.after); stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
STATE="$D/out/renormalize-judgments.after"
until [ "$(cat "$STATE" 2>/dev/null)" = done ]; do
  wait_night
  echo "######## slice after $(cat "$STATE" 2>/dev/null || echo the start) start $(date -u +%T)"
  sh "$D/renormalize-judgments-slice.sh"
  rc=$?
  echo "######## slice rc $rc end $(date -u +%T)"
  [ $rc -eq 0 ] || fail renormalize-judgments-slice $rc
done
echo "== all done $(date -u +%T)"
