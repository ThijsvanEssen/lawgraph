"""The derived columns of the node tables, which a trigger fills from ``props`` (``_derive``
in ``db/schema.py``), hold what their expressions give: the same values the generated
columns held, after an insert and after an update that changes props in part."""

from __future__ import annotations

import itertools
import json
from typing import Any

import psycopg
import pytest

from lawgraph.db import GraphStore
from lawgraph.db.schema import (
    _PROP,
    NODE_COLLECTIONS,
    SchemaOutdated,
    _derived,
    ensure_schema,
)

# Values of every type a prop takes, and of types it should not: a string with words, an
# ECLI, a list, a number, a boolean, an object with a child (a path like breadcrumb.title),
# a list of those, null, nothing.
_VALUES: list[Any] = [
    "Wetten en regels: art. 6:162 BW",
    "ECLI:NL:HR:2020:1",
    ["Één", "b", 2],
    3,
    2.5,
    True,
    {"title": "Hoofdstuk 1", "number": "1"},
    [{"title": "Afdeling 2"}, {"title": "Titel 3"}],
    None,
    "",
]
_MISSING = object()


def _keys(collection: str) -> list[str]:
    return sorted(
        {k for c in _derived(collection) for k in _PROP.findall(c.expression)}
    )


def _props(keys: list[str], shift: int) -> dict[str, Any]:
    """Props that give each key another value of ``_VALUES`` (or none) per *shift*."""
    props: dict[str, Any] = {"other": "x"}
    for n, key in enumerate(keys):
        value = (_VALUES + [_MISSING])[(n + shift) % (len(_VALUES) + 1)]
        if value is not _MISSING:
            props[key] = _unique(value, shift)
    return props


def _unique(value: Any, shift: int) -> Any:
    """A string of its own per row: a unique index (instruments.bwb_id, celex) holds each
    once. The empty string stays empty for one row only."""
    if isinstance(value, str):
        return f"{value} {shift}".strip() if value or shift else ""
    return value


def _differing(conn: psycopg.Connection, collection: str) -> list[str]:
    """The ids whose derived columns differ from their expressions over the props stored."""
    columns = _derived(collection)
    # json has no equality: its text, which is stricter (the value as written)
    stored = ", ".join(
        f"{c.name}::text" if c.sql_type == "json" else c.name for c in columns
    )
    computed = ", ".join(
        f"({c.expression})::text" if c.sql_type == "json" else c.expression
        for c in columns
    )
    rows = conn.execute(
        f"SELECT id FROM {collection} WHERE ROW({stored}) IS DISTINCT FROM ROW({computed})"
    ).fetchall()
    return [row[0] for row in rows]


_TABLES = [c for c in NODE_COLLECTIONS if _derived(c)]


@pytest.mark.parametrize("collection", _TABLES)
def test_the_derived_columns_follow_props_on_insert_and_update(
    store: GraphStore, conn: psycopg.Connection, collection: str
) -> None:
    keys = _keys(collection)
    count = len(_VALUES) + 1
    store.bulk_insert_or_update_nodes(
        collection,
        [
            {
                "_key": f"n{shift}",
                "type": "x",
                "labels": [],
                "props": _props(keys, shift),
            }
            for shift in range(count)
        ]
        + [{"_key": "empty", "type": "x", "labels": [], "props": {}}],
    )
    assert _differing(conn, collection) == []
    # an update of a part of the props (lg_update merges it into what is stored): every
    # key on its own, set to another value and to null
    for shift, key in itertools.islice(
        ((s, k) for s in range(count) for k in keys), 200
    ):
        value = _unique(_VALUES[(shift * 7 + len(key)) % len(_VALUES)], shift)
        store.bulk_insert_or_update_nodes(
            collection,
            [{"_key": f"n{shift}", "type": "x", "labels": [], "props": {key: value}}],
        )
    assert _differing(conn, collection) == []
    # a write that leaves props alone (labels only) keeps them
    store.bulk_insert_or_update_nodes(
        collection, [{"_key": "n0", "type": "x", "labels": ["L"], "props": {}}]
    )
    assert _differing(conn, collection) == []


def test_of_a_key_written_twice_the_last_counts_as_with_the_arrow(
    conn: psycopg.Connection,
) -> None:
    conn.execute(
        "INSERT INTO judgments (id, type, props)"
        """ VALUES ('judgments/x', 'judgment', '{"ecli": "A", "ecli": "B"}')"""
    )
    assert conn.execute("SELECT ecli, pj_ecli::text FROM judgments").fetchone() == (
        "B",
        '"B"',
    )
    assert _differing(conn, "judgments") == []


def test_a_nested_value_keeps_its_key_order(conn: psycopg.Connection) -> None:
    names = '{"z": 1, "a": [{"y": 2, "b": 3}]}'
    conn.execute(
        "INSERT INTO judgments (id, type, props) VALUES ('judgments/x', 'judgment', %s)",
        (json.dumps({"names": json.loads(names)}),),
    )
    assert conn.execute("SELECT pj_names::text FROM judgments").fetchone() == (names,)


def test_a_derived_column_still_generated_stops_the_start(
    conn: psycopg.Connection,
) -> None:
    """A database built when the derived columns were generated ones: a trigger cannot set
    a generated column, so it would keep the slow way unseen. It is built again."""
    conn.execute("ALTER TABLE dossiers DROP COLUMN number")
    conn.execute(
        "ALTER TABLE dossiers ADD COLUMN number text"
        " GENERATED ALWAYS AS (lg_str(props -> 'number')) STORED"
    )
    with pytest.raises(
        SchemaOutdated,
        match=r"dossiers\.number is gegenereerd, het schema vult hem met een trigger",
    ):
        ensure_schema(conn)
