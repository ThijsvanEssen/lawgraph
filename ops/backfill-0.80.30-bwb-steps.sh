#!/bin/sh
# The step of backfill-0.80.30-bwb.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
step 1-semantic-bwb semantic bwb
echo "== all done $(date -u +%T)"
