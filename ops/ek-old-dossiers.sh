#!/bin/sh
# Once after the deploy that writes the dossiers of the papers of the Eerste Kamer the Tweede Kamer's data has none of:
# normalize eerstekamer over every paper (writes those dossiers), then semantic eerstekamer (the papers PART_OF them);
# ek-old-dossiers-counts.sql before and after; under the lock.
. "$(dirname "$0")/_steps.sh"
counts papers before ek-old-dossiers-counts.sql
step d1-normalize-eerstekamer normalize eerstekamer
step d2-semantic-eerstekamer semantic eerstekamer
counts papers after ek-old-dossiers-counts.sql
echo "== all done $(date -u +%T)"
