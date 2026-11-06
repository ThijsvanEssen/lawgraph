#!/bin/sh
# Once: the judgments the renormalize pass of renormalize-rvs.sh read before 0.80.27 (29 and 30 Oct, the keys up to
# UNTIL of the slice script, about 57,000) normalized again, so they keep props.law_references, the jci references of
# their metadata (#1084); `semantic rechtspraak` of the weekly links them. In slices (renormalize-judgments-head-slice.sh),
# each under the lock on its own, at night (03:00-07:00 Europe/Amsterdam). Goes on where it stopped
# (out/renormalize-judgments-head.after); stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
STATE="$D/out/renormalize-judgments-head.after"
until [ "$(cat "$STATE" 2>/dev/null)" = done ]; do
  wait_night
  echo "######## head slice after $(cat "$STATE" 2>/dev/null || echo the start) start $(date -u +%T)"
  sh "$D/renormalize-judgments-head-slice.sh" || fail renormalize-judgments-head-slice $?
done
echo "== head all done $(date -u +%T)"
