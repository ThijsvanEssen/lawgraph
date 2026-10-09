"""The PostgreSQL schema answers as ArangoDB did: its collation, its helpers, its versions."""

from __future__ import annotations

import json

import psycopg
import pytest

from lawgraph.db.schema import (
    NODE_COLLECTIONS,
    SchemaOutdated,
    ensure_schema,
    expected_columns,
    schema_drift,
)


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
    # every node collection, edges, raw_sources, pipeline_state, the data versions and
    # the kept heat (lg_heat, lg_heat_state), the light judgments and papers
    # (lg_judgment_light, lg_document_light) and the terms of the articles with the stems
    # of the summaries they are weighed against (lg_article_terms, lg_summary_stems), and
    # what the coalition did on each vote (lg_decision_coalition), and the definitions of
    # the regulations (lg_instrument_definitions)
    assert tables == len(NODE_COLLECTIONS) + 12


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


def test_same_is_the_equality_of_aql(conn: psycopg.Connection) -> None:
    """An attribute set to null equals a missing one, at every depth and in an object inside
    an array; an array compares position by position, what the shorter lacks as null."""
    cases = [
        ('{"a": 1}', '{"a": 1, "b": null}', True),
        ('{"a": {"b": 1}}', '{"a": {"b": 1, "c": null}}', True),
        ('{"l": [{"c": 1}]}', '{"l": [{"c": 1, "x": null}]}', True),
        ('{"l": [1]}', '{"l": [1, null]}', True),
        ("[]", "[null]", True),
        ('{"l": [1, 2]}', '{"l": [1, null, 2]}', False),
        ('{"l": [[1]]}', '{"l": [[1, null], null]}', True),
        ('{"a": 1}', '{"a": 2}', False),
        ('{"a": 1}', '{"a": null}', False),
        ("null", "{}", False),
    ]
    for a, b, same in cases:
        assert _one(conn, f"SELECT lg_same('{a}'::jsonb, '{b}'::jsonb)") is same, (a, b)


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


def test_a_fresh_database_has_the_tables_of_the_schema(
    conn: psycopg.Connection,
) -> None:
    assert schema_drift(conn) == []
    assert {"articles", "edges", "raw_sources", "lg_data_version"} <= set(
        expected_columns()
    )


def test_a_column_the_table_lacks_stops_the_start(conn: psycopg.Connection) -> None:
    conn.execute("ALTER TABLE articles DROP COLUMN stub")
    with pytest.raises(
        SchemaOutdated, match=r"herbouw nodig.*articles\.stub ontbreekt"
    ):
        ensure_schema(conn)


def test_a_column_the_schema_lacks_stops_the_start(conn: psycopg.Connection) -> None:
    conn.execute("ALTER TABLE edges ADD COLUMN weight int")
    with pytest.raises(SchemaOutdated, match=r"edges\.weight staat niet in het schema"):
        ensure_schema(conn)


def test_an_index_the_schema_dropped_does_not_stop_the_start(
    conn: psycopg.Connection,
) -> None:
    """An index the schema no longer makes stays until it is dropped by hand (``DROP INDEX
    CONCURRENTLY`` on a large database): the start goes on, and it is not made again."""
    conn.execute("CREATE INDEX edges_to ON edges (to_id, relation, from_collection)")
    ensure_schema(conn)
    assert conn.execute(
        "SELECT count(*) FROM pg_indexes WHERE indexname = 'edges_to'"
    ).fetchone() == (1,)
    conn.execute("DROP INDEX edges_to")
    ensure_schema(conn)
    assert conn.execute(
        "SELECT count(*) FROM pg_indexes WHERE indexname = 'edges_to'"
    ).fetchone() == (0,)


@pytest.mark.parametrize(
    ("value", "truthy"),
    [
        ("null", False),
        ("false", False),
        ("0", False),
        ("0.0", False),
        ('""', False),
        ("true", True),
        ("1", True),
        ("-0.5", True),
        ('"0"', True),  # a string with a character, whatever it says
        ('" "', True),
        ("[]", True),
        ("{}", True),
    ],
)
def test_truthiness_is_that_of_aql(
    conn: psycopg.Connection, value: str, truthy: bool
) -> None:
    (found,) = conn.execute("SELECT lg_truthy(%s::json)", (value,)).fetchone()  # type: ignore[misc]
    assert found is truthy


def test_a_missing_value_is_not_truthy(conn: psycopg.Connection) -> None:
    (found,) = conn.execute("SELECT lg_truthy(NULL::json)").fetchone()  # type: ignore[misc]
    assert found is False


def test_the_schema_works_without_a_search_path(conn: psycopg.Connection) -> None:
    """What a restore (pg_restore) does with an empty search_path: build a generated column
    that inlines the functions, load rows (the generated columns and the data version
    trigger run), and the functions call each other by their schema."""
    conn.execute(b"SET search_path = ''")
    conn.execute(
        b"CREATE TABLE public.restored (v json, words text[] GENERATED ALWAYS AS"
        b" (public.lg_tokens_all(public.lg_values(v))) STORED)"
    )
    conn.execute(b"""INSERT INTO public.restored (v) VALUES ('["Wetten", "regels"]')""")
    assert _one(conn, "SELECT words FROM public.restored") == ["wet", "regel"]
    conn.execute(
        b"INSERT INTO public.dossiers (id, type, props)"
        b""" VALUES ('dossiers/1', 'dossier', '{"name": "x"}')"""
    )
    assert _one(
        conn, "SELECT version FROM public.lg_data_version WHERE collection = 'dossiers'"
    )
    calls = {
        "public.lg_fold_all(ARRAY['Één'])": ["een"],
        'public.lg_member_names(\'{"name": "A", "party": "B"}\')': "a b",
        'public.lg_faction_names(\'{"name": "A", "aliases": ["C"]}\')': "a  c",
        "public.lg_same('{\"a\": [1, null]}', '{\"a\": [1]}')": True,
        "public.lg_walk('dossiers/1', 1, 10, NULL, NULL, true, true, NULL,"
        " ARRAY['dossiers'])": [],
    }
    for call, expected in calls.items():
        assert _one(conn, f"SELECT {call}") == expected, call
