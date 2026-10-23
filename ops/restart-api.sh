#!/bin/sh
# Restarts the API in an incident (it answers 503 "database unavailable" while its pool hangs): first a stack dump of
# every thread (SIGUSR1, faulthandler) and the database sessions of the API into api-hang-<time>.txt for the
# diagnosis, then a restart, then waits until /api/health answers again. Writes no data.
OUT=/srv/lawgraph/ops/api-hang-$(date -u +%H%M).txt
PID=$(systemctl show -p MainPID --value lawgraph-api.service)
{ echo "== $(date -u +%FT%TZ) pid $PID"; curl -s -m 5 http://127.0.0.1:8000/api/health; echo
  docker exec lawgraph-postgres psql -X -U lawgraph -d lawgraph -Atc "SELECT pid, application_name, state, wait_event, date_trunc('second', now()-state_change), left(query, 100) FROM pg_stat_activity WHERE datname = current_database() ORDER BY 5 DESC LIMIT 40"
} > "$OUT" 2>&1
[ -n "$PID" ] && [ "$PID" != 0 ] && kill -USR1 "$PID" && sleep 3 && journalctl -u lawgraph-api --since "-1 min" --no-pager | tail -400 >> "$OUT"
sudo -n systemctl restart lawgraph-api < /dev/null && echo "$(date -u +%T) restarted"
for i in $(seq 1 60); do curl -s -m 5 http://127.0.0.1:8000/api/health | grep -q '"status":"ok"' && { echo "$(date -u +%T) healthy"; break; }; sleep 5; done
echo "evidence: $OUT"
