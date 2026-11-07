#!/bin/sh
# The steps of creators.sh, under the lock (B110 bron 1): who issued each stored ministerial regulation, asked of the
# KOOP SRU fifty to a query at the end of `retrieve staatscourant` (about 3 s a query: 20000 is some
# 20 minutes; its own listing of the last day is small), then normalize staatscourant over what was asked and semantic
# tooi-ministries for the LED_BY edges. creators-counts.sql before and after. The Staatsblad (a few thousand stored
# AMvBs) and what is left over go on in the nightly, 5000 a source a night.
. "$(dirname "$0")/_steps.sh"
since=$(date -u +%Y-%m-%dT%H:%M:%S)
counts creators before creators-counts.sql
step c1-retrieve-staatscourant retrieve staatscourant --since 1d --creators 20000
step c2-normalize-staatscourant normalize staatscourant --since "$since"
step c3-semantic-tooi-ministries semantic tooi-ministries
counts creators after creators-counts.sql
echo "== all done $(date -u +%T)"
