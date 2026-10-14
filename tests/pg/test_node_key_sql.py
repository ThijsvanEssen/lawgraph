"""``lg_node_key`` makes of an identifier in SQL the node key ``core.models.make_node_key``
makes of it in Python, over a broad set of identifiers: TK GUIDs, publication and BWB ids,
ECLIs, dots, spaces, runs of ``_``, accents, letters without an accent to take off,
compatibility forms, and nothing at all."""

from __future__ import annotations

import psycopg

from lawgraph.core.models import make_node_key

IDENTIFIERS = [
    "8C4B1E6D-1A2B-4C3D-9E8F-0123456789AB",
    "8c4b1e6d-1a2b-4c3d-9e8f-0123456789ab",
    "stb-2026-187",
    "stcrt-2025-12345",
    "kst-36200-VII-3",
    "BWBR0001854",
    "bwbr0001854",
    "BWBV0001234",
    "CVDR123456_1",
    "ECLI:NL:HR:2024:1234",
    "ECLI:NL:RVS:2023:4567.",
    "32012R1215",
    "2025Z15468",
    "36 200 VII",
    "  leading and trailing  ",
    "a__b___c",
    "__edges__",
    "a - b -- c",
    "a.b.c",
    "...",
    "1.2.3",
    "Yeşilgöz-Zegerius",
    "Ölçek",
    "café crème",
    "Straße",
    "Æsop Øresund",
    "ĳsselmeer",
    "Ĳssel",
    "İstanbul",
    "ﬁets",
    "Ａｂｃ１２３",
    "Ⅻ",
    "K-Kelvin",
    "x²",
    "½",
    "ǅemal",
    "Ω omega",
    "日本",
    " nbsp ",
    "tab\there",
    "line\nbreak",
    "a/b\\c",
    "'quote'",
    "Ångström",
    "",
    " ",
    "___",
    "-",
]


def test_lg_node_key_is_make_node_key(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        "SELECT x, lg_node_key(x) FROM unnest(%s::text[]) AS x", (IDENTIFIERS,)
    ).fetchall()
    assert dict(rows) == {x: make_node_key(x) for x in IDENTIFIERS}


def test_lg_node_key_of_null_is_null(conn: psycopg.Connection) -> None:
    """A missing identifier names no node (``make_node_key`` would give ``node``)."""
    assert conn.execute("SELECT lg_node_key(NULL)").fetchone() == (None,)


def test_lg_node_key_is_inlined(conn: psycopg.Connection) -> None:
    """The planner inlines it (a plain SQL expression), so an index on the key is used."""
    plan = conn.execute(
        "EXPLAIN (VERBOSE, COSTS OFF) SELECT lg_node_key(x) FROM unnest(ARRAY['a']) x"
    ).fetchall()
    assert "lg_node_key" not in " ".join(row[0] for row in plan)
