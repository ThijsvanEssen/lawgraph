#!/bin/sh
# Is the newest dump a backup? Restore it into a scratch database on another PostgreSQL
# server and compare what it holds with the `counts` written at dump time
# (scripts/_counts.sql): the rows of every table, the edges per relation, and the shape of
# the schema. The time the restore took is in runs.log: that is the restore time to plan
# with.
#
# The server is the test server of docker-compose.test.yml (container lawgraph-postgres-test,
# which mounts LAWGRAPH_BACKUP_DIR read-only at /backups), or LAWGRAPH_RESTORE_CONTAINER: a
# dump of the full database needs a server with the memory and disk of the real one. The
# scratch database is made as the schema makes a database (its collation sorts as the code
# expects) and dropped at the end, also after a failure.
. "$(dirname "$0")/_run.sh"

CONTAINER="${LAWGRAPH_RESTORE_CONTAINER:-lawgraph-postgres-test}"
# Where /backups of the container is on this machine (docker-compose.test.yml mounts it).
BACKUP_DIR="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/backups"}}{{.Source}}{{end}}{{end}}' "$CONTAINER" 2>/dev/null | sed "s|^/host_mnt/|/|")"
DATABASE="$(.venv/bin/python -c 'from lawgraph.config.settings import DB_NAME; print(DB_NAME)')"
SCRATCH="lawgraph_restore_test"

in_container() {
  script="$1"
  shift
  docker exec "$CONTAINER" sh -c "$script" sh "$@"
}

sql() {  # sql <database>: the statements on stdin, run in the container
  docker exec -i "$CONTAINER" psql -U lawgraph -d "$1" -X -q -A -t -v ON_ERROR_STOP=1
}

newest() {
  in_container 'cd /backups 2>/dev/null && ls -1d "$1"-* 2>/dev/null | grep -v "\.partial$" | sort | tail -n 1' "$DATABASE"
}

restore_and_compare() {
  dump="$(newest)"
  [ -n "$dump" ] || { note "no dump of $DATABASE in $BACKUP_DIR (as $CONTAINER sees it)"; return 1; }
  started=$(date +%s)
  printf 'DROP DATABASE IF EXISTS "%s" WITH (FORCE);\n%s;\n' "$SCRATCH" \
    "$(.venv/bin/python -c "from lawgraph.db.schema import create_database_sql; print(create_database_sql('$SCRATCH'))")" \
    | sql postgres >> "$LAWGRAPH_LOG_FILE" 2>&1 || return 1
  in_container 'pg_restore -U lawgraph -d "$1" -j 4 --exit-on-error "/backups/$2"' \
    "$SCRATCH" "$dump" >> "$LAWGRAPH_LOG_FILE" 2>&1 || return 1
  seconds=$(($(date +%s) - started))
  restored="$(sql "$SCRATCH" < scripts/_counts.sql | LC_ALL=C sort)"
  expected="$(in_container 'cat "/backups/$1/counts"' "$dump")"
  if [ -n "$expected" ] && [ "$restored" = "$expected" ]; then
    note "restored $dump in $seconds s on $CONTAINER; every table, relation, column, index and function is as dumped"
  else
    note "restored $dump on $CONTAINER, but it differs from the dump:"
    printf '%s\n' "$expected" > "$LOG_DIR/restore-expected"
    printf '%s\n' "$restored" > "$LOG_DIR/restore-restored"
    diff "$LOG_DIR/restore-expected" "$LOG_DIR/restore-restored" >> "$LOG_DIR/runs.log"
    return 1
  fi
}

drop_scratch() {
  printf 'DROP DATABASE IF EXISTS "%s" WITH (FORCE);\n' "$SCRATCH" | sql postgres
}

run "restore the newest dump of $DATABASE" restore_and_compare
run "drop $SCRATCH" drop_scratch
finish
