#!/bin/sh
# smoke.sh <base URL> [version]: the routes a visitor hits first, each within its time budget.
# Run by the deploy after the API has warmed up, against the public address
# (e.g. https://concordans.nl); exits 1 when a route fails, is too slow, or the API
# reports another version than the one given.
base="${1:?usage: smoke.sh <base URL> [version]}"
version="$2"
failed=0

check() {  # check <budget in seconds> <path>
  budget="$1"
  path="$2"
  out=$(curl -s -o /dev/null -m 60 -w '%{http_code} %{time_total}' "$base$path") || out="000 60"
  code=${out% *}
  secs=${out#* }
  if [ "$code" != 200 ]; then
    echo "[smoke] FAIL $path: HTTP $code after ${secs}s"
    failed=1
  elif awk -v t="$secs" -v b="$budget" 'BEGIN { exit !(t > b) }'; then
    echo "[smoke] FAIL $path: ${secs}s, budget ${budget}s"
    failed=1
  else
    echo "[smoke] ok   $path: ${secs}s (budget ${budget}s)"
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
