#!/bin/sh
# Once after the deploy that brings the dates of lg_authored: `semantic graph-light --authored-dates` keeps the date
# of the paper or case and the capacity of every signature kept before the triggers did, in slices of LIMIT members
# (default 500), each under the lock on its own so a poll can run in between, at night: from NOT_BEFORE (default 03)
# to NOT_AFTER (default 07), Europe/Amsterdam. The last slice notes the table dated (lg_authored_dated), from when the
# counts of a cabinet's members read its index. Goes on where it stopped (out/authored-dates.after); stops at the
# first failure and says so through the alert. Needs the index lg_authored_member_date built beforehand
# (CREATE INDEX CONCURRENTLY, docs/operations.md).
D=$(cd "$(dirname "$0")" && pwd)
set -a && . /srv/lawgraph/scheduler.env && set +a
from=${NOT_BEFORE:-03}
to=${NOT_AFTER:-07}
night() { h=$(TZ=Europe/Amsterdam date +%H); [ "$h" -ge "$from" ] && [ "$h" -lt "$to" ]; }
STATE="$D/out/authored-dates.after"
until [ "$(cat "$STATE" 2>/dev/null)" = done ]; do
  until night; do echo "$(date -u +%T) waiting for $from:00-$to:00 Europe/Amsterdam"; sleep 600; done
  echo "######## slice after $(cat "$STATE" 2>/dev/null || echo the start) start $(date -u +%T)"
  sh "$D/authored-dates-slice.sh"
  rc=$?
  echo "######## slice rc $rc end $(date -u +%T)"
  if [ $rc -ne 0 ]; then
    [ -z "$LAWGRAPH_ALERT_COMMAND" ] || LAWGRAPH_ALERT_MESSAGE="lawgraph ops authored-dates: a slice failed, rc $rc" sh -c "$LAWGRAPH_ALERT_COMMAND"
    exit $rc
  fi
done
echo "== all done $(date -u +%T)"
