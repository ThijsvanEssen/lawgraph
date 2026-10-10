#!/bin/sh
# Once after the deploy that brings lg_authored: semantic graph-light fills the papers members signed before its
# triggers, with their dossiers (200 members a statement; the other light tables already have theirs), and notes that
# the table is whole, from when the page of a member's dossiers reads it; member-authored-counts.sql before and after;
# under the lock.
. "$(dirname "$0")/_steps.sh"
counts signed before member-authored-counts.sql
step a1-semantic-graph-light semantic graph-light
counts signed after member-authored-counts.sql
echo "== all done $(date -u +%T)"
