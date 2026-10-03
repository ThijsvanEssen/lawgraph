"""``scripts/_counts.sql``, what ``scripts/restore-test.sh`` compares a restore with: a restore
that lacks an object the dump had (a trigger that pg_restore makes last, after the data)
gives other lines than the dump."""

from __future__ import annotations

from pathlib import Path

import psycopg

from lawgraph.db.schema import NODE_COLLECTIONS, _derived

_COUNTS = Path(__file__).parents[2] / "scripts" / "_counts.sql"


def _counts(conn: psycopg.Connection) -> set[str]:
    """The lines of _counts.sql for the database of *conn*, statement by statement."""
    lines: set[str] = set()
    for statement in _COUNTS.read_text().split(";"):
        if "SELECT" in statement:
            lines.update(row[0] for row in conn.execute(statement.encode()).fetchall())
    return lines


def test_the_counts_name_every_trigger_of_the_schema(conn: psycopg.Connection) -> None:
    lines = _counts(conn)
    derived = [c for c in NODE_COLLECTIONS if _derived(c)]
    assert derived
    for collection in derived:
        assert f"trigger {collection} {collection}_derive" in lines
        assert f"function lg_derive_{collection}" in lines
    for event in ("insert", "update", "delete"):
        assert f"trigger dossiers dossiers_version_{event}" in lines
        assert f"trigger edges edges_version_{event}" in lines


def test_a_missing_trigger_changes_the_counts(conn: psycopg.Connection) -> None:
    dumped = _counts(conn)
    conn.execute("DROP TRIGGER dossiers_derive ON dossiers")
    assert dumped - _counts(conn) == {"trigger dossiers dossiers_derive"}


def test_the_counts_follow_the_rows(conn: psycopg.Connection) -> None:
    conn.execute(
        "INSERT INTO dossiers (id, type, props) VALUES ('dossiers/1', 'Dossier', '{}')"
    )
    assert "rows dossiers 1" in _counts(conn)
