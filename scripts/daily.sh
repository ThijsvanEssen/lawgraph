#!/bin/sh
# Every day: what the sources changed since the last complete run of each phase.
# `--since last` goes on where that run began, so a day without a run is caught up.
. "$(dirname "$0")/_run.sh"

step retrieve all --since last
step normalize all --since last
step semantic all --since last
step check --skip-edges
finish
