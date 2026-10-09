#!/bin/sh
# After the deploy of 0.79.32: tk-dictum, post-0.79.29 and post-0.79.30, one after another, each under the
# lock on its own (a poll can run in between). Stops at the first failure and says so through the alert.
D=$(cd "$(dirname "$0")" && pwd)
set -a && . /srv/lawgraph/scheduler.env && set +a
for s in tk-dictum post-0.79.29 post-0.79.30; do
  echo "######## $s start $(date -u +%T)"
  sh "$D/$s.sh"
  rc=$?
  echo "######## $s rc $rc end $(date -u +%T)"
  if [ $rc -ne 0 ]; then
    [ -z "$LAWGRAPH_ALERT_COMMAND" ] || LAWGRAPH_ALERT_MESSAGE="lawgraph ops chain-rest: $s failed, rc $rc" sh -c "$LAWGRAPH_ALERT_COMMAND"
    exit $rc
  fi
done
