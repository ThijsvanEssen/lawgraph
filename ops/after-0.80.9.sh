#!/bin/sh
# The runs after the deploy of 0.80.9, once. Waits for the API to report 0.80.9, then each step through
# scripts/step.sh, which takes the lock of the scheduled runs for that step only (rc 75: the lock is held, tried
# again after 60 s). Step output goes to a file, never through $(...).
#   1  semantic bwb-implements   IMPLEMENTS for /surroundings and /delegated (#956)
#   2  semantic tk               full, the Kamerstuk references without the VVD law link (#954) and offsets (#954)
#   3  API restart               the caches of #956 start from the new edges
set -a && . /srv/lawgraph/scheduler.env && set +a
cd /srv/lawgraph/app || exit 1
log() { echo "$(date -u +%FT%TZ) $*"; }
step() { label=$1; shift; while :; do sh scripts/step.sh "$@" > "/srv/lawgraph/ops/after-0.80.9.step.log" 2>&1; rc=$?
    grep -E "Done in|Failed|rc |problem" "/srv/lawgraph/ops/after-0.80.9.step.log" | tail -6
    [ $rc -eq 75 ] && { sleep 60; continue; }; log "$label rc $rc"; return $rc; done; }
until [ "$(curl -s http://127.0.0.1:8000/api/health | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')" = "0.80.9" ]; do sleep 30; done
log "API 0.80.9"
step "1 semantic bwb-implements" semantic bwb-implements || log "1 failed, going on"
step "2 semantic tk (full)" semantic tk || log "2 failed, going on"
sudo -n systemctl restart lawgraph-api < /dev/null && log "3 API restarted" || log "3 restart failed"
log "all done"
