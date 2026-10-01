#!/bin/sh
# A compressed dump of the database, the last LAWGRAPH_BACKUP_KEEP (7) of them kept.
#
# The dump is written by pg_dump in the PostgreSQL container (directory format, four jobs,
# zstd), to /backups there: the directory LAWGRAPH_BACKUP_DIR (./backups) of this machine,
# mounted by docker-compose.yml. Every file operation on it runs in the container too. Next
# to the dump, `counts` holds what scripts/restore-test.sh compares a restore with: the rows
# of every table, the edges per relation, and the shape of the schema (the columns of every
# table, the indexes, the functions). A dump is written as `<name>.partial` and renamed when
# it is complete, so an interrupted one is never taken for a backup.
#
# LAWGRAPH_BACKUP_UPLOAD_COMMAND, when set, gets the new dump off this machine: it is run by
# `sh -c` with its path in LAWGRAPH_BACKUP_PATH, for example
#   rclone copy "$LAWGRAPH_BACKUP_PATH" leafcloud:lawgraph-backups/"$(basename "$LAWGRAPH_BACKUP_PATH")"
# The payload store (LAWGRAPH_PAYLOAD_STORE) is not in the dump: a bucket keeps its own
# versions, a directory needs a copy of its own.
# Runs under the lock of the scheduled runs: a dump never reads a database that a load writes.
. "$(dirname "$0")/_run.sh"

KEEP="${LAWGRAPH_BACKUP_KEEP:-7}"
CONTAINER="${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}"
# Where /backups of the container is on this machine (docker-compose.yml mounts it).
BACKUP_DIR="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/backups"}}{{.Source}}{{end}}{{end}}' "$CONTAINER" 2>/dev/null | sed "s|^/host_mnt/|/|")"
DATABASE="$(.venv/bin/python -c 'from lawgraph.config.settings import DB_NAME; print(DB_NAME)')"
NAME="$DATABASE-$(date +%Y-%m-%dT%H%M%S)"

in_container() {  # in_container <script> <args...>: sh in the container
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
  in_container 'pg_dump -U lawgraph -d "$1" -Fd -j 4 -Z zstd -f "/backups/$2.partial"' \
    "$DATABASE" "$NAME" || return 1
  # scripts/_counts.sql on stdin; sorted apart, so a failing psql fails the dump
  docker exec -i "$CONTAINER" sh -c '
    psql -U lawgraph -d "$1" -X -q -A -t -v ON_ERROR_STOP=1 > "/backups/$2.partial/counts.unsorted" &&
    LC_ALL=C sort "/backups/$2.partial/counts.unsorted" > "/backups/$2.partial/counts" &&
    rm "/backups/$2.partial/counts.unsorted"' sh "$DATABASE" "$NAME" \
    < scripts/_counts.sql >> "$LAWGRAPH_LOG_FILE" 2>&1 || return 1
  in_container 'mv "/backups/$2.partial" "/backups/$2"' "$DATABASE" "$NAME" || return 1
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
