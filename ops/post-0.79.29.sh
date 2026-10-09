#!/bin/sh
# Post-deploy steps of 0.79.29 (#366, #369, #372) under the lock of the
# scheduled runs, each block with its count script (read-only) before and after. Stops at the first
# failing step; the lock goes on exit. Outputs in out/post-0.79.29/.
. "$(dirname "$0")/_steps.sh"
counts g before treaty-same-as-counts.sql
step g1-semantic-verdragenbank semantic verdragenbank
counts g after treaty-same-as-counts.sql

counts h before ek-faction-votes-counts.sql
step h1-normalize-eerstekamer-votes normalize eerstekamer-votes
counts h after ek-faction-votes-counts.sql

counts i before ek-all-dossiers-counts.sql
since_i=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
step i1-retrieve-eerstekamer retrieve eerstekamer --mode full
step i2-normalize-eerstekamer normalize eerstekamer --since "$since_i"
step i3-semantic-eerstekamer semantic eerstekamer
counts i after ek-all-dossiers-counts.sql
echo "== all done $(date -u +%T)"
