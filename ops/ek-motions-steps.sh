#!/bin/sh
# The steps of ek-motions.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
counts motions before ek-motions-counts.sql
step m1-retrieve-eerstekamer-motions retrieve eerstekamer-motions
step m2-normalize-eerstekamer-motions normalize eerstekamer-motions
counts motions after ek-motions-counts.sql
echo "== all done $(date -u +%T)"
