#!/bin/sh
# judgment-columns-check.sql detached, without the lock: it runs longer than an ssh of action=sql stays open. Reads only;
# the result is in this script's log (action=log) and in out/judgment-columns-check.txt.
D=$(cd "$(dirname "$0")" && pwd)
set -a && . /srv/lawgraph/scheduler.env && set +a
. "$D/_sql.sh"
read_only_sql < "$D/judgment-columns-check.sql" > "$D/out/judgment-columns-check.txt" 2>&1
echo "== judgment-columns-check rc $? $(date -u +%T)"
cat "$D/out/judgment-columns-check.txt"
