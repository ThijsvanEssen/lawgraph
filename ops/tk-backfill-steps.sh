#!/bin/sh
# One step of the backfill of the XML of the Tweede Kamer papers, under the lock: `retrieve tk-content` for the papers
# of the graph that have none stored, at most TK_LIMIT papers (default 3600, about 0.5 s a paper) and at most TK_MINUTES
# minutes (default 28), so the step lets go of the lock in time. The same step goes on with what is left; TK_UNTIL
# (a day, e.g. 2016-01-01) takes only the papers dated before it (those without a date are left out).
# Refuses to start when the file system of the database is fuller than DISK_MAX_PCT (default 90): the XML of 96,000 papers
# is some 5-15 GB (an estimate), and /srv had 24 GB free on 28 Oct. Normalize and the rest of the pipeline follow in the
# nightly or in a step of their own.
. "$(dirname "$0")/_steps.sh"
used=$(df -P /srv/lawgraph | awk 'NR==2 {gsub("%", "", $5); print $5}')
if [ "${used:-100}" -ge "${DISK_MAX_PCT:-90}" ]; then
  echo "== /srv/lawgraph ${used}% full (limit ${DISK_MAX_PCT:-90}); not starting"
  printf 'failed\ttk-backfill\t/srv/lawgraph %s%% full\n' "$used" > "$OUT/failed"
  exit 1
fi
counts tk before tk-backfill-counts.sql
if [ -n "$TK_UNTIL" ]; then
  step t1-retrieve-tk-content retrieve tk-content --limit "${TK_LIMIT:-3600}" --minutes "${TK_MINUTES:-28}" --until "$TK_UNTIL"
else
  step t1-retrieve-tk-content retrieve tk-content --limit "${TK_LIMIT:-3600}" --minutes "${TK_MINUTES:-28}"
fi
counts tk after tk-backfill-counts.sql
echo "== all done $(date -u +%T)"
