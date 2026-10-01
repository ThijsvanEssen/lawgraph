"""The SQL helpers of the semantic queries give what their AQL gave (probe P1 for KEEP)."""

from __future__ import annotations

import json
from typing import Any

import psycopg
import pytest

from lawgraph.db.queries.semantic import (
    absent_sql,
    differs_sql,
    nonempty_sql,
    present_sql,
    slim_sql,
)

# A value that is not there at all (SQL NULL), as against the json null.
_MISSING = object()


def _value(conn: psycopg.Connection, expression: str, value: Any) -> Any:
    """*expression* of ``v``, a json value (``None`` for a value that is missing)."""
    literal = "NULL::json" if value is _MISSING else "%s::json"
    params = () if value is _MISSING else (json.dumps(value),)
    row = conn.execute(f"SELECT {expression} FROM (SELECT {literal} AS v) t", params)
    return row.fetchone()[0]  # type: ignore[index]


def test_slim_keeps_the_fields_asked_for_in_byte_order(
    conn: psycopg.Connection,
) -> None:
    conn.execute(
        "INSERT INTO articles (id, type, labels, props) VALUES"
        " ('articles/a', 'article', '{BWB}', %s::json)",
        (json.dumps({"title": "T", "Zeta": 1, "alpha": None, "other": 2}),),
    )
    (doc,) = conn.execute(
        f"SELECT {slim_sql('a', 'title', 'alpha', 'Zeta', 'gone')}::text"
        " FROM articles a"
    ).fetchone()  # type: ignore[misc]
    # the keys of a json object in its text: "Zeta" before "alpha" before "title" (bytes)
    assert list(json.loads(doc)) == ["_key", "type", "labels", "props"]
    assert list(json.loads(doc)["props"].items()) == [
        ("Zeta", 1),
        ("alpha", None),  # a prop set to null is kept, one the node lacks is not
        ("title", "T"),
    ]
    assert json.loads(doc)["labels"] == ["BWB"]


@pytest.mark.parametrize(
    ("value", "nonempty"),
    [
        ([1], True),
        ([], False),
        ({"a": 1}, True),
        ({}, False),
        ("x", True),
        ("", False),
        (0, True),
        (True, True),
        (False, False),
        (None, False),
        (_MISSING, False),
    ],
)
def test_nonempty_is_length_above_zero(
    conn: psycopg.Connection, value: Any, nonempty: bool
) -> None:
    assert _value(conn, f"coalesce({nonempty_sql('v')}, false)", value) is nonempty


@pytest.mark.parametrize(
    ("value", "present"),
    [("x", True), (0, True), (False, True), (None, False), (_MISSING, False)],
)
def test_present_and_absent_are_comparisons_with_null(
    conn: psycopg.Connection, value: Any, present: bool
) -> None:
    assert _value(conn, f"coalesce({present_sql('v')}, false)", value) is present
    assert _value(conn, absent_sql("v"), value) is (not present)


@pytest.mark.parametrize(
    ("stored", "wanted", "differs"),
    [
        (1, 1.0, False),
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}, False),
        ([1, 2], [2, 1], True),
        (None, _MISSING, False),
        ("x", None, True),
    ],
)
def test_differs_compares_by_value(
    conn: psycopg.Connection, stored: Any, wanted: Any, differs: bool
) -> None:
    def literal(value: Any) -> str:
        return "NULL::json" if value is _MISSING else f"'{json.dumps(value)}'::json"

    (found,) = conn.execute(
        f"SELECT {differs_sql(literal(stored), literal(wanted))}"
    ).fetchone()  # type: ignore[misc]
    assert found is differs
