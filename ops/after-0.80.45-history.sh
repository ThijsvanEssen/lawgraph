#!/bin/sh
# Step 2 of after-0.80.45.sh, under the lock: `normalize bwb-history` over every stored toestand, so every
# ArticleVersion has `redactions` and the text with a space around an added redaction (#1229). One step, no slices.
. "$(dirname "$0")/_steps.sh"
step 1-bwb-history normalize bwb-history
echo "== all done $(date -u +%T)"
