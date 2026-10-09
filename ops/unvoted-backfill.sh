#!/bin/sh
# The Besluiten without a vote on amendments and motions, in two steps that each take the lock of the
# scheduled runs on their own, so a poll can run in between. Waits for the night: from NOT_BEFORE (default 03,
# after the nightly of 01:00) to NOT_AFTER (default 07), Europe/Amsterdam. Stops at the first failure and says so
# through the alert.
D=$(cd "$(dirname "$0")" && pwd)
set -a && . /srv/lawgraph/scheduler.env && set +a
from=${NOT_BEFORE:-03}
to=${NOT_AFTER:-07}
night() { h=$(TZ=Europe/Amsterdam date +%H); [ "$h" -ge "$from" ] && [ "$h" -lt "$to" ]; }
for s in unvoted-1-retrieve unvoted-2-normalize; do
  until night; do echo "$(date -u +%T) waiting for $from:00-$to:00 Europe/Amsterdam"; sleep 600; done
  echo "######## $s start $(date -u +%T)"
  sh "$D/$s.sh"
  rc=$?
  echo "######## $s rc $rc end $(date -u +%T)"
  if [ $rc -ne 0 ]; then
    [ -z "$LAWGRAPH_ALERT_COMMAND" ] || LAWGRAPH_ALERT_MESSAGE="lawgraph ops unvoted-backfill: $s failed, rc $rc" sh -c "$LAWGRAPH_ALERT_COMMAND"
    exit $rc
  fi
done
