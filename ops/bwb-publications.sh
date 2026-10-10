#!/bin/sh
# Once after the deploy that brings semantic bwb-publications (the daily run keeps it after): SAME_AS from each
# paper of the Staatsblad and the Staatscourant to the BWB publication of its official id; bwb-publications-counts.sql
# before and after; under the lock (minutes).
. "$(dirname "$0")/_steps.sh"
counts papers before bwb-publications-counts.sql
step p1-semantic-bwb-publications semantic bwb-publications
counts papers after bwb-publications-counts.sql
echo "== all done $(date -u +%T)"
