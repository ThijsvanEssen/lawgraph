#!/bin/sh
# The steps of ek-persons.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
counts persons before ek-persons-counts.sql
step e1-retrieve-eerstekamer-persons retrieve eerstekamer-persons
step e2-normalize-eerstekamer-persons normalize eerstekamer-persons
counts persons after ek-persons-counts.sql
echo "== all done $(date -u +%T)"
