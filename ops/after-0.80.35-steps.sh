#!/bin/sh
# The steps of after-0.80.35.sh, under the lock (B131, #1147):
# - semantic graph-derive members: the digest of members changes with list_name (known_as before a name from the
#   signatures);
# - normalize rijksoverheid: the seat keys in government_functions and SERVED_IN.meta.posts without "-" when there is
#   no ministry.
. "$(dirname "$0")/_steps.sh"
step 1-graph-derive-members semantic graph-derive members
step 2-normalize-rijksoverheid normalize rijksoverheid
echo "== all done $(date -u +%T)"
