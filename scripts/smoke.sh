#!/bin/sh
# smoke.sh <base URL> [version]: the routes a visitor hits first, each within its time budget.
# Run by the deploy after the API has warmed up, against the public address
# (e.g. https://concordans.nl); exits 1 when a route fails, is too slow, or the API
# reports another version than the one given.
base="${1:?usage: smoke.sh <base URL> [version]}"
version="$2"
failed=0

# Right after a restart the caches are cold, so a route over its budget or failing gets one more
# try after RETRY_SECONDS (default 30): only a second miss fails the smoke test.
RETRY_SECONDS="${RETRY_SECONDS:-30}"

measure() {  # measure <budget in seconds> <path>: prints the verdict, returns 1 on a miss
  out=$(curl -s -o /dev/null -m 60 -w '%{http_code} %{time_total}' "$base$2") || out="000 60"
  code=${out% *}
  secs=${out#* }
  if [ "$code" != 200 ]; then
    verdict="HTTP $code after ${secs}s"
    return 1
  elif awk -v t="$secs" -v b="$1" 'BEGIN { exit !(t > b) }'; then
    verdict="${secs}s, budget ${1}s"
    return 1
  fi
  verdict="${secs}s (budget ${1}s)"
}

check() {  # check <budget in seconds> <path>
  if measure "$1" "$2"; then
    echo "[smoke] ok   $2: $verdict"
    return
  fi
  echo "[smoke] slow $2: $verdict; again in ${RETRY_SECONDS}s"
  sleep "$RETRY_SECONDS"
  if measure "$1" "$2"; then
    echo "[smoke] ok   $2: $verdict (second try)"
  else
    echo "[smoke] FAIL $2: $verdict (second try)"
    failed=1
  fi
}

check 2 /api/health
check 5 '/api/judgments?limit=20&facets=false'
check 10 '/api/search?q=awb'
check 5 '/api/feed?limit=1'
check 5 /api/articles/BWBR0001854/287

if [ -n "$version" ]; then
  live=$(curl -s -m 10 "$base/api/health" | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')
  if [ -z "$live" ]; then
    echo "[smoke] note /api/health names no version; not compared"
  elif [ "$live" != "$version" ]; then
    echo "[smoke] FAIL version: $live live, $version expected"
    failed=1
  else
    echo "[smoke] ok   version $live"
  fi
fi

exit $failed
