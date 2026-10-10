#!/bin/sh
# How long /api/search takes and what it waited for: read only, no lock (it only asks the API, as a visitor does).
# ROUNDS times (default 10), WAIT seconds apart (default 30): what the background threads compute at that moment
# (/api/health `busy`: the warm-up and the pool of the cache, by kind of answer, with their seconds), then three
# full searches, each timed with its `partial`:
#   new      a word no one searched before (one per round), so its frequencies are counted now
#   rare     an article number with letters (126ffa, 334vv, ...), another each round
#   common   a common word (bijstand, ontslag, ...), another each round
# Run it once right after a deploy or restart, during the warm-up, and once at a quiet hour; a slow search beside a
# busy "cache: bm25-stats" or "warm-up: search ..." says what it waited for. The searches count as search terms
# like any (search-stats); each is asked once, so none becomes a term the warm-up searches (5 asks or more).
RARE="126ffa 334vv 77wc 509jbis 51ab 7:669 13a 44bis 3:305a 8:69a"
COMMON="bijstand ontslag huurprijs vergunning bestemmingsplan aansprakelijkheid onteigening uitkering belasting asiel"
ROUNDS=${ROUNDS:-10}
WAIT=${WAIT:-30}
API=${API:-http://127.0.0.1:8000}
health() {
  curl -s --max-time 5 "$API/api/health" | python3 -c '
import json, sys
h = json.load(sys.stdin)
calls = ["%s %ss" % (b.get("call"), b.get("seconds")) for b in h.get("busy") or []]
pools = h.get("pools") or {}
print("warm=%s busy: %s; pools %s" % (h.get("warm"), ", ".join(calls) or "nothing", pools))
' 2>/dev/null || echo "health: no answer"
}
search() {  # search <label> <q>
  curl -s --max-time 40 -o /tmp/search-timing.json -w '%{http_code} %{time_total}' \
    "$API/api/search?mode=full&q=$2" | {
    read -r code took
    partial=$(python3 -c 'import json; print(",".join(sorted(json.load(open("/tmp/search-timing.json")).get("partial") or {})) or "-")' 2>/dev/null)
    echo "  $1 q=$2: $code ${took}s partial=$partial"
  }
}
echo "== $(date -u '+%F %T') UTC, release $(git -C /srv/lawgraph/app log --oneline -1 2>/dev/null | cut -c1-60)"
n=0
while [ "$n" -lt "$ROUNDS" ]; do
  n=$((n + 1))
  echo "-- round $n $(date -u +%T) $(health)"
  search new "zqx$(date +%s)$n"
  search rare "$(echo $RARE | cut -d' ' -f$(( (n - 1) % 10 + 1 )))"
  search common "$(echo $COMMON | cut -d' ' -f$(( (n - 1) % 10 + 1 )))"
  [ "$n" -lt "$ROUNDS" ] && sleep "$WAIT"
done
echo "== done $(date -u +%T)"
