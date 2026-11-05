#!/bin/sh
# Read only, no lock: how the site is used, as counts (usage-counts.py). DAYS back in the journal (default 30), and
# what the search terms hold. Each part writes to a file of out/usage-counts/ and is shown after it; a part that
# fails is said and the other still runs. Run outside the nightly: it streams the journal and reads the instruments.
set -a && . /srv/lawgraph/scheduler.env && set +a
D=$(dirname "$0")
OUT=/srv/lawgraph/ops/out/usage-counts
PY=/srv/lawgraph/app/.venv/bin/python
DAYS=${DAYS:-30}
STATS=${LAWGRAPH_SEARCH_STATS_DIR:-/srv/lawgraph/stats}
mkdir -p "$OUT"
rc=0
part() {  # part <name> <args of usage-counts.py...>
  name=$1; shift
  echo "== $name $(date -u '+%F %T') UTC"
  if nice -n 19 "$PY" "$D/usage-counts.py" "$@" > "$OUT/$name.txt" 2> "$OUT/$name.err"; then
    cat "$OUT/$name.txt"
  else
    echo "FAILED: $name"; tail -5 "$OUT/$name.err"; rc=1
  fi
}
part routes routes "$DAYS"
part terms terms "$STATS"
echo "== done $(date -u '+%F %T') UTC, rc $rc"
exit "$rc"
