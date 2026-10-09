#!/bin/sh
# The steps of tk-members.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
counts vacancies before faction-vacancies-counts.sql
since=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
echo "== since $since"
step m1-retrieve-tk-dossiers-members retrieve tk-dossiers --since 1h --skip-decisions --skip-documents
step m2-normalize-tk-dossiers normalize tk-dossiers --since "$since"
counts vacancies after faction-vacancies-counts.sql
echo "== all done $(date -u +%T)"
