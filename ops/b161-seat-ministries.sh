#!/bin/sh
# B161, once after the deploy of 0.80.41 (#1188): ask the Staatscourant also after "voor" for a minister whose page
# writes "van" (Immigratie en Asiel), then normalize rijksoverheid again, so the misspelt names, the two ministries of
# Drees III and the acting ministers get their ministry. Two steps under the lock, minutes. Check afterwards with
# `action=sql name=b161-seats-without-ministry`: only the 12 posts the sources give no ministry are left.
. "$(dirname "$0")/_steps.sh"
step 1-retrieve-staatscourant-posts retrieve staatscourant-posts
step 2-normalize-rijksoverheid normalize rijksoverheid
echo "== all done $(date -u +%T)"
