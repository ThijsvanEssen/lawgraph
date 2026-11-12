#!/bin/sh
# B149, once after the deploy of 0.80.40 (#1182): normalize rijksoverheid again, so a seat without a ministry in its
# key moves into the one ministry the sources give its posts (`staatssecretaris/fiscaliteit-en-belastingdienst` ->
# `fin/staatssecretaris/fiscaliteit-en-belastingdienst`). One step under the lock, a few minutes. Check afterwards:
# `/api/seats?ministry=fin` lists the staatssecretarissen of Fiscaliteit and Herstel en Toeslagen with `fin/`.
. "$(dirname "$0")/_steps.sh"
step 1-normalize-rijksoverheid normalize rijksoverheid
echo "== all done $(date -u +%T)"
