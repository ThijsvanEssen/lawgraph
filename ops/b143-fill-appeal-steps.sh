#!/bin/sh
# The step of b143-fill-appeal.sh: `semantic rechtspraak-appeal` over all, under the lock of the scheduled runs
# (_steps.sh), with b143-fill-counts.sql before and after.
. "$(dirname "$0")/_steps.sh"
counts b143 before b143-fill-counts.sql
step rechtspraak-appeal semantic rechtspraak-appeal
counts b143 after b143-fill-counts.sql
echo "== all done $(date -u +%T)"
