#!/bin/sh
# B143, the Verloop of a judgment: a new pass of `normalize rechtspraak` over every judgment, for
# judgment_metadata.procedures and judgment_metadata.relation_outcomes (psi:gevolg per earlier instance, #1149). As
# renormalize-rvs.sh: removes the key of the finished pass (out/renormalize-judgments.after) and runs
# renormalize-judgments.sh, in slices of about 25 minutes, each under the lock on its own, at night (03:00-07:00
# Europe/Amsterdam), counting with b143-fill-counts.sql before the first slice and after the last. Refuses while a
# pass is running. meta.source_outcome on the edges comes from the next `semantic rechtspraak-appeal` over all: the
# weekly run, or b143-fill-appeal.sh.
D=$(cd "$(dirname "$0")" && pwd)
if pgrep -f 'renormalize-judgments(-slice)?\.sh' > /dev/null; then
  echo "== a pass is running: $(pgrep -f 'renormalize-judgments(-slice)?\.sh' | tr '\n' ' '); nothing started"
  exit 1
fi
rm -f "$D/out/renormalize-judgments.after"
echo "== new pass for B143, key removed $(date -u +%T)"
export COUNTS_BLOCK=b143 COUNTS_SQL=b143-fill-counts.sql
exec sh "$D/renormalize-judgments.sh"
