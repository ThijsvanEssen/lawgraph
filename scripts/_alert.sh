# shellcheck shell=sh
# Sourced from the root of the app (where .venv is) by the scheduled scripts and the ops scripts:
#   alert <message>   runs LAWGRAPH_ALERT_COMMAND with `sh -c`, the message in LAWGRAPH_ALERT_MESSAGE, e.g.
#                     `curl -s -d "$LAWGRAPH_ALERT_MESSAGE" ntfy.sh/<topic>`; its exit code is the command's
#   tell <script...>  alerts what the record on stdin says, in one line of fixed form (python -m lawgraph.alert,
#                     docs/operations.md "Alerts"); the record as it is when that cannot be made
alert() {
  [ -n "$LAWGRAPH_ALERT_COMMAND" ] || return 0
  LAWGRAPH_ALERT_MESSAGE="$1" sh -c "$LAWGRAPH_ALERT_COMMAND"
}
tell() {
  [ -n "$LAWGRAPH_ALERT_COMMAND" ] || return 0
  record=$(cat)
  said=$(printf '%s\n' "$record" | .venv/bin/python -m lawgraph.alert "$@" 2>>"${LAWGRAPH_LOG_FILE:-/dev/null}") \
    || said="lawgraph $*: $(printf '%s' "$record" | tr '\t\n' ' ;')"
  alert "$said"
}
