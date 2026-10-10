#!/bin/sh
# Once after the deploy that brings lg_instrument_names: semantic graph-light fills the names of the instruments
# written before its triggers (a batch of 20,000 a statement; the judgments and papers it keeps light already have
# theirs); instrument-names-counts.sql before and after; under the lock (minutes).
. "$(dirname "$0")/_steps.sh"
counts names before instrument-names-counts.sql
step n1-semantic-graph-light semantic graph-light
counts names after instrument-names-counts.sql
echo "== all done $(date -u +%T)"
