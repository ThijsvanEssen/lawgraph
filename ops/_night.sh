# Sourced by a night backfill: `wait_night` waits until the hour is from NOT_BEFORE (default 03, after the
# nightly of 01:00) to NOT_AFTER (default 07), Europe/Amsterdam; `fail <steps> <rc>` says so through the alert, with
# the reason the failed step left (out/<steps>/failed, see _steps.sh) and the log, and exits. Sets D, the directory of
# ops/.
D=$(cd "$(dirname "$0")" && pwd)
set -a && . /srv/lawgraph/scheduler.env && set +a
from=${NOT_BEFORE:-03}
to=${NOT_AFTER:-07}
wait_night() {
  until h=$(TZ=Europe/Amsterdam date +%H); [ "$h" -ge "$from" ] && [ "$h" -lt "$to" ]; do
    echo "$(date -u +%T) waiting for $from:00-$to:00 Europe/Amsterdam"; sleep 600
  done
}
fail() {
  why=$(cat "$D/out/$1/failed" 2>/dev/null)
  [ -z "$LAWGRAPH_ALERT_COMMAND" ] || LAWGRAPH_ALERT_MESSAGE="lawgraph ops $(basename "$0" .sh): $1 failed, rc $2${why:+: $why} (log: $D/$(basename "$0" .sh).log)" sh -c "$LAWGRAPH_ALERT_COMMAND"
  exit "$2"
}
