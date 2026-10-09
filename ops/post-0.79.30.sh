#!/bin/sh
# Post-deploy steps of 0.79.30 (#377, #378, #381, #383) under the lock of the
# scheduled runs, each block with its count script (read-only) before and after. Stops at the first
# failing step; the lock goes on exit. Outputs in out/post-0.79.30/.
. "$(dirname "$0")/_steps.sh"
# #377: the first full run of graph-article-terms (the side tables do not exist before it)
step j1-semantic-graph-article-terms semantic graph-article-terms
counts j after article-terms-check.sql

counts k before revises-check.sql
since_k=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
step k1-retrieve-tk-replacing retrieve tk --replacing --mode full
step k2-normalize-tk normalize tk --since "$since_k"
step k3-semantic-tk-dossier-relations semantic tk-dossier-relations
counts k after revises-check.sql

counts l before tk-amends-pattern-counts.sql
step l1-semantic-tk-amends semantic tk-amends
counts l after tk-amends-pattern-counts.sql

counts m before ek-motion-votes-counts.sql
step m1-retrieve-eerstekamer-votes retrieve eerstekamer-votes --mode full
step m2-normalize-eerstekamer-votes normalize eerstekamer-votes
step m3-semantic-tk-dossier-outcomes semantic tk-dossier-outcomes
counts m after ek-motion-votes-counts.sql
echo "== all done $(date -u +%T)"
