"""The SQL fragments over json values (``db/queries/_json_sql.py``), on every kind of value:
missing (SQL NULL), the json null, 0, 0.0, "", [], {}, a string, true, false and a
non-empty array and object."""

from __future__ import annotations

import json
from typing import Any

import psycopg
import pytest

from lawgraph.db.queries._json_sql import (
    EMPTY_ARRAY,
    array_or_empty,
    as_text,
    differs,
    first_present,
    has_length,
    is_absent,
    is_present,
    json_length,
    keep_props,
    period_holds,
    period_overlaps,
    truthy_or,
)
from lawgraph.db.queries.semantic import slim_sql

# A value that is not there at all (SQL NULL), as against the json null.
_MISSING = object()

# value, present, truthy, length
_VALUES: list[tuple[Any, bool, bool, int]] = [
    (_MISSING, False, False, 0),
    (None, False, False, 0),
    (0, True, False, 1),
    (0.0, True, False, 3),
    ("", True, False, 0),
    ([], True, True, 0),
    ({}, True, True, 0),
    ("x", True, True, 1),
    (True, True, True, 1),
    (False, True, False, 0),
    ([1, 2], True, True, 2),
    ({"a": 1}, True, True, 1),
]
_NULL = "'null'::json"
_ZERO = "'0'::json"
_ONE = "'1'::json"
_EMPTY_STRING = """'""'::json"""


def _literal(value: Any) -> str:
    return "NULL::json" if value is _MISSING else f"'{json.dumps(value)}'::json"


def _value(conn: psycopg.Connection, expression: str, value: Any = _MISSING) -> Any:
    """*expression* of ``v``, the json *value*."""
    row = conn.execute(f"SELECT {expression} FROM (SELECT {_literal(value)} AS v) t")
    return row.fetchone()[0]  # type: ignore[index]


@pytest.mark.parametrize(("value", "present", "truthy", "length"), _VALUES)
def test_each_fragment_on_each_kind_of_value(
    conn: psycopg.Connection, value: Any, present: bool, truthy: bool, length: int
) -> None:
    itself = _value(conn, "v::text", value)
    assert _value(conn, is_present("v"), value) is present
    assert _value(conn, is_absent("v"), value) is (not present)
    # two-valued: never SQL NULL, so NOT holds too
    assert _value(conn, f"NOT {is_present('v')}", value) is (not present)
    assert _value(conn, f"NOT {is_absent('v')}", value) is present
    assert _value(conn, f"({truthy_or('v', _ONE)})::text", value) == (
        itself if truthy else "1"
    )
    assert _value(conn, f"({truthy_or('v', EMPTY_ARRAY)})::text", value) == (
        itself if truthy else "[]"
    )
    assert _value(conn, f"({first_present('v', _ONE)})::text", value) == (
        itself if present else "1"
    )
    assert json.loads(_value(conn, f"({array_or_empty('v')})::text", value)) == (
        value if isinstance(value, list) else []
    )
    assert _value(conn, json_length("v"), value) == length
    assert _value(conn, has_length("v"), value) is (length > 0)


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (_MISSING, ""),
        (None, ""),
        ("x", "x"),
        (0.0, "0.0"),
        (True, "true"),
        ([1], "[1]"),
    ],
)
def test_as_text_writes_a_value_and_null_as_empty(
    conn: psycopg.Connection, value: Any, text: str
) -> None:
    assert _value(conn, as_text("v"), value) == text


def test_first_present_and_truthy_or_take_the_first(conn: psycopg.Connection) -> None:
    first = first_present("v", _NULL, _ZERO)
    truthy = truthy_or(_ZERO, _EMPTY_STRING, EMPTY_ARRAY, _ONE)
    assert _value(conn, f"({first})::text") == "0"
    assert _value(conn, f"({truthy})::text") == "[]"
    assert _value(conn, first_present("v", _NULL)) is None
    assert _value(conn, f"({truthy_or(_ZERO, _NULL)})::text") == "null"


def test_keep_props_keeps_the_fields_asked_for_in_byte_order(
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
    (none,) = conn.execute(
        f"SELECT {keep_props('a.props', 'gone')}::text FROM articles a"
    ).fetchone()  # type: ignore[misc]
    assert none == "{}"


@pytest.mark.parametrize(
    ("stored", "wanted", "differ"),
    [
        (1, 1.0, False),
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}, False),
        ([1, 2], [2, 1], True),
        (None, _MISSING, False),
        ("x", None, True),
    ],
)
def test_differs_compares_by_value(
    conn: psycopg.Connection, stored: Any, wanted: Any, differ: bool
) -> None:
    assert _value(conn, differs(_literal(stored), _literal(wanted))) is differ


@pytest.mark.parametrize(
    ("start", "end", "day", "holds"),
    [
        ("2020-01-01", "2020-12-31", "2020-01-01", True),  # both ends inclusive
        ("2020-01-01", "2020-12-31", "2020-12-31", True),
        ("2020-01-01", "2020-12-31", "2021-01-01", False),
        ("2020-01-01", "2020-12-31", "2019-12-31", False),
        (_MISSING, "2020-12-31", "1900-01-01", True),  # no start: from the first day
        (None, None, "2020-06-01", True),  # no end: still going on
        ("2020-01-01", _MISSING, "2019-01-01", False),
    ],
)
def test_period_holds_on_a_day(
    conn: psycopg.Connection, start: Any, end: Any, day: str, holds: bool
) -> None:
    (found,) = conn.execute(
        f"SELECT {period_holds(_literal(start), _literal(end), '%(day)s')}",
        {"day": day},
    ).fetchone()  # type: ignore[misc]
    assert found is holds


@pytest.mark.parametrize(
    ("start", "end", "first", "last", "overlaps"),
    [
        ("2020-01-01", "2020-12-31", "2020-12-31", "2021-06-01", True),
        ("2020-01-01", "2020-12-31", "2021-01-01", "2021-06-01", False),
        ("2020-01-01", "2020-12-31", "2019-01-01", "2019-12-31", False),
        ("2020-01-01", _MISSING, "2030-01-01", None, True),  # still going on
        (_MISSING, "2020-12-31", None, "1900-01-01", True),  # from the first day
        ("2020-01-01", "2020-12-31", None, None, True),  # nothing asked
    ],
)
def test_period_overlaps_a_period(
    conn: psycopg.Connection,
    start: Any,
    end: Any,
    first: str | None,
    last: str | None,
    overlaps: bool,
) -> None:
    fragment = period_overlaps(_literal(start), _literal(end), "%(first)s", "%(last)s")
    (found,) = conn.execute(
        f"SELECT {fragment}", {"first": first, "last": last}
    ).fetchone()  # type: ignore[misc]
    assert found is overlaps
