#!/bin/sh
# Step 0 of 0.80.7, once, right before its deploy: the column lg_cited_by.areas (#930, nullable, no rewrite) and the
# two indexes ensure_schema would otherwise build at the start of the API while it blocks writes:
# lg_cited_by_article_areas (#930) and documents_article_100 (#929). Under the lock of the scheduled runs. The
# ALTER waits for an exclusive lock on lg_cited_by and the reads of the API queue behind that wait: lock_timeout
# keeps it at 5 s, tried again after 15 s, at most 20 times. The indexes are built CONCURRENTLY (no time-out); a
# failed one is left invalid, which the check at the end shows (drop it and run this again). Every statement is
# IF NOT EXISTS, so a second run does nothing.
. "$(dirname "$0")/_steps.sh"

sql() {
  docker exec -i -e PGOPTIONS="$1" "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
    psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}"
}

column() {
  echo "ALTER TABLE lg_cited_by ADD COLUMN IF NOT EXISTS areas text[];" | sql '-c lock_timeout=5s -c statement_timeout=60s'
}
try=1
until column; do
  [ $try -lt 20 ] || { echo "== column failed $try times"; exit 1; }
  try=$((try + 1))
  sleep 15
done
echo "== column done, try $try $(date -u +%T)"

sql '-c statement_timeout=0' <<'SQL'
CREATE INDEX CONCURRENTLY IF NOT EXISTS lg_cited_by_article_areas ON lg_cited_by (article_id) INCLUDE (judgment_id, edge_key, mentions, date_eff, ecli, court_code, tier, cited, areas);
CREATE INDEX CONCURRENTLY IF NOT EXISTS documents_article_100 ON documents (date DESC NULLS LAST, key) WHERE kind = 'Brief regering' AND public.lg_str(pj_subject) ~* '^(?:(?:aanvullende?|aanvulling(?: op de)?|kennisgeving)[\s:–-]*)?artikel[\s-]*100(?![0-9])(?![\s-]*procedure)|\(artikel[\s-]*100(?![0-9])[^)]*\)\s*$';
SELECT indexrelid::regclass, indisvalid FROM pg_index WHERE indexrelid::regclass::text IN ('lg_cited_by_article_areas', 'documents_article_100');
ANALYZE lg_cited_by;
ANALYZE documents;
SQL
echo "== all done $(date -u +%T)"
