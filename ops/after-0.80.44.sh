#!/bin/sh
# Once after the deploy of 0.80.44, under the lock of the scheduled runs:
# - normalize cbs: a year of CBS without a district (2027, all ".") leaves lg_court_districts (#1215, B182);
# - semantic tk-amends over every paper, then tk-amendment-articles: a bill whose title names no law amends the
#   laws of its parts (#1213, B175). The weekly does the same.
. "$(dirname "$0")/_steps.sh"
step 1-normalize-cbs normalize cbs
step 2-tk-amends semantic tk-amends
step 3-tk-amendment-articles semantic tk-amendment-articles
echo "== all done $(date -u +%T)"
