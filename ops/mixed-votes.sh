#!/bin/sh
# After the deploy of the mixed-votes fix and the new coalition definitions: the decisions read as a roll call
# that were a faction vote with members voting apart (26 on 9 Oct, mixed-votes-counts.sql), normalized again from
# their stored votes, then what the coalition did on every vote, in full (26 s on 9 Oct). One step under the lock,
# at night: from NOT_BEFORE (default 03) to NOT_AFTER (default 07), Europe/Amsterdam.
from=${NOT_BEFORE:-03}
to=${NOT_AFTER:-07}
until h=$(TZ=Europe/Amsterdam date +%H); [ "$h" -ge "$from" ] && [ "$h" -lt "$to" ]; do
  echo "$(date -u +%T) waiting for $from:00-$to:00 Europe/Amsterdam"; sleep 600
done
. "$(dirname "$0")/_steps.sh"
counts mixed before mixed-votes-counts.sql
step v1-normalize-tk-dossiers-mixed-votes normalize tk-dossiers --mixed-votes
step v2-semantic-tk-coalition-votes semantic tk-coalition-votes
counts mixed after mixed-votes-counts.sql
counts missing after coalition-missing-rows.sql
echo "== all done $(date -u +%T)"
