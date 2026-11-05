#!/bin/sh
# After the deploy of 0.80.30 (#1108), once: `semantic verdragenbank` fills instruments.same_as (about a minute); until
# then the list shows a treaty with a BWB text twice. Waits for the API to report 0.80.30, so it can be started before
# the deploy; the step takes the lock of the scheduled runs through _steps.sh, after that wait.
until [ "$(curl -s http://127.0.0.1:8000/api/health | sed -n 's/.*"version":"\([^"]*\)".*/\1/p')" = "0.80.30" ]; do sleep 30; done
. "$(dirname "$0")/_steps.sh"
step 1-verdragenbank semantic verdragenbank
echo "== all done $(date -u +%T)"
