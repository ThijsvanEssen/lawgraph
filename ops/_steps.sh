# Sourced by an ops script that writes: the venv and environment of the scheduled runs, a wait until no
# scheduled run is busy, the lock of the scheduled runs (let go on exit), and two helpers:
#   counts <block> <before|after> <file.sql>   a read-only query from ops/, printed and kept in out/<script>/
#   step <label> <lawgraph args...>              one lawgraph command, its log in out/<script>/; exits on failure
OPS=$(cd "$(dirname "$0")" && pwd)
OUT="$OPS/out/$(basename "$0" .sh)"
cd /srv/lawgraph/app || exit 1
set -a && . /srv/lawgraph/scheduler.env && set +a
mkdir -p "$OUT"
L=.venv/bin/lawgraph

until [ -z "$(systemctl list-units --state=activating,active,deactivating --no-legend 'lawgraph-*.service' | grep -v lawgraph-api)" ]; do sleep 15; done
LOCK="${TMPDIR:-/tmp}/lawgraph-scheduled.lock"
until mkdir "$LOCK" 2>/dev/null; do echo "$(date -u +%T) lock held, waiting"; sleep 30; done
trap 'rmdir "$LOCK"' EXIT
trap 'exit 130' INT TERM
echo "== lock $LOCK taken $(date -u +%T), version $(curl -s http://127.0.0.1:8000/api/health | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')"

counts() {
  docker exec -i -e PGOPTIONS='-c default_transaction_read_only=on' lawgraph-postgres \
    psql -X -U lawgraph -d lawgraph < "$OPS/$3" > "$OUT/$1-$2.txt" 2>&1
  echo "== $1 counts $2 rc $?"
  cat "$OUT/$1-$2.txt"
}
step() {
  label="$1"; shift
  start=$(date +%s)
  echo "== $label start $(date -u +%T)"
  $L "$@" < /dev/null > "$OUT/$label.log" 2>&1
  rc=$?
  grep -E "Done in|Failed after|ERROR" "$OUT/$label.log" | tail -3 | cut -c1-200
  echo "== $label rc $rc after $(( $(date +%s) - start )) s"
  [ $rc -eq 0 ] || exit $rc
}
