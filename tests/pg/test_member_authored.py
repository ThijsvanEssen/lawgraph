"""The papers members signed with their dossiers, on a real PostgreSQL: ``lg_authored`` kept
by the triggers on every write of ``edges`` (the signatures, a paper placed in a dossier or a
case, a case placed in a dossier, and those taken out), filled by ``semantic graph-light`` for
those written before them, and read by the page of a member's dossiers
(``get_actor_dossiers``) once filled, the same page as the walk over the edges, a paper of
today included."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import RELATION_AUTHORED, RELATION_PART_OF
from lawgraph.db import GraphStore
from lawgraph.db.queries import member_authored
from lawgraph.db.queries.committees import get_actor_dossiers
from tests.pg.test_committees_queries import Graph, _authorship_graph, _signatures


def _dossiers(store: GraphStore, member: str) -> dict[str, list[str]]:
    return {
        r["document_id"]: list(r["dossiers"])
        for r in store.query(
            "SELECT document_id, dossiers FROM lg_authored WHERE member_id = %(m)s",
            {"m": member},
        )
    }


def test_a_signature_is_kept_with_the_dossiers_of_its_paper(store: GraphStore) -> None:
    """With the signature, directly and through a case; again when the paper or its case is
    placed in a dossier, or taken out; gone with the signature."""
    g = Graph(store)
    g.node("members", "m1", name="Anna")
    g.node("documents", "doc1")
    g.node("documents", "doc2")
    g.node("cases", "k1")
    g.edge("documents/doc1", RELATION_PART_OF, "dossiers/d1")
    g.edge(
        "members/m1", RELATION_AUTHORED, "documents/doc1", role="Eerste ondertekenaar"
    )
    g.edge("members/m1", RELATION_AUTHORED, "documents/doc2", role="Mede ondertekenaar")
    g.write()
    assert _dossiers(store, "members/m1") == {
        "documents/doc1": ["dossiers/d1"],
        "documents/doc2": [],
    }
    # a paper placed in a case, the case in a dossier, the paper in a second dossier
    g.edge("documents/doc2", RELATION_PART_OF, "cases/k1")
    g.write()
    g.edge("cases/k1", RELATION_PART_OF, "dossiers/d2")
    g.write()
    g.edge("documents/doc1", RELATION_PART_OF, "dossiers/d3")
    g.write()
    assert _dossiers(store, "members/m1") == {
        "documents/doc1": ["dossiers/d1", "dossiers/d3"],
        "documents/doc2": ["dossiers/d2"],
    }
    # the case taken out of its dossier: its papers lose it
    store.execute(
        "DELETE FROM edges WHERE from_id = 'cases/k1' AND relation = %(p)s",
        {"p": RELATION_PART_OF},
    )
    assert _dossiers(store, "members/m1")["documents/doc2"] == []
    store.execute(
        "DELETE FROM edges WHERE from_id = 'members/m1' AND to_id = 'documents/doc1'"
    )
    assert list(_dossiers(store, "members/m1")) == ["documents/doc2"]


@pytest.mark.parametrize("graph", [_authorship_graph, _signatures])
def test_the_page_from_the_table_is_that_of_the_walk(
    store: GraphStore, graph: Any
) -> None:
    """Before the fill the page walks; after it the same pages (every member, paged), from
    the table; a faction walks always."""
    graph(store)
    # a statement of one column gives its values
    members = store.query("SELECT id FROM members ORDER BY id NULLS LAST")
    actors = [*members, "factions/vvd", "factions/d66"]
    pages = [(0, 100), (0, 1), (1, 1)]
    walked = {
        (a, o, n): get_actor_dossiers(store, a, offset=o, limit=n)
        for a in actors
        for o, n in pages
    }
    store.execute("DELETE FROM lg_authored")  # as written before the triggers
    assert not member_authored.is_filled(store)
    assert member_authored.fill_authored(store) > 0
    assert member_authored.is_filled(store)
    for (a, o, n), page in walked.items():
        assert get_actor_dossiers(store, a, offset=o, limit=n) == page, (a, o, n)


def test_a_paper_of_today_is_on_the_page_at_once(store: GraphStore) -> None:
    _authorship_graph(store)
    member_authored.fill_authored(store)
    g = Graph(store)
    g.node("dossiers", "39000", title="Nieuw", opened_on="2026-10-10")
    g.node("documents", "today")
    g.edge("documents/today", RELATION_PART_OF, "dossiers/39000")
    g.edge(
        "members/m1", RELATION_AUTHORED, "documents/today", role="Eerste ondertekenaar"
    )
    g.write()
    first = get_actor_dossiers(store, "members/m1")["items"][0]
    assert first["dossier"]["_key"] == "39000" and first["document_count"] == 1


def test_the_page_of_a_member_reads_the_table_not_the_edges(store: GraphStore) -> None:
    """Once filled, a member's papers and dossiers are a range of the table's index: no
    edge of their signatures read from the table of edges, no probe of a paper's dossiers."""
    _signatures(store)
    member_authored.fill_authored(store)
    from lawgraph.db.store import _query

    statements: list[tuple[Any, Any]] = []
    query = store.query

    def recording(statement: Any, params: Any = None, **options: Any) -> Any:
        if params and "actor_id" in params:
            statements.append((statement, params))
        return query(statement, params, **options)

    store.query = recording  # type: ignore[method-assign]
    try:
        get_actor_dossiers(store, "members/m1")
    finally:
        store.query = query  # type: ignore[method-assign]
    statement, params = statements[0]
    with store.pool.connection() as conn:
        explain = b"EXPLAIN (FORMAT JSON) " + _query(statement).as_bytes(conn)
        plan = conn.execute(explain, params).fetchone()[0]

    def relations(node: Any) -> set[str]:
        found = {node["Relation Name"]} if "Relation Name" in node else set()
        for child in node.get("Plans", []):
            found |= relations(child)
        return found

    assert "edges" not in relations(plan[0]["Plan"])


