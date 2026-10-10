#!/bin/sh
# The citations between judgments read again (`semantic rechtspraak-citations` over all), so an LJN named on its
# own ("LJN BK9271", how a decision was cited before 2013) cites the judgment whose ECLI has it, and each citation
# keeps the numbers of the paragraphs that name it (meta.paragraphs, #419). In slices of LIMIT
# judgments (default 150000, about 20 minutes), each under the lock on its own so a poll can run in between, at
# night: from NOT_BEFORE (default 03) to NOT_AFTER (default 07), Europe/Amsterdam.
# Goes on where it stopped (out/relink-citations.after); stops at the first failure and says so through the alert.
D=$(cd "$(dirname "$0")" && pwd)
set -a && . /srv/lawgraph/scheduler.env && set +a
from=${NOT_BEFORE:-03}
to=${NOT_AFTER:-07}
night() { h=$(TZ=Europe/Amsterdam date +%H); [ "$h" -ge "$from" ] && [ "$h" -lt "$to" ]; }
STATE="$D/out/relink-citations.after"
until [ "$(cat "$STATE" 2>/dev/null)" = done ]; do
  until night; do echo "$(date -u +%T) waiting for $from:00-$to:00 Europe/Amsterdam"; sleep 600; done
  echo "######## slice after $(cat "$STATE" 2>/dev/null || echo the start) start $(date -u +%T)"
  sh "$D/relink-citations-slice.sh"
  rc=$?
  echo "######## slice rc $rc end $(date -u +%T)"
  if [ $rc -ne 0 ]; then
    [ -z "$LAWGRAPH_ALERT_COMMAND" ] || LAWGRAPH_ALERT_MESSAGE="lawgraph ops relink-citations: a slice failed, rc $rc" sh -c "$LAWGRAPH_ALERT_COMMAND"
    exit $rc
  fi
done
echo "== all done $(date -u +%T)"
