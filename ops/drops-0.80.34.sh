#!/bin/sh
# Step 0 of 0.80.34, once, right before its deploy: drops instruments_list_title, which 0.80.33 no
# longer reads (B127 sorts on instruments_list_sort_title). It stays one release, so a rollback to 0.80.32 keeps
# its index. Under the lock of the scheduled runs, CONCURRENTLY; IF EXISTS, so a second run does nothing.
. "$(dirname "$0")/_steps.sh"

docker exec -i -e PGOPTIONS='-c statement_timeout=0' "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
  psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}" \
  -c 'DROP INDEX CONCURRENTLY IF EXISTS instruments_list_title;'
echo "== all done $(date -u +%T)"
