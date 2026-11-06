#!/bin/sh
# Stops tk-backfill-nights.sh before its next night: a step that runs goes to its end (never SIGSTOP).
D=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$D/out"
touch "$D/out/tk-backfill-nights.stop"
echo "== stop set $(date -u +%T); the loop: $(pgrep -f 'tk-backfill-(nights|steps)\.sh' | tr '\n' ' ')"
