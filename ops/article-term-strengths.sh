#!/bin/sh
# Step 0 of the release with the strengths of the terms of the articles, once, right before its deploy: adds the
# column lg_article_terms.strengths (nullable, no default: the catalog only, no rewrite of the table), so that the
# start of the API finds it and waits for no lock on the table the search reads. Under the lock of the scheduled
# runs; article-term-strengths-counts.sql before and after. The ADD COLUMN waits for an exclusive lock on
# lg_article_terms, and the searches of articles queue behind that wait: lock_timeout keeps it at 5 s, and a
# statement that times out is tried again after 15 s, at most 20 times. IF NOT EXISTS, so a second run does
# nothing. The column needs no index. The release before it starts on the database this leaves (a nullable column
# it does not know, and keeps its terms without a strength), so a rollback needs nothing.
. "$(dirname "$0")/_steps.sh"
counts article-term-strengths before article-term-strengths-counts.sql

add_column() {
  echo 'ALTER TABLE lg_article_terms ADD COLUMN IF NOT EXISTS strengths real[];' \
    | docker exec -i -e PGOPTIONS='-c lock_timeout=5s -c statement_timeout=120s' \
      "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
      psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}"
}

try=1
until add_column; do
  [ $try -lt 20 ] || { echo "== add column failed $try times"; exit 1; }
  try=$((try + 1))
  sleep 15
done
echo "== column added, try $try"
counts article-term-strengths after article-term-strengths-counts.sql
echo "== all done $(date -u +%T)"
