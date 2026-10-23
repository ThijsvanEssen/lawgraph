#!/bin/sh
# Stops after-0806.sh (P14) and the step it runs, so the deploy of 0.80.8 can take the lock (go Thijs 23 Oct). Its
# runs come back in after-0.80.8.sh; a normalize can run again from the start. The step's step.sh lets go of the
# lock on its way out (trap). Writes no data itself.
for pid in $(pgrep -f "^sh (.*/)?after-0806.sh\$"); do
  kill -TERM "$pid" && echo "$(date -u +%T) after-0806.sh ($pid) stopped"
done
for pid in $(pgrep -f "lawgraph normalize tk-content"); do
  kill -TERM "$pid" && echo "$(date -u +%T) normalize tk-content ($pid) stopped"
done
sleep 20
echo "$(date -u +%T) lock: $(ls -ld /srv/lawgraph/tmp/lawgraph-scheduled.lock 2>/dev/null || echo free)"
