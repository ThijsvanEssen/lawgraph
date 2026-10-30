#!/bin/sh
# Every day: what the sources changed since the last complete run of each phase.
# `--since last` goes on where that run began, so a day without a run is caught up.
. "$(dirname "$0")/_run.sh"

step retrieve all --since last
step normalize all --since last
step semantic all --since last
step feed-events
step check --skip-edges
step search-stats prune
step search-candidates
# The sitemaps read the graph and write files: outside the lock, so the polls need not wait.
unlock
step sitemaps
# Last, so what the nightly run read does not push it out: what the search reads, into memory.
step prewarm
finish
