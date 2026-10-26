#!/bin/sh
# Read only: what restart-api.sh kept of an API hang (api-hang-<time>.txt, every one of today, newest last) and the
# stack dumps (SIGUSR1, faulthandler) and warnings the API wrote to the journal in the hour before the newest one.
OPS=/srv/lawgraph/ops
ls -l "$OPS"/api-hang-*.txt 2>/dev/null || { echo "no api-hang-*.txt"; exit 0; }
for f in $(ls -tr "$OPS"/api-hang-*.txt | tail -3); do echo "==== $f"; cat "$f"; done
NEWEST=$(ls -t "$OPS"/api-hang-*.txt | head -1)
UNTIL=$(date -u -r "$NEWEST" '+%F %T')
echo "==== journal lawgraph-api, the hour before $UNTIL UTC: dumps, warnings, errors"
journalctl -u lawgraph-api --utc --since "$(date -u -d "$UNTIL 1 hour ago" '+%F %T')" --until "$UNTIL" --no-pager -o short-iso \
  | grep -E 'Thread 0x|Current thread|File "|WARNING|ERROR|Traceback|Error|timed out|unavailable|Started|Stopp' | tail -1500
