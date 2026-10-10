#!/bin/sh
# The steps of member-death-dates.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
counts members before member-death-dates-counts.sql
step p1-normalize-tk-persons normalize tk-dossiers --persons
counts members after member-death-dates-counts.sql
echo "== all done $(date -u +%T)"
