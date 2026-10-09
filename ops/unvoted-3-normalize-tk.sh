#!/bin/sh
# Backfill step 3 of 3 (unvoted-backfill.sh, at the weekend): every Zaak normalized again, so each case says
# whether the Kamer is done with it (props.done, Zaak.Afgedaan, in the stored records). Measured: 20,000 cases in
# about a second on the test server; prod has about 304,000.
. "$(dirname "$0")/_steps.sh"
step u3-normalize-tk normalize tk
counts unvoted after-done unvoted-counts.sql
echo "== all done $(date -u +%T)"
