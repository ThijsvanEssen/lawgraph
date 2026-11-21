#!/bin/sh
# Step 0 of the release with recent work in the search (B172), once, right before its deploy: the column
# lg_search_candidates.date (nullable, no rewrite), which ensure_schema would otherwise add at the start of the API
# while it blocks the table. Under the lock of the scheduled runs. The ALTER waits for an exclusive lock on
# lg_search_candidates and the searches of a common word queue behind that wait: lock_timeout keeps it at 5 s, tried
# again after 15 s, at most 20 times. IF NOT EXISTS, so a second run does nothing.
#
# The rows kept keep date null, and their signature is that of the release before: the new release takes none of them
# and finds the hits of a common word itself (a cold search of one takes seconds) until `lawgraph search-candidates`
# reads every word again, the first run after a poll (poll.sh), or by hand under this lock after the deploy:
# `.venv/bin/lawgraph search-candidates` (about one search per word and type, 50 words). A rollback keeps the column:
# the release before writes its rows without it.
. "$(dirname "$0")/_steps.sh"

column() {
  echo "ALTER TABLE lg_search_candidates ADD COLUMN IF NOT EXISTS date text;" |
    docker exec -i -e PGOPTIONS='-c lock_timeout=5s -c statement_timeout=60s' "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
      psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}"
}
try=1
until column; do
  [ $try -lt 20 ] || { echo "== column failed $try times"; exit 1; }
  try=$((try + 1))
  sleep 15
done
echo "== column done, try $try $(date -u +%T)"
