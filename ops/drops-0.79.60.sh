#!/bin/sh
# Step 0 of 0.79.60, once, right before its deploy: drops what 0.79.59 no longer fills or reads (search_tsv of six
# tables, sort_order and closed_on of dossiers with their indexes, lg_tsv, lg_bm25 and the four state tables of the
# light tables). Under the lock of the scheduled runs; drops-0.79.60-counts.sql before and after. Every statement is
# IF EXISTS, so a second run does nothing. A DROP COLUMN changes the catalog only (no rewrite of the table) but waits
# for an exclusive lock on its table, and the reads of the API queue behind that wait: lock_timeout keeps it at 5 s,
# and a statement that times out is tried again after 15 s, the run at most 20 times.
. "$(dirname "$0")/_steps.sh"
counts drops before drops-0.79.60-counts.sql

drops() {
  docker exec -i -e PGOPTIONS='-c lock_timeout=5s -c statement_timeout=120s' \
    "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
    psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}" <<'SQL'
ALTER TABLE articles DROP COLUMN IF EXISTS search_tsv;
ALTER TABLE instruments DROP COLUMN IF EXISTS search_tsv;
ALTER TABLE judgments DROP COLUMN IF EXISTS search_tsv;
ALTER TABLE documents DROP COLUMN IF EXISTS search_tsv;
ALTER TABLE committees DROP COLUMN IF EXISTS search_tsv;
ALTER TABLE dossiers DROP COLUMN IF EXISTS search_tsv, DROP COLUMN IF EXISTS sort_order,
    DROP COLUMN IF EXISTS closed_on;
DROP FUNCTION IF EXISTS lg_tsv(text[], "char");
DROP FUNCTION IF EXISTS lg_bm25(float8, float8, float8, float8);
DROP TABLE IF EXISTS lg_led_state, lg_faction_votes_state, lg_authored_state, lg_authored_dated;
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
counts drops after drops-0.79.60-counts.sql
echo "== all done $(date -u +%T)"
