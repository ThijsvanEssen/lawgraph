#!/bin/sh
# Step 0 of the release with instruments.same_as (B79), once, right before its deploy: the nullable column, no rewrite.
# Under the lock of the scheduled runs. The ALTER waits for an exclusive lock on instruments and the reads of the API
# queue behind that wait: lock_timeout keeps it at 5 s, tried again after 15 s, at most 20 times. IF NOT EXISTS, so a
# second run does nothing. After the deploy `lawgraph semantic verdragenbank` fills it (about a minute): until then the
# list shows a treaty with a BWB text twice.
. "$(dirname "$0")/_steps.sh"

column() {
  echo "ALTER TABLE instruments ADD COLUMN IF NOT EXISTS same_as text;" |
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
