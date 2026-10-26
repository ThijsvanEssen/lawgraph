#!/bin/sh
# Stops the loop of renormalize-judgments.sh (and after-07966.sh, which started it with a day-long window), so
# after-0.80.9.sh can take the lock (go Thijs 26 Oct). The slice it runs goes on to its end, writes where the next
# one starts (out/renormalize-judgments.after) and lets go of the lock; no next slice starts. A new
# renormalize-judgments.sh goes on from there. Writes no data itself.
for name in after-07966.sh renormalize-judgments.sh; do
  for pid in $(pgrep -f "^sh (.*/)?$name\$"); do
    kill -TERM "$pid" && echo "$(date -u +%T) $name ($pid) stopped"
  done
done
echo "$(date -u +%T) slice still running: $(pgrep -f 'renormalize-judgments-slice.sh' | tr '\n' ' ')"
echo "$(date -u +%T) lock: $(ls -ld /srv/lawgraph/tmp/lawgraph-scheduled.lock 2>/dev/null || echo free)"
