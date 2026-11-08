#!/bin/sh
# Once, after the nightly (03:00-07:00 Europe/Amsterdam): the data runs the releases 0.80.30-0.80.32 left, each a
# script of its own under its own lock, so a poll can run in between:
# - ek-old-dossiers.sh: `normalize eerstekamer` over every paper, then `semantic eerstekamer`: the copy of a paper an
#   earlier run left goes (#1033; 36702 A is there twice);
# - backfill-0.80.30-bwb-steps.sh: `semantic bwb` over every toestand, for the REFERS_TO of an article to a whole law
#   (#1111, about 13 minutes);
# - renormalize-judgments-head.sh: the judgments read before 0.80.27 normalized again for props.law_references (#1084).
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/ek-old-dossiers.sh" || fail ek-old-dossiers $?
sh "$D/backfill-0.80.30-bwb-steps.sh" || fail backfill-0.80.30-bwb-steps $?
sh "$D/renormalize-judgments-head.sh" || exit $?
echo "== all done $(date -u +%T)"
