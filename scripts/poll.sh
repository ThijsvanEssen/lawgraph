#!/bin/sh
# Between the nightly runs: what one source published lately, up to the feed.
#   poll.sh <tk|ek|rechtspraak|echr> [window]
# The window reaches back past the poll before it (and the nightly run before the first poll
# of a day), so that polls overlap; everything is an upsert. Under the lock of the other
# scheduled runs: a poll that finds one running exits 75 and leaves it to the next poll.
case "$1" in
  tk) window=4h ;;           # every 30 minutes on working days; the first at 08:00
  ek) window=4h ;;           # Tuesday afternoon, after the votes of the Eerste Kamer
  rechtspraak) window=6h ;;  # every hour on working days; the first at 09:15
  echr) window=1d ;;         # Tuesday and Thursday, after the judgments of 10:00
  *)
    echo "usage: $0 <tk|ek|rechtspraak|echr> [window]" >&2
    exit 2
    ;;
esac
chain="$1"
window="${2:-$window}"
. "$(dirname "$0")/_run.sh"
export LAWGRAPH_LOG_FILE="$LOG_DIR/poll-$chain-$(date +%Y-%m-%d).log"

step poll "$chain" --since "$window"
finish
