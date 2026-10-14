#!/bin/sh
# Was this code already tested on develop? Usage: tested-on-develop.sh WORKFLOW (e.g. tests.yaml).
#
# Exits 0 when a parent of HEAD has the same tree as HEAD (the same files, byte for byte) and the
# workflow's run for the push of that parent to develop finished green (green-on.sh, which waits
# for a run still going). Exits 1 otherwise, and the caller runs the suite itself.
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
  "$(dirname "$0")/green-on.sh" "$workflow" "$parent" develop && exit 0
done
echo "not tested on develop: the suite runs here"
exit 1
