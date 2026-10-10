#!/bin/sh
# Once after the deploy that keeps has_text with every paper in lg_document_light, at night: semantic graph-light
# --papers (every paper's light row again, reading its props once; the other light tables only where a row is
# missing); papers-light-counts.sql before and after; under the lock. Stops at a failure and says so through the
# alert. After it, the triggers keep has_text with every write of a paper.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/papers-light-steps.sh" || fail papers-light-steps $?
