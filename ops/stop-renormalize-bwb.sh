#!/bin/sh
# Stops the loop of renormalize-bwb.sh: TERM to the loop only, never SIGSTOP. The slice it runs goes on to its end,
# writes where the next one starts (out/renormalize-bwb.after) and lets go of the lock; no next slice starts. The same
# `ops run renormalize-bwb` goes on from there. After a kill of the slice itself: free-orphan-lock.sh. Writes no data.
for pid in $(pgrep -f '^sh (.*/)?renormalize-bwb\.sh$'); do
  kill -TERM "$pid" && echo "$(date -u +%T) renormalize-bwb.sh ($pid) stopped"
done
echo "$(date -u +%T) slice still running: $(pgrep -f 'renormalize-bwb-slice.sh' | tr '\n' ' ')"
echo "$(date -u +%T) lock: $(ls -ld /srv/lawgraph/tmp/lawgraph-scheduled.lock 2>/dev/null || echo free)"
