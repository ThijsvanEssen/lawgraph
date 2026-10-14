#!/bin/sh
# Did a workflow finish green on a commit? Usage: green-on.sh WORKFLOW SHA [BRANCH]
#
# Exits 0 when the newest run of WORKFLOW (e.g. tests.yaml) for SHA finished green; with BRANCH,
# the run of the push of SHA to that branch. A run still going is waited for, up to WAIT_MINUTES
# (default 40); a run not there yet, for two minutes (it may not exist a few seconds after the
# push). Exits 1 when the run finished otherwise, when there is none, or when the API does not
# answer. Needs GH_TOKEN (actions: read) and GITHUB_REPOSITORY.
set -u
workflow=$1 sha=$2
query="head_sha=$sha${3:+&branch=$3&event=push}"
for i in $(seq "$(( ${WAIT_MINUTES:-40} * 2 ))"); do
  state=$(gh api "repos/$GITHUB_REPOSITORY/actions/workflows/$workflow/runs?$query" \
    -q '.workflow_runs | sort_by(.run_number) | last | if . == null then "none" else .status + " " + (.conclusion // "") end') \
    || { echo "$sha: no answer from the API"; exit 1; }
  case "$state" in
    "completed success") echo "$sha: $workflow green"; exit 0 ;;
    completed*) echo "$sha: $workflow $state"; exit 1 ;;
    none) [ "$i" -le 4 ] || { echo "$sha: no run of $workflow"; exit 1; } ;;
  esac
  echo "$sha: $workflow $state; waiting"
  sleep 30
done
echo "$sha: $workflow not done within ${WAIT_MINUTES:-40} minutes"
exit 1
