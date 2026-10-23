#!/bin/sh
# The watch of the API (lawgraph-api-watch.timer, every minute): /api/health within 10 s, or a failure counted.
# At the third failure in a row it keeps the evidence (the sessions of the database and a stack dump of every
# thread, SIGUSR1) in ops/api-hang-<date>-<time>.txt, restarts the API, waits until it answers and alerts. Never
# while a deploy runs (deploy.yml's tmp/deploying) or while the API started less than 10 minutes ago, never two
# at once (flock), and at most one restart per 30 minutes: past that it alerts only.
DIR=/srv/lawgraph
STATE=$DIR/tmp/api-watch
OUT_DIR=$DIR/ops
HEALTH=http://127.0.0.1:8000/api/health
FAILS_TO_RESTART=3
RESTART_GAP=1800
mkdir -p "$STATE"
exec 9> "$STATE/lock"
flock -n 9 || exit 0

now=$(date +%s)
age() { echo $((now - $(stat -c %Y "$1"))); }
alert() { "$DIR/bin/alert.sh" "API health: $1" || true; }

# a deploy changes the API (a marker older than an hour is one a killed deploy left)
if [ -e "$DIR/tmp/deploying" ] && [ "$(age "$DIR/tmp/deploying")" -lt 3600 ]; then
  rm -f "$STATE/fails"; exit 0
fi
started=$(systemctl show -p ActiveEnterTimestamp --value lawgraph-api.service)
if [ -z "$started" ] || [ $((now - $(date -d "$started" +%s))) -lt 600 ]; then
  rm -f "$STATE/fails"; exit 0
fi

if curl -fsS -m 10 -o /dev/null "$HEALTH"; then
  rm -f "$STATE/fails"; exit 0
fi
fails=$(( $(cat "$STATE/fails" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$STATE/fails"
echo "$(date -u +%FT%TZ) /api/health failed ($fails in a row)"
[ "$fails" -ge "$FAILS_TO_RESTART" ] || exit 0

if [ -e "$STATE/restarted" ] && [ "$(age "$STATE/restarted")" -lt "$RESTART_GAP" ]; then
  # once per hang: the count goes on, the alert at the third failure only
  [ "$fails" -eq "$FAILS_TO_RESTART" ] && alert "mislukt, geen-antwoord [actie]"
  exit 0
fi

OUT=$OUT_DIR/api-hang-$(date -u +%Y%m%d-%H%M%S).txt
PID=$(systemctl show -p MainPID --value lawgraph-api.service)
{ echo "== $(date -u +%FT%TZ) pid $PID, /api/health failed $fails times in a row (api-watch)"
  docker exec lawgraph-postgres psql -X -U lawgraph -d lawgraph -Atc "SELECT pid, application_name, state, wait_event, date_trunc('second', now()-state_change), left(query, 100) FROM pg_stat_activity WHERE datname = current_database() ORDER BY 5 DESC LIMIT 40"
} > "$OUT" 2>&1
if [ -n "$PID" ] && [ "$PID" != 0 ] && kill -USR1 "$PID"; then
  sleep 3
  journalctl -u lawgraph-api --since "-1 min" --no-pager | tail -400 >> "$OUT"
fi
touch "$STATE/restarted"
rm -f "$STATE/fails"
sudo -n systemctl restart lawgraph-api < /dev/null
echo "$(date -u +%T) restarted; evidence: $OUT"
i=0
while [ "$i" -lt 60 ]; do
  if curl -fsS -m 5 -o /dev/null "$HEALTH"; then
    echo "$(date -u +%T) healthy"
    alert "herstart, geen-antwoord [actie]"
    exit 0
  fi
  sleep 5; i=$((i + 1))
done
alert "mislukt, geen-antwoord [actie]"
exit 1
