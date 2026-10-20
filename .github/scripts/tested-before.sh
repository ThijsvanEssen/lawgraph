#!/bin/sh
# Were exactly these files already tested? Usage: tested-before.sh WORKFLOW (e.g. tests.yaml).
#
# Exits 0 when a parent of HEAD has the same tree as HEAD (the same files, byte for byte) and the
# workflow's run on that parent finished green (green-on.sh, which waits for a run still going).
# Exits 1 otherwise, and the caller runs the suite itself.
#
# HEAD is the commit under test, checked out with its parents (fetch-depth: 2):
#   a push to develop               the merge commit of a pull request; its second parent is the
#                                   head of that pull request, whose pull_request run tested the
#                                   same files when the branch already held develop
#   a pull request from main-X.Y.Z  the merge ref; its second parent is the develop commit, whose
#                                   push run counts
#   a push to main                  the merge commit; its second parent is the develop commit
# Needs GH_TOKEN (actions: read), GITHUB_REPOSITORY, GITHUB_EVENT_NAME and GITHUB_REF.
set -u
workflow=$1
if [ "$GITHUB_EVENT_NAME $GITHUB_REF" = "push refs/heads/develop" ]; then
  set -- pull_request
else
  set -- push develop
fi
tree=$(git rev-parse 'HEAD^{tree}') || exit 1
for parent in $(git rev-list --parents -n 1 HEAD | cut -d' ' -f2-); do
  if [ "$(git rev-parse "$parent^{tree}")" != "$tree" ]; then
    echo "$parent: other files"
    continue
  fi
  "$(dirname "$0")/green-on.sh" "$workflow" "$parent" "$@" && exit 0
done
echo "not tested before: the suite runs here"
exit 1
