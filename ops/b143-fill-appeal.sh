#!/bin/sh
# B143, after the pass of b143-fill.sh: `semantic rechtspraak-appeal` over all, once, at night after the nightly, so
# the edges APPEAL_OF, CONTINUES and REFERRED_BY get meta.source_outcome. One step of about an hour (52 to 77 minutes
# in the weekly runs): it has no slices, so it holds the lock that long. The weekly run does the same step; this is
# for when that should not wait. Refuses while the pass of b143-fill.sh is not done. Stops at a failure and says so
# through the alert.
. "$(dirname "$0")/_night.sh"
if [ "$(cat "$D/out/renormalize-judgments.after" 2>/dev/null)" != "done" ]; then
  echo "== the pass of b143-fill.sh is not done; nothing started"
  exit 1
fi
wait_night
sh "$D/b143-fill-appeal-steps.sh" || fail b143-fill-appeal-steps $?
