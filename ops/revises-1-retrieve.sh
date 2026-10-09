#!/bin/sh
# #378 backfill, step 1 of 3 (revises-backfill.sh): every Zaak that replaces another (Zaak.VervangenVanuit,
# about 11,600), fetched again with that relation. Measured on the OData: 47 pages of 250 at about 0.5 s.
# Keeps the moment it began for the normalize of step 2.
. "$(dirname "$0")/_steps.sh"
counts revises before revises-amendments-counts.sql
since=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
echo "$since" > "$OPS/out/revises-backfill.since"
echo "== since $since (for revises-2-normalize.sh)"
step r1-retrieve-tk-replacing retrieve tk --replacing --mode full
echo "== all done $(date -u +%T)"
