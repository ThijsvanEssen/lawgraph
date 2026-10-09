#!/bin/sh
# One lawgraph command under the lock of the scheduled runs (_run.sh), taken for that command alone: the weekly
# run goes step by step through this, so a poll runs in between. A running poll is waited for, an hour at most
# (LAWGRAPH_LOCK_WAIT); after that the step is skipped (exit 75) and says so in runs.log.
: "${LAWGRAPH_LOCK_WAIT:=3600}"
export LAWGRAPH_LOCK_WAIT
. "$(dirname "$0")/_run.sh"
step "$@"
finish
