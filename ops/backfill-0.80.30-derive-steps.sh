#!/bin/sh
# The step of backfill-0.80.30-derive.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
step 1-graph-derive semantic graph-derive instruments
echo "== all done $(date -u +%T)"
