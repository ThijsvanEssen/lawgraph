#!/bin/sh
# Step 0 of the release with the laws of the Staatsblad, once, right before its deploy: adds the column
# articles.official_id (nullable, no default: the catalog only, no rewrite of the table) and builds its unique index
# articles_official_id_article_number CONCURRENTLY, so that the start of the API finds both and builds nothing on
# the table. Under the lock of the scheduled runs; official-id-counts.sql before and after. The ADD COLUMN waits for
# an exclusive lock on articles, and the reads of the API queue behind that wait: lock_timeout keeps it at 5 s, and
# a statement that times out is tried again after 15 s, at most 20 times. Every statement is IF NOT EXISTS, so a
# second run does nothing; a CONCURRENTLY that failed leaves an invalid index, which the counts show: drop it with
# DROP INDEX CONCURRENTLY and run this again. The release before it starts on the database this leaves (a nullable
# column it does not know), so a rollback needs nothing.
. "$(dirname "$0")/_steps.sh"
counts official-id before official-id-counts.sql

psql_run() {
  docker exec -i -e PGOPTIONS="$1" "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
    psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}"
}
add_column() {
  echo 'ALTER TABLE articles ADD COLUMN IF NOT EXISTS official_id text;' \
    | psql_run '-c lock_timeout=5s -c statement_timeout=120s'
}

try=1
until add_column; do
  [ $try -lt 20 ] || { echo "== add column failed $try times"; exit 1; }
  try=$((try + 1))
  sleep 15
done
echo "== column added, try $try"

start=$(date +%s)
echo 'CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS articles_official_id_article_number ON articles (official_id, article_number);' \
  | psql_run '-c statement_timeout=0' || { echo "== index failed"; exit 1; }
echo "== index built after $(( $(date +%s) - start )) s"
counts official-id after official-id-counts.sql
echo "== all done $(date -u +%T)"
