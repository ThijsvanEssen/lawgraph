#!/bin/sh
# Starts a new pass of `normalize rechtspraak` over all judgments, for the RvS outcome of 0.80.19: removes the key of
# the finished pass (out/renormalize-judgments.after) and runs renormalize-judgments.sh, which goes in slices of
# about 25 minutes, each under the lock on its own, at night (03:00-07:00 Europe/Amsterdam). Writes no data itself
# besides that key. Refuses while a pass is running. Measure with outcomes-counts.sql and rvs-outcome-counts.sql.
D=$(cd "$(dirname "$0")" && pwd)
if pgrep -f 'renormalize-judgments(-slice)?\.sh' > /dev/null; then
  echo "== a pass is running: $(pgrep -f 'renormalize-judgments(-slice)?\.sh' | tr '\n' ' '); nothing started"
  exit 1
fi
rm -f "$D/out/renormalize-judgments.after"
echo "== new pass, key removed $(date -u +%T)"
exec sh "$D/renormalize-judgments.sh"
