#!/bin/sh
# The article citations of every judgment linked again (`semantic rechtspraak` over all), so the laws the linker
# now knows by another name take their citations over: the code beside its versions (Rv), a title without its
# year (Vreemdelingenwet). In slices of LIMIT judgments (default 100000), each under the lock on its own so a
# poll can run in between, at night: from NOT_BEFORE (default 03) to NOT_AFTER (default 07), Europe/Amsterdam.
# Goes on where it stopped (out/relink-judgments.after); stops at the first failure and says so through the alert.
D=$(cd "$(dirname "$0")" && pwd)
set -a && . /srv/lawgraph/scheduler.env && set +a
from=${NOT_BEFORE:-03}
to=${NOT_AFTER:-07}
night() { h=$(TZ=Europe/Amsterdam date +%H); [ "$h" -ge "$from" ] && [ "$h" -lt "$to" ]; }
STATE="$D/out/relink-judgments.after"
until [ "$(cat "$STATE" 2>/dev/null)" = done ]; do
  until night; do echo "$(date -u +%T) waiting for $from:00-$to:00 Europe/Amsterdam"; sleep 600; done
  echo "######## slice after $(cat "$STATE" 2>/dev/null || echo the start) start $(date -u +%T)"
  sh "$D/relink-judgments-slice.sh"
  rc=$?
  echo "######## slice rc $rc end $(date -u +%T)"
  if [ $rc -ne 0 ]; then
    [ -z "$LAWGRAPH_ALERT_COMMAND" ] || LAWGRAPH_ALERT_MESSAGE="lawgraph ops relink-judgments: a slice failed, rc $rc" sh -c "$LAWGRAPH_ALERT_COMMAND"
    exit $rc
  fi
done
echo "== all done $(date -u +%T)"
