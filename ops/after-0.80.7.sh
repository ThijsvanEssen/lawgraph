#!/bin/sh
# The runs after the deploy of 0.80.7, once (go Thijs 23 Oct). Waits for the API to report 0.80.7, then each step
# through scripts/step.sh, which takes the lock of the scheduled runs for that step only (rc 75: the lock is held,
# tried again after 60 s), so a poll can run between two steps.
#   1 semantic bwb-amendments            COMMENCES, inwerkingtredingsbesluit -> wet (#927)
#   2 normalize bwb --since yesterday    the ministry of each regulation from the WTI (#931)
#   3 semantic graph-derive instruments  the digest of the instruments with their ministry (#931)
#   4 semantic graph-light --only cited-by --all   lg_cited_by.areas for every row (#930)
#   5 DROP INDEX lg_cited_by_article     replaced by lg_cited_by_article_areas (#930), then ANALYZE
#   6 sitemaps
set -a && . /srv/lawgraph/scheduler.env && set +a
cd /srv/lawgraph/app || exit 1
log() { echo "$(date -u +%FT%TZ) $*"; }
step() { label=$1; shift; while :; do out=$(sh scripts/step.sh "$@" 2>&1); rc=$?
    printf '%s\n' "$out" | grep -E "Done in|Failed|rc |problem" | tail -6
    [ $rc -eq 75 ] && { sleep 60; continue; }; log "$label rc $rc"; return $rc; done; }
until [ "$(curl -s http://127.0.0.1:8000/api/health | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')" = "0.80.7" ]; do sleep 30; done
log "API 0.80.7"
step "1 semantic bwb-amendments" semantic bwb-amendments || log "1 failed, going on"
step "2 normalize bwb (since yesterday)" normalize bwb --since "$(date -u -d yesterday +%F)" || log "2 failed, going on"
step "3 semantic graph-derive instruments" semantic graph-derive instruments || log "3 failed, going on"
step "4 fill lg_cited_by.areas" semantic graph-light --only cited-by --all || { log "4 failed, index kept"; exit 1; }
docker exec -i -e PGOPTIONS='-c lock_timeout=5s -c statement_timeout=120s' "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
  psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}" <<'SQL' && log "5 old index dropped" || log "5 failed, going on"
DROP INDEX CONCURRENTLY IF EXISTS lg_cited_by_article;
ANALYZE lg_cited_by;
SQL
step "6 sitemaps" sitemaps || log "6 failed, going on"
log "all done"
