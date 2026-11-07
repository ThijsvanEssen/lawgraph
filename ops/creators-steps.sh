#!/bin/sh
# The steps of creators.sh, under the lock (B110 bron 1): who issued each stored publication, asked of the KOOP SRU
# fifty to a query (about 3 s a query: CREATORS_LIMIT 20000 a source is some 20 minutes), then normalize of both
# publications over what was asked and semantic tooi-ministries for the LED_BY edges. creators-counts.sql before and
# after. A source with more than CREATORS_LIMIT left goes on in the next run, or in the nightly (5000 a night).
. "$(dirname "$0")/_steps.sh"
since=$(date -u +%Y-%m-%dT%H:%M:%S)
counts creators before creators-counts.sql
step c1-retrieve-staatscourant-creators retrieve staatscourant-creators --limit "${CREATORS_LIMIT:-20000}"
step c2-retrieve-staatsblad-creators retrieve staatsblad-creators --limit "${CREATORS_LIMIT:-20000}"
step c3-normalize-staatscourant normalize staatscourant --since "$since"
step c4-normalize-staatsblad normalize staatsblad --since "$since"
step c5-semantic-tooi-ministries semantic tooi-ministries
counts creators after creators-counts.sql
echo "== all done $(date -u +%T)"
