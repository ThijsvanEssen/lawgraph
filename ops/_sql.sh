# Sourced: read_only_sql runs the SQL on stdin in the PostgreSQL container, in a read-only session with a
# 600 s statement time-out, and stops at the first failing statement with psql's rc (3). The container and the
# database come from the environment (scheduler.env), as for scripts/backup.sh.
read_only_sql() {
  docker exec -i -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=600s' \
    "${LAWGRAPH_DB_CONTAINER:-lawgraph-postgres}" \
    psql -X -v ON_ERROR_STOP=1 -U lawgraph -d "${LAWGRAPH_DB_NAME:-lawgraph}"
}
