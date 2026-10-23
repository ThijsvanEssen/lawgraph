#!/bin/sh
# Holds the loops of the slice scripts (renormalize-judgments.sh, relink-judgments.sh, relink-citations.sh) and of
# the runs after a release (after-0806.sh) so a
# deploy can take the lock: each loop gets SIGSTOP, the slice it started runs on to its end and lets go of the
# lock, and no next slice starts. go-on-slices.sh lets them go on where they stopped. Writes no data itself.
for name in renormalize-judgments.sh relink-judgments.sh relink-citations.sh after-0806.sh; do
  for pid in $(pgrep -f "^sh (.*/)?$name\$"); do
    kill -STOP "$pid" && echo "$(date -u +%T) $name ($pid) held; its slice runs to its end"
  done
done
echo "$(date -u +%T) lock: $(ls -ld /srv/lawgraph/tmp/lawgraph-scheduled.lock 2>/dev/null || echo free)"
