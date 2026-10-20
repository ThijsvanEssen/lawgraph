# shellcheck shell=sh
# Shared by the scheduled scripts (daily, weekly, poll, step): one run at a time, one log per run, one line per outcome.
# Sourced, not run.
cd "$(dirname "$0")/.." || exit 1
LOG_DIR="${LAWGRAPH_LOG_DIR:-$HOME/Library/Logs/lawgraph}"
mkdir -p "$LOG_DIR"
LAWGRAPH_LOG_FILE="$LOG_DIR/$(basename "$0" .sh)-$(date +%Y-%m-%d).log"
export LAWGRAPH_LOG_FILE

# A failed run is told to whoever should know, in one line of fixed form (_alert.sh). What did not end well is kept in a
# record, a line per step (kind, command line, reason; lawgraph.alert says how): the run tells it at the end. A
# step of the weekly run adds to the record of that run (LAWGRAPH_RUN_RECORD), which tells it at its end.
. scripts/_alert.sh
told() {  # told <script...> < record: the alert, and a line in runs.log when its command failed
  tell "$@" || echo "$(date '+%F %T') $(basename "$0"): the alert command failed" >> "$LOG_DIR/runs.log"
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
    # shellcheck disable=SC2086  # the script and its chain, two words
    [ "$skipped" -ne 3 ] || printf 'held\t\t%s\n' "$skipped" | told $RUN_NAME
    exit 75
  fi
  sleep 1
  waited=$((waited + 1))
done
[ "$waited" -eq 0 ] || echo "$(date '+%F %T') $(basename "$0"): started after waiting ${waited} s for $LOCK" >> "$LOG_DIR/runs.log"
# Why a command ended as it did, in one line (cut at 300 characters; the log has it all): lawgraph writes it here.
OUTCOME="${TMPDIR:-/tmp}/lawgraph-outcome-$$"
RECORD="${LAWGRAPH_RUN_RECORD:-${TMPDIR:-/tmp}/lawgraph-record-$$}"
[ -n "$LAWGRAPH_RUN_RECORD" ] || : > "$RECORD"
trap 'rmdir "$LOCK"; rm -f "$OUTCOME"; [ -n "$LAWGRAPH_RUN_RECORD" ] || rm -f "$RECORD"' EXIT
rm -f "$SKIPPED"

# macOS: keep the machine from idle sleep while a command runs. A closed lid on battery
# still sleeps (the run then pauses until the next wake); nothing here can change that.
AWAKE=""
command -v caffeinate >/dev/null 2>&1 && AWAKE="caffeinate -i"

failed=0
unavailable=""
run() {  # run <label> <command...>: a failure is remembered and the next one still runs
  label="$1"
  shift
  rm -f "$OUTCOME"
  LAWGRAPH_OUTCOME_FILE="$OUTCOME" "$@"
  rc=$?
  why=$(cat "$OUTCOME" 2>/dev/null)
  if [ $rc -eq 3 ]; then  # EXIT_UNAVAILABLE: a source refused us, the rest went on; told, not failed
    unavailable=1
    printf 'unavailable\t%s\t%s\n' "$label" "$why" >> "$RECORD"
    echo "$(date '+%F %T') $(basename "$0"): $label: a source was unavailable${why:+: $why}" >> "$LOG_DIR/runs.log"
  elif [ $rc -ne 0 ]; then
    failed=1
    printf 'failed\t%s\t%s\n' "$label" "${why:-exit code $rc}" >> "$RECORD"
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
  if [ -z "$LAWGRAPH_RUN_RECORD" ] && { [ $failed -ne 0 ] || [ -n "$unavailable" ]; }; then
    # shellcheck disable=SC2086  # the script and its chain, two words
    told $RUN_NAME < "$RECORD"
  fi
  exit $failed
}
