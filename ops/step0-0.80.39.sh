#!/bin/sh
# Step 0 of 0.80.39, once, right before its deploy: the columns lg_feed_events.tier and .subject_areas (#1174,
# nullable, no rewrite) and the index lg_feed_events_tier, which ensure_schema would otherwise add at the start of
# the API while it blocks the table (the only change of the schema since 0.80.38). Under the lock of the scheduled
# runs. The ALTER waits for an exclusive lock on lg_feed_events and the reads of the API queue behind that wait:
# lock_timeout keeps it at 5 s, tried again after 15 s, at most 20 times. The index is built CONCURRENTLY (no
# time-out); a failed one is left invalid, which the check at the end shows (drop it and run this again). Every
# statement is IF NOT EXISTS, so a second run does nothing.
#
# The rows keep tier and subject_areas null until the events are written again whole: the feed without `tier` counts
# them as before (null is the feed's own tiers), but under `tier` or `subject_area` the table holds none. The rebuild
# is the next nightly (`lawgraph feed-events` in daily.sh), or by hand under this lock: `.venv/bin/lawgraph
# feed-events`. It now writes the judgments of every tier too: measured locally 18 s for 262k events, 106 s for 992k
# with 730k more judgments (about 0.12 ms a row), so on prod minutes, not half an hour.
. "$(dirname "$0")/_steps.sh"

sql() {
  docker exec -i -e PGOPTIONS="$1" "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
    psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}"
}

columns() {
  sql '-c lock_timeout=5s -c statement_timeout=60s' <<'SQL'
ALTER TABLE lg_feed_events ADD COLUMN IF NOT EXISTS tier text;
ALTER TABLE lg_feed_events ADD COLUMN IF NOT EXISTS subject_areas text[];
SQL
}
try=1
until columns; do
  [ $try -lt 20 ] || { echo "== columns failed $try times"; exit 1; }
  try=$((try + 1))
  sleep 15
done
echo "== columns done, try $try $(date -u +%T)"

sql '-c statement_timeout=0' <<'SQL'
CREATE INDEX CONCURRENTLY IF NOT EXISTS lg_feed_events_tier ON lg_feed_events (tier, date) WHERE tier IS NOT NULL;
SELECT indexrelid::regclass, indisvalid FROM pg_index WHERE indexrelid::regclass::text = 'lg_feed_events_tier';
ANALYZE lg_feed_events;
SQL
echo "== all done $(date -u +%T)"
