#!/bin/sh
# The backfill of the XML of the Tweede Kamer papers night after night: one step a night (tk-backfill-steps.sh, at most
# TK_MINUTES minutes under the lock), after the other night steps (a slice of a renormalize pass, ek-old-dossiers.sh,
# backfill-0.80.30-bwb-steps.sh: it waits until none of them has run for two minutes), until `retrieve tk-content` has
# nothing left to do. A step refuses when /srv/lawgraph is fuller than DISK_MAX_PCT (here 88) and the loop stops with the
# alert. stop-tk-backfill.sh stops the loop before its next night; a step that runs goes to its end.
. "$(dirname "$0")/_night.sh"
DISK_MAX_PCT=${DISK_MAX_PCT:-88}
export DISK_MAX_PCT
STOP="$D/out/tk-backfill-nights.stop"
STEP_LOG="$D/out/tk-backfill-steps/t1-retrieve-tk-content.log"
OTHERS='ek-old-dossiers\.sh|backfill-0\.80\.30-bwb-steps\.sh|-slice\.sh'
rm -f "$STOP"
night=0
while :; do
  wait_night
  sleep 300
  idle=0
  until [ $idle -ge 2 ]; do
    if pgrep -f "$OTHERS" > /dev/null; then idle=0; else idle=$((idle + 1)); fi
    sleep 60
  done
  [ -e "$STOP" ] && { echo "== stopped by stop-tk-backfill.sh after $night nights $(date -u +%T)"; exit 0; }
  night=$((night + 1))
  echo "######## night $night start $(date -u '+%F %T')"
  sh "$D/tk-backfill-steps.sh" || fail tk-backfill-steps $?
  if grep -q "Done in .*nothing to do" "$STEP_LOG"; then
    echo "== all done after $night nights $(date -u +%T)"
    exit 0
  fi
  until h=$(TZ=Europe/Amsterdam date +%H); [ "$h" -ge "$to" ] || [ "$h" -lt "$from" ]; do sleep 600; done
done
