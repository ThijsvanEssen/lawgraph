#!/bin/sh
# Frees the root disk (/) of what nothing uses: the Docker build cache and the images no container runs on (the
# running containers keep theirs). Then, where sudo allows it, the journal down to 300 MB and the rotated syslog.
# Reads first which program writes most to syslog, so the cause can be capped. Takes no lock: it touches no data.
echo "== $(date -u '+%F %T') UTC, before"; df -h / | tail -1
echo "== who writes syslog (last 20,000 lines)"
tail -n 20000 /var/log/syslog 2>/dev/null | awk '{ sub(/\\[.*/, "", $5); print $5 }' | sort | uniq -c | sort -rn | head -8
tail -n 3 /var/log/syslog 2>/dev/null | cut -c1-300
echo "== docker build cache"; docker builder prune -af 2>&1 | tail -1
echo "== docker images no container uses"; docker image prune -af 2>&1 | tail -1
echo "== journal"; sudo -n journalctl --vacuum-size=300M 2>&1 | tail -1 || echo "no sudo for journalctl"
echo "== syslog.1"; sudo -n truncate -s 0 /var/log/syslog.1 2>&1 && echo "emptied" || echo "no sudo for truncate"
echo "== after"; df -h / | tail -1
