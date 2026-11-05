#!/bin/sh
# The steps of backfill-0.80.30-bills.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
step 1-retrieve retrieve eerstekamer-bills --names-only
step 2-normalize normalize eerstekamer-bills
echo "== all done $(date -u +%T)"
