#!/bin/sh
# Step 0 of the release with `normalize cbs` (B140), once, right before its deploy: the table lg_court_districts.
# ensure_schema would create it at the start of the API as well (a new, empty table: no lock on another table, and an
# older release starts on a database that has it), so this only makes the start do nothing. Under the lock of the
# scheduled runs; lock_timeout keeps the CREATE at 5 s. IF NOT EXISTS, so a second run does nothing.
#
# The table stays empty until `retrieve cbs` and `normalize cbs` ran: both are weekly (`scripts/weekly.sh`, not the
# nightly): the table fills on the first weekly run after the deploy, or a run by hand; a run is a few requests to
# opendata.cbs.nl and seconds of work.
. "$(dirname "$0")/_steps.sh"

sql() {
  docker exec -i -e PGOPTIONS="$1" "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
    psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}"
}

sql '-c lock_timeout=5s -c statement_timeout=60s' <<'SQL'
CREATE TABLE IF NOT EXISTS lg_court_districts (
    year integer NOT NULL,
    municipality_code text NOT NULL,
    municipality text NOT NULL,
    province text NOT NULL,
    district text NOT NULL,
    district_code text NOT NULL,
    circuit text NOT NULL,
    circuit_code text NOT NULL,
    district_article text,
    circuit_article text,
    law_district text,
    district_check text,
    circuit_check text,
    PRIMARY KEY (year, municipality_code)
);
SELECT count(*) AS rows FROM lg_court_districts;
SQL
echo "== all done $(date -u +%T)"
