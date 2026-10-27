#!/bin/sh
# The first build of the steps between sources after the deploy of 0.80.13 (#990), once: until then /api/chains
# answers 503. Waits for the API to report 0.80.13, then the step through scripts/step.sh, which takes the lock of
# the scheduled runs for that step only (rc 75: the lock is held, tried again after 60 s). From then on the nightly
# builds them (semantic all).
#   1  semantic graph-steps   source_steps and source_step_nodes, built beside the tables and put in their place
set -a && . /srv/lawgraph/scheduler.env && set +a
cd /srv/lawgraph/app || exit 1
log() { echo "$(date -u +%FT%TZ) $*"; }
step() { label=$1; shift; while :; do sh scripts/step.sh "$@" > "/srv/lawgraph/ops/after-0.80.13.step.log" 2>&1; rc=$?
    grep -E "Done in|Failed|rc |problem" "/srv/lawgraph/ops/after-0.80.13.step.log" | tail -6
    [ $rc -eq 75 ] && { sleep 60; continue; }; log "$label rc $rc"; return $rc; done; }
until [ "$(curl -s http://127.0.0.1:8000/api/health | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')" = "0.80.13" ]; do sleep 30; done
log "API 0.80.13"
step "1 semantic graph-steps" semantic graph-steps
log "all done"
