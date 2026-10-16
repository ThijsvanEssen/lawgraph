"""The SQL of ``lawgraph built-beforehand`` on a real PostgreSQL: it builds a missing index
concurrently, finds each valid and analyzes the tables of the expressions."""

from __future__ import annotations

import psycopg

from lawgraph.db.schema import BUILT_BEFOREHAND, built_beforehand_sql


def test_the_sql_builds_what_is_missing_and_finds_every_index_valid(
    conn: psycopg.Connection,
) -> None:
    conn.execute("DROP INDEX cases_number")
    valid = []
    for line in built_beforehand_sql():
        cursor = conn.execute(line.encode())
        if line.startswith("SELECT "):
            valid = cursor.fetchall()
    assert len(valid) == len(BUILT_BEFOREHAND)
    assert all(is_valid for _, is_valid in valid)
