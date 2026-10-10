#!/bin/sh
# Every week: link everything again, then fetch what the graph refers to and lacks.
# The full semantic steps come first: a text loaded long ago can name a law loaded this week, and what it names
# and is missing is what `expand-graph` then fetches.
#
# Step by step, each under the lock on its own (scripts/step.sh), so the polls run in between: the run as a whole
# takes hours, one step minutes. The steps are those of `semantic all`, in its order (`semantic all --list`), but:
# - rechtspraak-citations is left to the daily run: a judgment cited by ECLI that is not loaded yet is a stub the
#   edge already reaches, and fills when it comes; the run over all (1h58m) adds nothing new each week;
# - rechtspraak (the article citations: a law loaded this week takes its citations over) and bwb-definitions go
#   in slices of RECHTSPRAAK_SLICE judgments (default 100000) and DEFINITIONS_SLICE regulations (default 5000).
# A failing step does not stop the run; at the end the failures are told through the alert, as _run.sh does.
cd "$(dirname "$0")/.." || exit 1
LOG_DIR="${LAWGRAPH_LOG_DIR:-$HOME/Library/Logs/lawgraph}"
mkdir -p "$LOG_DIR"
failures=""
run() {  # run <lawgraph args...>: one step under the lock; a failure is remembered, a skip (75) noted
  sh scripts/step.sh "$@"
  rc=$?
  [ $rc -eq 0 ] || [ $rc -eq 75 ] || failures="${failures:+$failures; }lawgraph $*"
  return $rc
}
slices() {  # slices <semantic step> <size>: its run over all, slice by slice, until one reads nothing
  after=""
  n=0
  while :; do
    n=$((n + 1))
    if [ "$n" -gt "${MAX_SLICES:-200}" ]; then  # a run over all is far fewer slices
      failures="${failures:+$failures; }lawgraph semantic $1: more than ${MAX_SLICES:-200} slices"
      return 1
    fi
    # the output is read for where to go on: in this shell, not in the subshell of $(…)
    out=$(sh scripts/step.sh semantic "$1" ${after:+--after "$after"} --limit "$2" 2>&1)
    rc=$?
    printf '%s\n' "$out"
    if [ $rc -ne 0 ]; then
      [ $rc -eq 75 ] || failures="${failures:+$failures; }lawgraph semantic $1 (after ${after:-the start})"
      return $rc
    fi
    next=$(printf '%s\n' "$out" | sed -n 's/.*go on with --after \([^)]*\)).*/\1/p' | tail -1)
    { [ -n "$next" ] && [ "$next" != None ]; } || return 0
    if [ "$next" = "$after" ]; then  # no step forward: the same slice again and again
      failures="${failures:+$failures; }lawgraph semantic $1: no progress after $after"
      return 1
    fi
    after=$next
  done
}

# The members, factions, their seats and vacant seats, which the daily run skips
# (`--skip-members`): a new seat or vacancy shows within a week. A short step.
run retrieve tk-dossiers --since 1d --skip-decisions --skip-documents
run normalize tk-dossiers --since 1d
# The pages of the sitting members of the Eerste Kamer again, and their periods in its
# factions (a change the daily run fetches names the members it is about; a page can change
# without one). Minutes.
run retrieve eerstekamer-persons --sitting
run normalize eerstekamer-persons
for name in $(.venv/bin/lawgraph semantic all --list); do
  case "$name" in
    rechtspraak-citations) ;;
    rechtspraak) slices rechtspraak "${RECHTSPRAAK_SLICE:-100000}" ;;
    bwb-definitions) slices bwb-definitions "${DEFINITIONS_SLICE:-5000}" ;;
    *) run semantic "$name" ;;
  esac
done
run expand-graph
run check

if [ -n "$failures" ]; then
  echo "$(date '+%F %T') weekly.sh: FAILED: $failures" >> "$LOG_DIR/runs.log"
  [ -z "$LAWGRAPH_ALERT_COMMAND" ] || LAWGRAPH_ALERT_MESSAGE="lawgraph weekly.sh on $(hostname) FAILED: $failures" sh -c "$LAWGRAPH_ALERT_COMMAND"
  exit 1
fi
echo "$(date '+%F %T') weekly.sh: ok" >> "$LOG_DIR/runs.log"
