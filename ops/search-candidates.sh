#!/bin/sh
# Once after the deploy of 0.80.43 (B172, #1200): `search-candidates` reads every common word again, so the rows get
# the new signature and the column `date` (step 0). Until then a common word searches itself cold (seconds). The
# poll does this on weekdays and the weekly run on Sunday; this is for a deploy in between. One step under the lock.
. "$(dirname "$0")/_steps.sh"
step 1-search-candidates search-candidates
echo "== all done $(date -u +%T)"
