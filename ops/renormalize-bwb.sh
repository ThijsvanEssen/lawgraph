#!/bin/sh
# Every regulation normalized again from its stored toestand XML (`normalize bwb` over all, no --since), so it keeps
# its preamble (props.preamble, the aanhef of the law page). In slices of LIMIT toestanden (default 15000, about 13
# minutes at the 20 per second of the run of 13 Oct), each under the lock on its own so a poll can run in between,
# at night: from NOT_BEFORE (default 03) to NOT_AFTER (default 07), Europe/Amsterdam. The slice that reaches the end
# also does the WTI pass and the series. Goes on where it stopped (out/renormalize-bwb.after); stops at the first
# failure and says so through the alert. Measure with bwb-preamble-counts.sql.
# Stop: stop-renormalize-bwb.sh (the slice that runs goes to its end); start again with the same command. A new
# pass: remove out/renormalize-bwb.after once the old one is done. Refuses while a pass is running.
. "$(dirname "$0")/_night.sh"
STATE="$D/out/renormalize-bwb.after"
# no $(...) here: its subshell would show up with the command line of this script
if pgrep -f '^sh (.*/)?renormalize-bwb(-slice)?\.sh$' | grep -vqx "$$"; then
  echo "== a pass is running; nothing started"
  exit 1
fi
until [ "$(cat "$STATE" 2>/dev/null)" = "done" ]; do
  wait_night
  echo "######## slice after $(cat "$STATE" 2>/dev/null || echo the start) start $(date -u +%T)"
  sh "$D/renormalize-bwb-slice.sh"
  rc=$?
  echo "######## slice rc $rc end $(date -u +%T)"
  [ $rc -eq 0 ] || fail renormalize-bwb-slice $rc
done
echo "== all done $(date -u +%T)"
