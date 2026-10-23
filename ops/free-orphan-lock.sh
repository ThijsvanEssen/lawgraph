#!/bin/sh
# Removes the lock of the scheduled runs only when nothing that takes it runs: no lawgraph command, no step.sh and no
# daily/weekly/poll script. A holder that was stopped (stop-p14.sh) can leave it behind. Otherwise it leaves it.
L=/srv/lawgraph/tmp/lawgraph-scheduled.lock
[ -d "$L" ] || { echo "$(date -u +%T) lock: free"; exit 0; }
if pgrep -f '^/srv/lawgraph/app/\.venv/bin/python \.venv/bin/lawgraph ' >/dev/null \
  || pgrep -f 'scripts/(step|daily|weekly|poll)\.sh' >/dev/null; then
  echo "$(date -u +%T) a scheduled run holds it, left alone: $(pgrep -af 'lawgraph |scripts/' | cut -c1-120 | head -3)"
  exit 0
fi
rmdir "$L" && echo "$(date -u +%T) orphaned lock removed (made $(date -u -r "$L" +%T 2>/dev/null || echo earlier))"
