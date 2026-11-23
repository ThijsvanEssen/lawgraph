#!/bin/sh
# At night, once after the deploy of 0.80.45 (B189, #1229: lg_amounts and /amounts), in slices that each take the lock
# and let it go, so the polls and the nightly run in between; over as many nights as it needs:
# 1. `normalize bwb` over every toestand: the space around an added redaction and `redactions` on every article;
#    slices of 15000 toestanden, about 13 minutes each;
# 2. `normalize bwb-history` over every toestand: `redactions` on every ArticleVersion; slices of at least
#    HISTORY_LIMIT (default 2000) toestanden, whole regulations;
#    both through renormalize-bwb-slice.sh, which makes a slice that took more than 25 minutes smaller;
# 3. `semantic bwb-amounts` over every regulation (after-0.80.45-amounts.sh): slices of AMOUNTS_SLICE (default 5000)
#    regulations, minutes each.
# Goes on where it stopped (out/after-0.80.45-*.after); stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
# no $(...) here: its subshell would show up with the command line of this script
if pgrep -f '^sh (.*/)?after-0\.80\.45\.sh$' | grep -vqx "$$"; then
  echo "== a pass is running; nothing started"
  exit 1
fi
normalize_pass() {  # normalize_pass <step> <toestanden per slice>
  until [ "$(cat "$D/out/after-0.80.45-$1.after" 2>/dev/null)" = "done" ]; do
    wait_night
    PASS="after-0.80.45-$1" NORMALIZE="$1" LIMIT="$2" COUNTS="" sh "$D/renormalize-bwb-slice.sh" \
      || fail renormalize-bwb-slice $?
  done
}
normalize_pass bwb 15000
normalize_pass bwb-history "${HISTORY_LIMIT:-2000}"
until [ "$(cat "$D/out/after-0.80.45-amounts.after" 2>/dev/null)" = "done" ]; do
  wait_night
  sh "$D/after-0.80.45-amounts.sh" || fail after-0.80.45-amounts $?
done
echo "== all done $(date -u +%T)"
