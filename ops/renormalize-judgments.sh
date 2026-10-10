#!/bin/sh
# Every judgment normalized again from its stored XML (`normalize rechtspraak` over all), so it keeps its footnotes
# (props.footnotes), which `semantic rechtspraak` then reads. In slices of LIMIT judgments (default 90000, about 25
# minutes), each under the lock on its own so a poll can run in between, at night: from NOT_BEFORE (default 03) to
# NOT_AFTER (default 07), Europe/Amsterdam. The relink after it (relink-judgments.sh, or the weekly) links the
# citations of the footnotes.
# Goes on where it stopped (out/renormalize-judgments.after); stops at the first failure and says so through the alert.
D=$(cd "$(dirname "$0")" && pwd)
set -a && . /srv/lawgraph/scheduler.env && set +a
from=${NOT_BEFORE:-03}
to=${NOT_AFTER:-07}
night() { h=$(TZ=Europe/Amsterdam date +%H); [ "$h" -ge "$from" ] && [ "$h" -lt "$to" ]; }
STATE="$D/out/renormalize-judgments.after"
until [ "$(cat "$STATE" 2>/dev/null)" = done ]; do
  until night; do echo "$(date -u +%T) waiting for $from:00-$to:00 Europe/Amsterdam"; sleep 600; done
  echo "######## slice after $(cat "$STATE" 2>/dev/null || echo the start) start $(date -u +%T)"
  sh "$D/renormalize-judgments-slice.sh"
  rc=$?
  echo "######## slice rc $rc end $(date -u +%T)"
  if [ $rc -ne 0 ]; then
    [ -z "$LAWGRAPH_ALERT_COMMAND" ] || LAWGRAPH_ALERT_MESSAGE="lawgraph ops renormalize-judgments: a slice failed, rc $rc" sh -c "$LAWGRAPH_ALERT_COMMAND"
    exit $rc
  fi
done
echo "== all done $(date -u +%T)"
