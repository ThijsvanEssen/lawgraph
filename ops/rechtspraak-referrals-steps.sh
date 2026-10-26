#!/bin/sh
# The step of rechtspraak-referrals.sh: `semantic rechtspraak-referrals` over all, under the lock of the scheduled
# runs (_steps.sh), with rechtspraak-referrals-counts.sql before and after.
. "$(dirname "$0")/_steps.sh"
counts referrals before rechtspraak-referrals-counts.sql
step rechtspraak-referrals semantic rechtspraak-referrals
counts referrals after rechtspraak-referrals-counts.sql
echo "== all done $(date -u +%T)"
