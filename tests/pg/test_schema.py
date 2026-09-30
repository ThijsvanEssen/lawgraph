"""The PostgreSQL schema answers as ArangoDB did: its collation, its helpers, its versions."""

from __future__ import annotations

import json

import psycopg

from lawgraph.db.schema import NODE_COLLECTIONS, ensure_schema


def _one(conn: psycopg.Connection, sql: str, *params: object) -> object:
    row = conn.execute(sql.encode(), params or None).fetchone()
    assert row is not None
    return row[0]


def test_the_schema_can_be_ensured_again(conn: psycopg.Connection) -> None:
    ensure_schema(conn)
    tables = _one(
        conn,
        "SELECT count(*) FROM information_schema.tables"
        " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'",
    )
    # every node collection, edges, raw_sources, pipeline_state and the data versions
    assert tables == len(NODE_COLLECTIONS) + 4


def test_strings_sort_as_in_arangodb(conn: psycopg.Connection) -> None:
    """Probe P2: ICU root, upper case first, null first."""
    words = ["wet", "Wet", "WET", "Wét", "B", "a", "aa", "Aa", None]
    got = _one(
        conn,
        "SELECT array_agg(w ORDER BY w NULLS FIRST) FROM unnest(%s::text[]) w",
        words,
    )
    assert got == [None, "a", "Aa", "aa", "B", "WET", "Wet", "wet", "Wét"]


def test_generated_columns_hold_only_values_of_their_type(
    conn: psycopg.Connection,
) -> None:
    props = {
        "ecli": "ECLI:NL:HR:2020:1",
        "stub": "yes",
        "subjects": ["b", 1, "a"],
        "z": 1,
    }
    conn.execute(
        "INSERT INTO judgments (id, type, props) VALUES ('judgments/x', 'judgment', %s)",
        (json.dumps(props),),
    )
    row = conn.execute(
        "SELECT key, ecli, stub, subjects, props::text FROM judgments"
    ).fetchone()
    assert row == ("x", "ECLI:NL:HR:2020:1", None, ["b", "a"], json.dumps(props))


def test_merge_keeps_the_order_arangodb_gives(conn: psycopg.Connection) -> None:
    """Probe P1: the left keys in byte order, then the new keys of the right."""
    got = _one(
        conn,
        """SELECT lg_merge('{"zeta": 1, "b": 2, "B": 0}', '{"b": 5, "alpha": 3}')::text""",
    )
    assert list(json.loads(str(got))) == ["B", "b", "zeta", "alpha"]
    assert json.loads(str(got))["b"] == 5


def test_array_union_keeps_the_first_occurrence(conn: psycopg.Connection) -> None:
    assert _one(conn, "SELECT lg_array_union('{TK,b}', '{c,TK,b,d}')") == [
        "TK",
        "b",
        "c",
        "d",
    ]


def test_tokens_are_the_tokens_of_text_nl(conn: psycopg.Connection) -> None:
    """Probe P3: what ArangoDB answers to TOKENS(text, "text_nl")."""
    text = "ECLI:NL:HR:2020:1234, zo’n café, 1.000,50 en t/m, Straße, gewijzigd"
    assert _one(conn, "SELECT lg_tokens(%s)", text) == [
        "ecli:nl:hr",
        "2020",
        "1234",
        "zo’n",
        "caf",
        "1.000,50",
        "en",
        "t",
        "m",
        "straß",
        "gewijzigd",
    ]


def test_a_write_raises_the_data_version_and_an_empty_one_does_not(
    conn: psycopg.Connection,
) -> None:
    def version() -> object:
        return _one(
            conn, "SELECT version FROM lg_data_version WHERE collection = 'dossiers'"
        )

    before = version()
    conn.execute("UPDATE dossiers SET props = props WHERE false")
    assert version() == before
    conn.execute("INSERT INTO dossiers (id, type) VALUES ('dossiers/1', 'dossier')")
    assert version() == before + 1  # type: ignore[operator]


def test_the_nodes_view_finds_a_node_by_id(conn: psycopg.Connection) -> None:
    conn.execute("INSERT INTO members (id, type) VALUES ('members/m', 'member')")
    assert conn.execute(
        "SELECT collection, key FROM nodes WHERE id = 'members/m'"
    ).fetchall() == [("members", "m")]
