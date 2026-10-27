#!/bin/bash
# VACUUM (ANALYZE) of edges (27 Oct 2026: 2.16 M dead rows, 14 %, and 58 % of its pages all-visible, so the index-only
# scans of /api/chains and the neighbourhoods fetch the heap). A plain vacuum: reads and writes go on beside it. Under
# the lock of the scheduled runs, at most 30 min; the state of edges before and after in out/vacuum-edges/.
. "$(dirname "$0")/_steps.sh"

state() {
  read_only_sql > "$OUT/state-$1.txt" 2>&1 <<'SQL'
SET default_transaction_read_only = on;
SELECT n_live_tup, n_dead_tup, last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
FROM pg_stat_user_tables WHERE relname = 'edges';
SELECT relpages, relallvisible, round(100.0 * relallvisible / greatest(relpages, 1), 1) AS pct_visible
FROM pg_class WHERE relname = 'edges';
SQL
  echo "== state $1"
  cat "$OUT/state-$1.txt"
}

state before
echo "== vacuum start $(date -u +%T)"
docker exec -i -e PGOPTIONS='-c statement_timeout=1800s -c lock_timeout=60s' "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
  psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}" \
  -c 'VACUUM (ANALYZE, VERBOSE) edges' > "$OUT/vacuum.log" 2>&1
rc=$?
echo "== vacuum rc $rc $(date -u +%T)"
tail -n 20 "$OUT/vacuum.log"
state after
exit $rc
