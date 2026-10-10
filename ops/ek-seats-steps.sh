#!/bin/sh
# The steps of ek-seats.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
counts ek before ek-seats-counts.sql
step e1-retrieve-kiesraad retrieve kiesraad
step e2-retrieve-eerstekamer-mutations retrieve eerstekamer-mutations
step e3-normalize-eerstekamer-mutations normalize eerstekamer-mutations
counts ek after ek-seats-counts.sql
echo "== all done $(date -u +%T)"
