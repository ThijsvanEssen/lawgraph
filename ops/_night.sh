# Sourced by a night backfill: `wait_night` waits until the hour is from NOT_BEFORE (default 03, after the
# nightly of 01:00) to NOT_AFTER (default 07), Europe/Amsterdam; `fail <steps> <rc>` says so through the alert, in
# plain Dutch from what the failed step left (out/<steps>/failed, see _steps.sh; `tell` of the app's scripts/_alert.sh),
# and exits. Sets D, the directory of ops/.
D=$(cd "$(dirname "$0")" && pwd)
APP=/srv/lawgraph/app
set -a && . /srv/lawgraph/scheduler.env && set +a
from=${NOT_BEFORE:-03}
to=${NOT_AFTER:-07}
wait_night() {
  until h=$(TZ=Europe/Amsterdam date +%H); [ "$h" -ge "$from" ] && [ "$h" -lt "$to" ]; do
    echo "$(date -u +%T) waiting for $from:00-$to:00 Europe/Amsterdam"; sleep 600
  done
}
fail() {
  { cat "$D/out/$1/failed" 2>/dev/null || printf 'failed\t%s\texit code %s\n' "$1" "$2"; } \
    | (cd "$APP" && . scripts/_alert.sh && tell ops "$(basename "$0" .sh)")
  exit "$2"
}
