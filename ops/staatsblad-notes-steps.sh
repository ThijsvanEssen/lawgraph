#!/bin/sh
# The steps of staatsblad-notes.sh, under the lock.
. "$(dirname "$0")/_steps.sh"
counts staatsblad before staatsblad-counts.sql
step s1-normalize-staatsblad normalize staatsblad
step s2-semantic-staatsblad semantic staatsblad
counts staatsblad after staatsblad-counts.sql
echo "== all done $(date -u +%T)"
