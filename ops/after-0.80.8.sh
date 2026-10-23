#!/bin/sh
# The runs after the deploy of 0.80.8, once (go Thijs 23 Oct: 0.80.7 and 0.80.8 in one release, P14 stopped and
# taken in here). Waits for the API to report 0.80.8, then each step through scripts/step.sh, which takes the lock
# of the scheduled runs for that step only (rc 75: the lock is held, tried again after 60 s). Fast, visible steps first.
#   1  semantic bwb-amendments           COMMENCES (#927)
#   2  semantic tk-faction-succession    CONTINUES between factions (#934)
#   3  normalize bwb                     ministry from the WTI (#931), basis_preamble (#943), full
#   4  semantic graph-derive instruments digest with the ministry (#931)
#   5  semantic bwb-grondslagen          basis from the "Gelet op" text (#943)
#   6  semantic tooi-ministries          ministries as nodes, LED_BY/SERVED_IN/CONTINUES (#936)
#   7  sitemaps                          readable paths incl. /ministeries (#936)
#   8  semantic graph-light --only cited-by --all   lg_cited_by.areas (#930), then the old index dropped
#   9  normalize tk-content, semantic graph-light, normalize tk-dossiers, normalize eurlex, normalize rijksoverheid
#      (the runs of P14 for 0.80.6: #922, #923)
set -a && . /srv/lawgraph/scheduler.env && set +a
cd /srv/lawgraph/app || exit 1
log() { echo "$(date -u +%FT%TZ) $*"; }
step() { label=$1; shift; while :; do sh scripts/step.sh "$@" > "/srv/lawgraph/ops/after-0.80.8.step.log" 2>&1; rc=$?
    grep -E "Done in|Failed|rc |problem" "/srv/lawgraph/ops/after-0.80.8.step.log" | tail -6
    [ $rc -eq 75 ] && { sleep 60; continue; }; log "$label rc $rc"; return $rc; done; }
until [ "$(curl -s http://127.0.0.1:8000/api/health | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')" = "0.80.8" ]; do sleep 30; done
log "API 0.80.8"
step "1 semantic bwb-amendments" semantic bwb-amendments || log "1 failed, going on"
step "2 semantic tk-faction-succession" semantic tk-faction-succession || log "2 failed, going on"
step "3 normalize bwb (full)" normalize bwb || log "3 failed, going on"
step "4 semantic graph-derive instruments" semantic graph-derive instruments || log "4 failed, going on"
step "5 semantic bwb-grondslagen" semantic bwb-grondslagen || log "5 failed, going on"
step "6 semantic tooi-ministries" semantic tooi-ministries || log "6 failed, going on"
step "7 sitemaps" sitemaps || log "7 failed, going on"
if step "8 fill lg_cited_by.areas" semantic graph-light --only cited-by --all; then
  docker exec -i -e PGOPTIONS='-c lock_timeout=5s -c statement_timeout=120s' "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
    psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}" <<'SQL' && log "8b old index dropped" || log "8b failed, going on"
DROP INDEX CONCURRENTLY IF EXISTS lg_cited_by_article;
ANALYZE lg_cited_by;
SQL
else log "8 failed, index kept"; fi
step "9a normalize tk-content" normalize tk-content || log "9a failed, going on"
step "9b semantic graph-light" semantic graph-light || log "9b failed, going on"
step "9c normalize tk-dossiers" normalize tk-dossiers || log "9c failed, going on"
step "9d normalize eurlex" normalize eurlex || log "9d failed, going on"
step "9e normalize rijksoverheid" normalize rijksoverheid || log "9e failed, going on"
log "all done"
