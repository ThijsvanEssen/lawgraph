#!/bin/sh
# A compressed dump of the database, the last LAWGRAPH_BACKUP_KEEP (7) of them kept.
#
# The dump is written by arangodump in the ArangoDB container, to /backups there: the
# directory LAWGRAPH_BACKUP_DIR (./backups) of this machine, mounted by docker-compose.yml.
# Every file operation on it runs in the container too, whose files belong to root. Next to
# the dump, `counts` holds the number of documents per collection and the search views, what
# scripts/restore-test.sh compares a restore with. A dump is written as `<name>.partial` and
# renamed when it is complete, so an interrupted one is never taken for a backup.
#
# LAWGRAPH_BACKUP_UPLOAD_COMMAND, when set, gets the new dump off this machine: it is run by
# `sh -c` with its path in LAWGRAPH_BACKUP_PATH, for example
#   rclone copy "$LAWGRAPH_BACKUP_PATH" leafcloud:lawgraph-backups/"$(basename "$LAWGRAPH_BACKUP_PATH")"
# Runs under the lock of the scheduled runs: a dump never reads a database that a load writes.
. "$(dirname "$0")/_run.sh"

KEEP="${LAWGRAPH_BACKUP_KEEP:-7}"
CONTAINER="${LAWGRAPH_ARANGO_CONTAINER:-arango-lawgraph}"
# Where /backups of the container is on this machine (docker-compose.yml mounts it).
BACKUP_DIR="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/backups"}}{{.Source}}{{end}}{{end}}' "$CONTAINER" 2>/dev/null | sed "s|^/host_mnt/|/|")"
DATABASE="$(.venv/bin/python -c 'from lawgraph.config.settings import ARANGO_DB_NAME; print(ARANGO_DB_NAME)')"
NAME="$DATABASE-$(date +%Y-%m-%dT%H%M%S)"

in_container() {  # in_container <script> <args...>: sh in the container, with its root password
  script="$1"
  shift
  docker exec "$CONTAINER" sh -c "$script" sh "$@" >> "$LAWGRAPH_LOG_FILE" 2>&1
}

dump() {
  started=$(date +%s)
  [ -n "$BACKUP_DIR" ] || {
    note "$CONTAINER mounts nothing at /backups: recreate it (docker compose up -d)"
    return 1
  }
  in_container '
    arangodump --server.password "$ARANGO_ROOT_PASSWORD" --server.database "$1" \
      --output-directory "/backups/$2.partial" --compress-output true --overwrite true &&
    arangosh --server.password "$ARANGO_ROOT_PASSWORD" --server.database "$1" --quiet \
      --log.level warning --javascript.execute-string "
        db._collections()
          .filter(function (c) { return c.name()[0] !== \"_\"; })
          .map(function (c) { return c.name() + \" \" + c.count(); })
          .concat(db._views().map(function (v) { return \"view \" + v.name(); }))
          .sort().forEach(function (line) { print(line); });" > "/backups/$2.partial/counts" &&
    mv "/backups/$2.partial" "/backups/$2"' "$DATABASE" "$NAME" || return 1
  size=$(docker exec "$CONTAINER" du -sh "/backups/$NAME" | cut -f1)
  note "dumped $DATABASE to $BACKUP_DIR/$NAME ($size in $(($(date +%s) - started)) s)"
}

prune() {  # keep the newest $KEEP complete dumps of this database, and no partial ones
  in_container '
    cd /backups || exit 1
    rm -rf ./"$1"-*.partial
    ls -1d ./"$1"-* 2>/dev/null | sort -r | tail -n +"$(($2 + 1))" | while read -r old; do
      rm -rf "$old"
    done' "$DATABASE" "$KEEP"
}

upload() {
  [ -n "${LAWGRAPH_BACKUP_UPLOAD_COMMAND:-}" ] || return 0
  LAWGRAPH_BACKUP_PATH="$BACKUP_DIR/$NAME" sh -c "$LAWGRAPH_BACKUP_UPLOAD_COMMAND" >> "$LAWGRAPH_LOG_FILE" 2>&1
}

run "dump $DATABASE" dump
[ $failed -eq 0 ] && run "upload $NAME" upload
run "prune $BACKUP_DIR" prune
finish
