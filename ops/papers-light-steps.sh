#!/bin/sh
# The steps of papers-light.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
counts papers before papers-light-counts.sql
step p1-graph-light-papers semantic graph-light --papers
counts papers after papers-light-counts.sql
echo "== all done $(date -u +%T)"
