#!/bin/sh
# Is the newest dump a backup? Restore it into a scratch database on another ArangoDB server
# and compare what it holds with the `counts` written at dump time: the number of documents
# of every collection and the names of the search views. The time the restore took is in
# runs.log: that is the restore time to plan with.
#
# The server is the test server of docker-compose.test.yml (container arango-lawgraph-test,
# which mounts LAWGRAPH_BACKUP_DIR read-only at /backups), or LAWGRAPH_RESTORE_CONTAINER: a
# dump of the full database needs a server with the memory and disk of the real one. The
# scratch database is dropped at the end, also after a failure.
. "$(dirname "$0")/_run.sh"

CONTAINER="${LAWGRAPH_RESTORE_CONTAINER:-arango-lawgraph-test}"
# Where /backups of the container is on this machine (docker-compose.yml mounts it).
BACKUP_DIR="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/backups"}}{{.Source}}{{end}}{{end}}' "$CONTAINER" 2>/dev/null | sed "s|^/host_mnt/|/|")"
DATABASE="$(.venv/bin/python -c 'from lawgraph.config.settings import ARANGO_DB_NAME; print(ARANGO_DB_NAME)')"
SCRATCH="lawgraph_restore_test"

in_container() {
  script="$1"
  shift
  docker exec "$CONTAINER" sh -c "$script" sh "$@"
}

newest() {
  in_container 'cd /backups 2>/dev/null && ls -1d "$1"-* 2>/dev/null | grep -v "\.partial$" | sort | tail -n 1' "$DATABASE"
}

restore_and_compare() {
  dump="$(newest)"
  [ -n "$dump" ] || { note "no dump of $DATABASE in $BACKUP_DIR (as $CONTAINER sees it)"; return 1; }
  started=$(date +%s)
  in_container '
    arangorestore --server.password "$ARANGO_ROOT_PASSWORD" --server.database "$1" \
      --create-database true --input-directory "/backups/$2" --overwrite true' \
    "$SCRATCH" "$dump" >> "$LAWGRAPH_LOG_FILE" 2>&1 || return 1
  seconds=$(($(date +%s) - started))
  restored="$(in_container '
    arangosh --server.password "$ARANGO_ROOT_PASSWORD" --server.database "$1" --quiet \
      --log.level warning --javascript.execute-string "
        db._collections()
          .filter(function (c) { return c.name()[0] !== \"_\"; })
          .map(function (c) { return c.name() + \" \" + c.count(); })
          .concat(db._views().map(function (v) { return \"view \" + v.name(); }))
          .sort().forEach(function (line) { print(line); });"' "$SCRATCH")"
  expected="$(in_container 'cat "/backups/$1/counts"' "$dump")"
  if [ "$restored" = "$expected" ]; then
    note "restored $dump in $seconds s on $CONTAINER; every collection and view is as dumped"
  else
    note "restored $dump on $CONTAINER, but it differs from the dump:"
    printf '%s\n' "$expected" > "$LOG_DIR/restore-expected"
    printf '%s\n' "$restored" > "$LOG_DIR/restore-restored"
    diff "$LOG_DIR/restore-expected" "$LOG_DIR/restore-restored" >> "$LOG_DIR/runs.log"
    return 1
  fi
}

drop_scratch() {
  in_container '
    arangosh --server.password "$ARANGO_ROOT_PASSWORD" --quiet --log.level warning \
      --javascript.execute-string "
        if (db._databases().indexOf(\"$1\") >= 0) { db._dropDatabase(\"$1\"); }"' "$SCRATCH"
}

run "restore the newest dump of $DATABASE" restore_and_compare
run "drop $SCRATCH" drop_scratch
finish
