#!/bin/sh
# Step 0 of 0.80.33, once, right before its deploy: the index instruments_list_sort_title (B127), which
# ensure_schema would otherwise build at the start of the API while it blocks the table. Under the lock of the
# scheduled runs, CONCURRENTLY (no time-out); a failed build is left invalid, which the check at the end shows
# (drop it and run this again). IF NOT EXISTS, so a second run does nothing.
. "$(dirname "$0")/_steps.sh"

sql() {
  docker exec -i -e PGOPTIONS="$1" "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
    psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}"
}

sql '-c statement_timeout=0' <<'SQL'
CREATE INDEX CONCURRENTLY IF NOT EXISTS instruments_list_sort_title ON instruments ((regexp_replace(coalesce(citation_title, public.lg_str(props -> 'title'), public.lg_str(props -> 'display_name'), key), '^[^[:alnum:]]+', '')), key) WHERE kind IS DISTINCT FROM 'publicatie';
SELECT indexrelid::regclass, indisvalid FROM pg_index WHERE indexrelid::regclass::text = 'instruments_list_sort_title';
ANALYZE instruments;
SQL
echo "== all done $(date -u +%T)"