def _dated(store: GraphStore, member: str) -> dict[str, tuple[Any, Any]]:
    return {
        r["document_id"]: (r["date"], r["capacity"])
        for r in store.query(
            "SELECT document_id, date, capacity FROM lg_authored"
            " WHERE member_id = %(m)s",
            {"m": member},
        )
    }


def test_a_signature_is_kept_with_the_date_of_its_paper(store: GraphStore) -> None:
    """The date of the paper or the case signed and the capacity of the signature, with the
    signature; again when the paper or the case is written later or its date changes."""
    g = Graph(store)
    g.node("members", "m1", name="Anna")
    g.node("documents", "doc1", date="2024-01-01")
    g.node("cases", "k1", date="2023-05-05")
    signed = {"role": "Eerste ondertekenaar", "capacity": "bewindspersoon"}
    g.edge("members/m1", RELATION_AUTHORED, "documents/doc1", **signed)
    g.edge("members/m1", RELATION_AUTHORED, "cases/k1", **signed)
    # signed before the paper is written
    g.edge("members/m1", RELATION_AUTHORED, "documents/doc2", role="Mede ondertekenaar")
    g.write()
    assert _dated(store, "members/m1") == {
        "documents/doc1": ("2024-01-01", "bewindspersoon"),
        "cases/k1": ("2023-05-05", "bewindspersoon"),
        "documents/doc2": (None, None),
    }
    g.node("documents", "doc2", date="2024-03-03")
    g.node("documents", "doc1", date="2024-02-02")
    g.node("cases", "k1", date="2023-06-06")
    g.write()
    assert _dated(store, "members/m1") == {
        "documents/doc1": ("2024-02-02", "bewindspersoon"),
        "cases/k1": ("2023-06-06", "bewindspersoon"),
        "documents/doc2": ("2024-03-03", None),
    }


def test_the_dates_are_kept_in_slices_then_marked(store: GraphStore) -> None:
    """Signatures kept before the dates were (no date, no capacity): kept a slice of members
    at a time, each slice saying where the next goes on; the last notes the table dated."""
    _signatures(store)
    member_authored.fill_authored(store)
    kept = {
        m: _dated(store, m)
        for m in store.query("SELECT DISTINCT member_id FROM lg_authored")
    }
    store.execute("UPDATE lg_authored SET date = NULL, capacity = NULL")
    store.execute("DELETE FROM lg_authored_dated")
    assert not member_authored.is_dated(store)
    after, slices = "", 0
    while True:
        after, _ = member_authored.date_authored(store, after=after, limit=1)
        slices += 1
        if after is None:
            break
        assert not member_authored.is_dated(store)
    assert slices == len(kept) + 1
    assert member_authored.is_dated(store)
    assert {m: _dated(store, m) for m in kept} == kept


def test_a_table_filled_from_new_is_dated_and_one_filled_before_is_not(
    store: GraphStore,
) -> None:
    """On a new database (a rebuild) the table had its dates from its first row, so the
    first fill notes it dated as well, without the pass of ``--authored-dates``; on one
    filled before the dates (prod), the fill leaves that to the pass."""
    _signatures(store)
    assert not member_authored.is_filled(store)
    member_authored.fill_authored(store)
    assert member_authored.is_filled(store) and member_authored.is_dated(store)

    # filled before its dates were kept: the fill again does not note them
    store.execute("DELETE FROM lg_authored_dated")
    member_authored.fill_authored(store)
    assert member_authored.is_filled(store) and not member_authored.is_dated(store)
