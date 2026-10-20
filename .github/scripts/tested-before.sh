#!/bin/sh
# Were these files already tested? Usage: tested-before.sh WORKFLOW (e.g. tests.yaml).
#
# Exits 0 when a run of WORKFLOW that counts finished green (green-on.sh, which waits for a run
# still going), and exits 1 otherwise, and the caller runs the suite itself. HEAD is the commit
# under test, checked out with its parents (fetch-depth: 2). What counts:
#   a push to develop               the merge commit of a pull request: the pull_request run of
#                                   its second parent (the head) when it has the same tree (the
#                                   branch already held develop); or the run of the push of its
#                                   first parent when HEAD is only a version bump of it
#   a pull request into develop     the merge ref (tests.yaml asks only on a branch bump-*): the
#                                   run of the push of its first parent (the tip of develop)
#                                   when HEAD is only a version bump of it (version-bump.sh)
#   a pull request from main-X.Y.Z  the merge ref: the run of the push of its second parent (the
#                                   develop commit) when it has the same tree
#   a push to main                  the merge commit: the same, of its second parent
# Needs GH_TOKEN (actions: read), GITHUB_REPOSITORY, GITHUB_EVENT_NAME, GITHUB_REF and, on a
# pull request, GITHUB_BASE_REF and GITHUB_HEAD_REF.
set -u
workflow=$1
here=$(dirname "$0")

same_tree() {  # same_tree EVENT [BRANCH]: a parent with the files of HEAD, green
  tree=$(git rev-parse 'HEAD^{tree}') || return 1
  for parent in $(git rev-list --parents -n 1 HEAD | cut -d' ' -f2-); do
    if [ "$(git rev-parse "$parent^{tree}")" != "$tree" ]; then
      echo "$parent: other files"
      continue
    fi
    "$here/green-on.sh" "$workflow" "$parent" "$@" && return 0
  done
  return 1
}

bump_of_develop() {  # HEAD is a version bump of its first parent, green on develop
  "$here/version-bump.sh" HEAD^1 && "$here/green-on.sh" "$workflow" "$(git rev-parse HEAD^1)" push develop
}

case "$GITHUB_EVENT_NAME $GITHUB_REF" in
  "push refs/heads/develop") same_tree pull_request || bump_of_develop ;;
  "push "*) same_tree push develop ;;
  *)
    case "${GITHUB_HEAD_REF:-}" in
      main-*) same_tree push develop ;;
      *) [ "${GITHUB_BASE_REF:-}" = develop ] && bump_of_develop ;;
    esac ;;
esac && exit 0
echo "not tested before: the suite runs here"
exit 1
