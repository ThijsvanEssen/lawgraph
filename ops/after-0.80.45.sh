#!/bin/sh
# At night, once after the deploy of 0.80.45 (B189, #1229: lg_amounts and /amounts), each unit under the lock on its
# own, so the polls and the nightly run in between:
# 1. `normalize bwb` over every toestand (renormalize-bwb-slice.sh, PASS=after-0.80.45-bwb): the space around an added
#    redaction and `redactions` on every article; slices of 15000 toestanden, about 13 minutes each;
# 2. `normalize bwb-history` in full (after-0.80.45-history.sh): `redactions` on every ArticleVersion. It has no
#    slices: one step that holds the lock throughout, started only from NOT_BEFORE to HISTORY_BY (default 04)
#    Europe/Amsterdam, so it ends before the day;
# 3. `semantic bwb-amounts` over every regulation (after-0.80.45-amounts.sh): slices of AMOUNTS_SLICE (default 5000)
#    regulations, minutes each.
# Goes on where it stopped (out/after-0.80.45.phase); stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
PHASE="$D/out/after-0.80.45.phase"
# no $(...) here: its subshell would show up with the command line of this script
if pgrep -f '^sh (.*/)?after-0\.80\.45\.sh$' | grep -vqx "$$"; then
  echo "== a pass is running; nothing started"
  exit 1
fi
mkdir -p "$D/out"
phase() { cat "$PHASE" 2>/dev/null || echo bwb; }
night_by() {  # wait_night, but start no later than the hour $1
  until=$to
  to=$1
  wait_night
  to=$until
}
if [ "$(phase)" = bwb ]; then
  until [ "$(cat "$D/out/after-0.80.45-bwb.after" 2>/dev/null)" = "done" ]; do
    wait_night
    PASS=after-0.80.45-bwb COUNTS="" sh "$D/renormalize-bwb-slice.sh" || fail renormalize-bwb-slice $?
  done
  echo history > "$PHASE"
fi
if [ "$(phase)" = history ]; then
  night_by "${HISTORY_BY:-04}"
  sh "$D/after-0.80.45-history.sh" || fail after-0.80.45-history $?
  echo amounts > "$PHASE"
fi
if [ "$(phase)" = amounts ]; then
  until [ "$(cat "$D/out/after-0.80.45-amounts.after" 2>/dev/null)" = "done" ]; do
    wait_night
    sh "$D/after-0.80.45-amounts.sh" || fail after-0.80.45-amounts $?
  done
  echo done > "$PHASE"
fi
echo "== all done $(date -u +%T)"
