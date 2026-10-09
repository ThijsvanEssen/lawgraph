#!/bin/sh
# #378 backfill, step 3 of 3: REVISES from each paper of a replacing case to the papers of the case it
# replaces (meta.rule vervanging), with the other relations of the step.
. "$(dirname "$0")/_steps.sh"
step r3-semantic-tk-dossier-relations semantic tk-dossier-relations
counts revises after revises-amendments-counts.sql
echo "== all done $(date -u +%T)"
