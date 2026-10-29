#!/bin/sh
# The watch of the freshness (lawgraph-freshness-watch.timer, daily 09:30 after the nightly): how far each source
# is behind, against the limits of /srv/lawgraph/freshness.json. It reads /api/stats and /api/stats/coverage (no
# database, no source) and lets `python -m lawgraph.freshness` decide; what that prints as `Versheid ...` goes to
# alert.sh: one line per subject that got worse, again after 24 hours while it stays so, and `hersteld` when it is
# back. Never while a deploy runs (tmp/deploying) or while the API started less than 10 minutes ago, never two at
# once (flock). The coverage only once the API has warmed up; without its answer only its rules are skipped.
DIR=/srv/lawgraph
STATE=$DIR/tmp/freshness
API=http://127.0.0.1:8000
PYTHON=$DIR/app/.venv/bin/python
mkdir -p "$STATE"
exec 9> "$STATE/lock"
flock -n 9 || exit 0

now=$(date +%s)
age() { echo $((now - $(stat -c %Y "$1"))); }
log() { echo "$(date -u +%FT%TZ) $*"; }

if [ -e "$DIR/tmp/deploying" ] && [ "$(age "$DIR/tmp/deploying")" -lt 3600 ]; then
  log "a deploy runs; skipped"; exit 0
fi
started=$(systemctl show -p ActiveEnterTimestamp --value lawgraph-api.service)
if [ -z "$started" ] || [ $((now - $(date -d "$started" +%s))) -lt 600 ]; then
  log "the API started less than 10 minutes ago; skipped"; exit 0
fi

if ! curl -fsS -m 60 -o "$STATE/stats.json" "$API/api/stats"; then
  log "/api/stats did not answer; the API watch is the one that tells"; exit 0
fi

# the coverage is slow cold: wait for the warm-up (at most 10 minutes), then three tries
coverage=""
i=0
while [ "$i" -lt 20 ] && ! curl -fsS -m 10 "$API/api/health" | grep -q '"warm":true'; do
  sleep 30; i=$((i + 1))
done
for _ in 1 2 3; do
  if curl -fsS -m 120 -o "$STATE/coverage.json" "$API/api/stats/coverage"; then
    coverage="--coverage $STATE/coverage.json"; break
  fi
  sleep 30
done
[ -n "$coverage" ] || log "no coverage answer; its rules are skipped"

# shellcheck disable=SC2086
if ! "$PYTHON" -m lawgraph.freshness --rules "$DIR/freshness.json" --stats "$STATE/stats.json" $coverage \
    --state "$STATE/state.json" > "$STATE/lines"; then
  log "lawgraph.freshness failed"
  # the watch itself broke: once per 24 hours
  if [ ! -e "$STATE/broken" ] || [ "$(age "$STATE/broken")" -gt 86400 ]; then
    touch "$STATE/broken"
    "$DIR/bin/alert.sh" "Versheid watch: mislukt, onverwacht [actie]" || true
  fi
  exit 1
fi
while IFS= read -r line; do
  case "$line" in
    Versheid*) log "$line"; "$DIR/bin/alert.sh" "$line" || true ;;
  esac
done < "$STATE/lines"
