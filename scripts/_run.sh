# Shared by daily.sh and weekly.sh: one run at a time, one log per run, one line per outcome.
# Sourced, not run.
cd "$(dirname "$0")/.." || exit 1
LOG_DIR="${LAWGRAPH_LOG_DIR:-$HOME/Library/Logs/lawgraph}"
mkdir -p "$LOG_DIR"
export LAWGRAPH_LOG_FILE="$LOG_DIR/$(basename "$0" .sh)-$(date +%Y-%m-%d).log"

# `mkdir` either makes the directory or fails: two scheduled runs never write side by side.
LOCK="${TMPDIR:-/tmp}/lawgraph-scheduled.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "$(date '+%F %T') $(basename "$0"): another scheduled run holds $LOCK; not started" >> "$LOG_DIR/runs.log"
  exit 75
fi
trap 'rmdir "$LOCK"' EXIT

# macOS: keep the machine from idle sleep while a command runs. A closed lid on battery
# still sleeps (the run then pauses until the next wake); nothing here can change that.
AWAKE=""
command -v caffeinate >/dev/null 2>&1 && AWAKE="caffeinate -i"

failed=0
failures=""
step() {  # run one command; a failure is remembered and the next one still runs
  $AWAKE .venv/bin/lawgraph "$@" || {
    failed=1
    failures="${failures:+$failures; }lawgraph $*"
    echo "$(date '+%F %T') $(basename "$0"): lawgraph $* failed" >> "$LOG_DIR/runs.log"
  }
}
# A failed run is told to whoever should know: LAWGRAPH_ALERT_COMMAND is run by `sh -c` with
# the message in LAWGRAPH_ALERT_MESSAGE, e.g. `curl -s -d "$LAWGRAPH_ALERT_MESSAGE" ntfy.sh/<topic>`
# or `mail -s lawgraph me@example.org <<< "$LAWGRAPH_ALERT_MESSAGE"`.
alert() {
  [ -n "$LAWGRAPH_ALERT_COMMAND" ] || return 0
  LAWGRAPH_ALERT_MESSAGE="$1" sh -c "$LAWGRAPH_ALERT_COMMAND" \
    || echo "$(date '+%F %T') $(basename "$0"): the alert command failed" >> "$LOG_DIR/runs.log"
}
finish() {
  echo "$(date '+%F %T') $(basename "$0"): $([ $failed -eq 0 ] && echo ok || echo FAILED) (log: $LAWGRAPH_LOG_FILE)" >> "$LOG_DIR/runs.log"
  [ $failed -eq 0 ] || alert "lawgraph $(basename "$0") on $(hostname) FAILED: $failures (log: $LAWGRAPH_LOG_FILE)"
  exit $failed
}
