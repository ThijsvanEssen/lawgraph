#!/bin/sh
# Sets how many judgments the next slices of renormalize-judgments.sh read: writes out/renormalize-judgments.limit
# (LIMIT, default 50000) and touches nothing else. A slice that takes longer than 25 minutes lowers it again.
D=$(cd "$(dirname "$0")" && pwd)
LIMITS="$D/out/renormalize-judgments.limit"
echo "== was: $(cat "$LIMITS" 2>/dev/null || echo 'not set')"
echo "${LIMIT:-50000}" > "$LIMITS"
echo "== now: $(cat "$LIMITS")"
