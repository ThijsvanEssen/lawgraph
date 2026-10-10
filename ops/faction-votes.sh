#!/bin/sh
# Once after the deploy that brings lg_faction_votes: semantic graph-light fills the votes of the factions written
# before its triggers (5,000 decisions a statement; the judgments, papers and instruments it keeps light already have
# theirs) and notes that the table is whole, from when the page of a member's votes reads it; faction-votes-counts.sql
# before and after; under the lock.
. "$(dirname "$0")/_steps.sh"
counts votes before faction-votes-counts.sql
step v1-semantic-graph-light semantic graph-light
counts votes after faction-votes-counts.sql
echo "== all done $(date -u +%T)"
