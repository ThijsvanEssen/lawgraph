#!/bin/sh
# Was this code already tested on develop? Usage: tested-on-develop.sh WORKFLOW (e.g. tests.yaml).
#
# Exits 0 when a parent of HEAD has the same tree as HEAD (the same files, byte for byte) and the
# workflow's run for the push of that parent to develop finished green; a run still going is
# waited for, up to 40 minutes. Exits 1 otherwise, and the caller runs the suite itself.
#
# HEAD is the commit under test, checked out with its parents (fetch-depth: 2):
#   a pull request from main-X.Y.Z  the merge ref; its second parent is the develop commit
#   a push to main                  the merge commit; its second parent is the develop commit
# Needs GH_TOKEN (actions: read) and GITHUB_REPOSITORY.
set -u
workflow=$1
tree=$(git rev-parse 'HEAD^{tree}') || exit 1
for parent in $(git rev-list --parents -n 1 HEAD | cut -d' ' -f2-); do
  if [ "$(git rev-parse "$parent^{tree}")" != "$tree" ]; then
    echo "$parent: other files"
    continue
  fi
  for i in $(seq 80); do
    state=$(gh api "repos/$GITHUB_REPOSITORY/actions/workflows/$workflow/runs?head_sha=$parent&branch=develop&event=push" \
      -q '.workflow_runs | sort_by(.run_number) | last | if . == null then "none" else .status + " " + (.conclusion // "") end') \
      || { echo "$parent: no answer from the API"; break; }
    case "$state" in
      "completed success") echo "$parent: same files, $workflow green on develop"; exit 0 ;;
      completed*) echo "$parent: same files, $workflow on develop: $state"; break ;;
      # the push run may not exist yet a few seconds after the merge
      none) [ "$i" -le 4 ] || { echo "$parent: no run of $workflow on develop"; break; } ;;
    esac
    echo "$parent: $workflow on develop: $state; waiting"
    sleep 30
  done
done
echo "not tested on develop: the suite runs here"
exit 1
