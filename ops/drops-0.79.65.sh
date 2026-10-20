#!/bin/sh
# Once, before or after the deploy of 0.79.65: drops members.active, a column no release since 0.79.60 knows (a
# member's seat is members.seated) and that each command logs as unknown. Under the lock of the scheduled runs;
# drops-0.79.65-counts.sql before and after. The statement is IF EXISTS, so a second run does nothing. A DROP COLUMN
# changes the catalog only (no rewrite of the table) but waits for an exclusive lock on its table, and the reads of
# the API queue behind that wait: lock_timeout keeps it at 5 s, and a statement that times out is tried again after
# 15 s, the run at most 20 times.
. "$(dirname "$0")/_steps.sh"
counts drops before drops-0.79.65-counts.sql

drops() {
  docker exec -i -e PGOPTIONS='-c lock_timeout=5s -c statement_timeout=120s' \
    "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
    psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}" <<'SQL'
ALTER TABLE members DROP COLUMN IF EXISTS active;
SQL
}

try=1
start=$(date +%s)
until drops; do
  [ $try -lt 20 ] || { echo "== drops failed $try times"; exit 1; }
  try=$((try + 1))
  sleep 15
done
echo "== drops done after $(( $(date +%s) - start )) s, try $try"
counts drops after drops-0.79.65-counts.sql
echo "== all done $(date -u +%T)"
