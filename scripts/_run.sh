# shellcheck shell=sh
# Shared by the scheduled scripts (daily, weekly, poll, step): one run at a time, one log per run, one line per outcome.
# Sourced, not run.
cd "$(dirname "$0")/.." || exit 1
LOG_DIR="${LAWGRAPH_LOG_DIR:-$HOME/Library/Logs/lawgraph}"
mkdir -p "$LOG_DIR"
LAWGRAPH_LOG_FILE="$LOG_DIR/$(basename "$0" .sh)-$(date +%Y-%m-%d).log"
export LAWGRAPH_LOG_FILE

# A failed run is told to whoever should know: LAWGRAPH_ALERT_COMMAND is run by `sh -c` with
# the message in LAWGRAPH_ALERT_MESSAGE, e.g. `curl -s -d "$LAWGRAPH_ALERT_MESSAGE" ntfy.sh/<topic>`
# or `mail -s lawgraph me@example.org <<< "$LAWGRAPH_ALERT_MESSAGE"`.
alert() {
  [ -n "$LAWGRAPH_ALERT_COMMAND" ] || return 0
  LAWGRAPH_ALERT_MESSAGE="$1" sh -c "$LAWGRAPH_ALERT_COMMAND" \
    || echo "$(date '+%F %T') $(basename "$0"): the alert command failed" >> "$LOG_DIR/runs.log"
}

# `mkdir` either makes the directory or fails: two scheduled runs never write side by side.
# LAWGRAPH_LOCK_WAIT seconds (default 0) a run waits for a run that holds the lock: the nightly
# waits out a poll that hangs, a poll gives its turn up at once.
LOCK="${TMPDIR:-/tmp}/lawgraph-scheduled.lock"
# Runs given up in a row, per script and chain (`poll.sh tk` apart from `poll.sh rechtspraak`): the
# third says so through the alert, once; a run that starts sets the count back.
RUN_NAME="$(basename "$0" .sh)${1:+ $1}"
SKIPPED="$LOG_DIR/skipped-$(basename "$0" .sh)${1:+-$1}"
waited=0
until mkdir "$LOCK" 2>/dev/null; do
  if [ "$waited" -ge "${LAWGRAPH_LOCK_WAIT:-0}" ]; then
    echo "$(date '+%F %T') $(basename "$0"): another scheduled run holds $LOCK; not started (waited ${waited} s)" >> "$LOG_DIR/runs.log"
    skipped=$(( $(cat "$SKIPPED" 2>/dev/null || echo 0) + 1 ))
    echo "$skipped" > "$SKIPPED"
    [ "$skipped" -ne 3 ] || alert "lawgraph $RUN_NAME on $(hostname) skipped 3 times in a row: another run holds $LOCK"
    exit 75
  fi
  sleep 1
  waited=$((waited + 1))
done
[ "$waited" -eq 0 ] || echo "$(date '+%F %T') $(basename "$0"): started after waiting ${waited} s for $LOCK" >> "$LOG_DIR/runs.log"
# Why a command ended as it did, in one line (cut at 300 characters; the log has it all): lawgraph writes it here.
OUTCOME="${TMPDIR:-/tmp}/lawgraph-outcome-$$"
trap 'rmdir "$LOCK"; rm -f "$OUTCOME"' EXIT
rm -f "$SKIPPED"

# macOS: keep the machine from idle sleep while a command runs. A closed lid on battery
# still sleeps (the run then pauses until the next wake); nothing here can change that.
AWAKE=""
command -v caffeinate >/dev/null 2>&1 && AWAKE="caffeinate -i"

failed=0
failures=""
unavailable=""
run() {  # run <label> <command...>: a failure is remembered and the next one still runs
  label="$1"
  shift
  rm -f "$OUTCOME"
  LAWGRAPH_OUTCOME_FILE="$OUTCOME" "$@"
  rc=$?
  why=$(cat "$OUTCOME" 2>/dev/null)
  if [ $rc -eq 3 ]; then  # EXIT_UNAVAILABLE: a source refused us, the rest went on; told, not failed
    unavailable="${unavailable:+$unavailable; }$label${why:+: $why}"
    echo "$(date '+%F %T') $(basename "$0"): $label: a source was unavailable${why:+: $why}" >> "$LOG_DIR/runs.log"
  elif [ $rc -ne 0 ]; then
    failed=1
    failures="${failures:+$failures; }$label: ${why:-exit code $rc}"
    echo "$(date '+%F %T') $(basename "$0"): $label failed: ${why:-exit code $rc}" >> "$LOG_DIR/runs.log"
  fi
}
step() {  # one lawgraph command, kept awake
  # shellcheck disable=SC2086  # AWAKE is a command and its flag, or nothing
  run "lawgraph $*" $AWAKE .venv/bin/lawgraph "$@"
}
note() {  # one line in runs.log
  echo "$(date '+%F %T') $(basename "$0"): $*" >> "$LOG_DIR/runs.log"
}
finish() {
  echo "$(date '+%F %T') $(basename "$0"): $([ $failed -eq 0 ] && echo ok || echo FAILED) (log: $LAWGRAPH_LOG_FILE)" >> "$LOG_DIR/runs.log"
  if [ $failed -ne 0 ]; then
    alert "lawgraph $(basename "$0") on $(hostname) FAILED: $failures${unavailable:+; source unavailable: $unavailable} (log: $LAWGRAPH_LOG_FILE)"
  elif [ -n "$unavailable" ]; then
    alert "lawgraph $(basename "$0") on $(hostname): source unavailable: $unavailable (log: $LAWGRAPH_LOG_FILE)"
  fi
  exit $failed
}
