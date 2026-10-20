# Sourced by an ops script that writes: the venv and environment of the scheduled runs, a wait until no
# scheduled run is busy, the lock of the scheduled runs (let go on exit), and two helpers:
#   counts <block> <before|after> <file.sql>   a read-only query from ops/ (read_only_sql of _sql.sh), printed and
#                                                kept in out/<script>/; a failing query prints FAILED, the script goes on
#   step <label> <lawgraph args...>              one lawgraph command, its log in out/<script>/; on failure it shows the
#                                                errors in full, leaves "<label>: <reason>" in out/<script>/failed (for
#                                                `fail` of _night.sh) and exits; a source that was unavailable (exit 3)
#                                                is said and alerted, and the script goes on
OPS=$(cd "$(dirname "$0")" && pwd)
OUT="$OPS/out/$(basename "$0" .sh)"
cd /srv/lawgraph/app || exit 1
set -a && . /srv/lawgraph/scheduler.env && set +a
. "$OPS/_sql.sh"
mkdir -p "$OUT"
rm -f "$OUT/failed"
L=.venv/bin/lawgraph

until [ -z "$(systemctl list-units --state=activating,active,deactivating --no-legend 'lawgraph-*.service' | grep -v lawgraph-api)" ]; do sleep 15; done
LOCK="${TMPDIR:-/tmp}/lawgraph-scheduled.lock"
until mkdir "$LOCK" 2>/dev/null; do echo "$(date -u +%T) lock held, waiting"; sleep 30; done
trap 'rmdir "$LOCK"' EXIT
trap 'exit 130' INT TERM
echo "== lock $LOCK taken $(date -u +%T), version $(curl -s http://127.0.0.1:8000/api/health | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')"

counts() {
  read_only_sql < "$OPS/$3" > "$OUT/$1-$2.txt" 2>&1
  rc=$?
  echo "== $1 counts $2 rc $rc$([ $rc -eq 0 ] || echo ' FAILED')"
  cat "$OUT/$1-$2.txt"
}
step() {
  label="$1"; shift
  start=$(date +%s)
  echo "== $label start $(date -u +%T)"
  rm -f "$OUT/$label.outcome"
  LAWGRAPH_OUTCOME_FILE="$OUT/$label.outcome" $L "$@" < /dev/null > "$OUT/$label.log" 2>&1
  rc=$?
  why=$(cat "$OUT/$label.outcome" 2>/dev/null)
  if [ $rc -eq 0 ]; then
    grep -E "Done in|Failed after|ERROR" "$OUT/$label.log" | tail -3
  else
    grep -E "pipelines\.command: (Failed after|Error: |Unavailable: )" "$OUT/$label.log"
  fi
  echo "== $label rc $rc after $(( $(date +%s) - start )) s"
  case $rc in
    0) ;;
    3)
      echo "== $label: a source was unavailable ($why); going on"
      [ -z "$LAWGRAPH_ALERT_COMMAND" ] || LAWGRAPH_ALERT_MESSAGE="lawgraph ops $(basename "$0" .sh): $label: source unavailable: $why (log: $OUT/$label.log)" sh -c "$LAWGRAPH_ALERT_COMMAND"
      ;;
    *)
      echo "$label: ${why:-exit code $rc}" > "$OUT/failed"
      exit $rc
      ;;
  esac
}
