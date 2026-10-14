"""What a committee leads, kept apart on a real PostgreSQL: ``lg_led`` kept by the triggers on
``edges`` (an activity or case led, a dossier it is about) and on ``activities`` and ``cases``
(their dates), filled by ``semantic graph-light`` for what was written before them, and read
by the pages of a committee once filled: the same pages as the walk over the edges, without
a probe per item led (8.9 s for the dossiers of Financiën on prod)."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.config.constants import RELATION_ABOUT, RELATION_LED_BY
from lawgraph.db import GraphStore, schema, version_cache
from lawgraph.db.queries import committee_led
from lawgraph.db.queries.committees import (
    get_committee_activities,
    get_committee_detail,
)
from tests.pg.plans import explain, plan_nodes, recorded
from tests.pg.test_committees_queries import Graph, _committee_graph


def _led(store: GraphStore) -> dict[str, tuple[Any, list[str]]]:
    return {
        r["item_id"]: (r["date"], list(r["dossiers"]))
        for r in store.query(
            "SELECT item_id, date, dossiers FROM lg_led"
            " WHERE committee_id = 'committees/c1'"
        )
    }


def test_an_item_led_is_kept_with_its_date_and_dossiers(store: GraphStore) -> None:
    """With the edge that leads it, its date and the dossiers it is about; again when one
    is added or taken away, when its date changes or it is written after its edge; gone
    with its edge."""
    g = Graph(store)
    g.node("committees", "c1", name="Financiën", slug="fin")
    g.node("activities", "a1", date="2024-01-01")
    g.node("cases", "k1", date="2023-05-05")
    g.edge("activities/a1", RELATION_LED_BY, "committees/c1")
    g.edge("cases/k1", RELATION_LED_BY, "committees/c1")
    g.edge("activities/a1", RELATION_ABOUT, "dossiers/d1")
    g.edge("cases/k1", RELATION_ABOUT, "dossiers/d2")
    # led before it is written
    g.edge("activities/a2", RELATION_LED_BY, "committees/c1")
    g.write()
    assert _led(store) == {
        "activities/a1": ("2024-01-01", ["dossiers/d1"]),
        "cases/k1": ("2023-05-05", ["dossiers/d2"]),
        "activities/a2": (None, []),
    }
    more = Graph(store)
    more.node("activities", "a2", date="2024-02-02")
    more.node("activities", "a1", date="2024-03-03")
    more.edge("activities/a1", RELATION_ABOUT, "dossiers/d3")
    more.write()
    assert _led(store) == {
        "activities/a1": ("2024-03-03", ["dossiers/d1", "dossiers/d3"]),
        "cases/k1": ("2023-05-05", ["dossiers/d2"]),
        "activities/a2": ("2024-02-02", []),
    }
    store.execute(
        "DELETE FROM edges WHERE from_id = 'activities/a1' AND to_id = 'dossiers/d1'"
    )
    store.execute(
        "DELETE FROM edges WHERE from_id = 'cases/k1' AND to_id = 'committees/c1'"
    )
    assert _led(store) == {
        "activities/a1": ("2024-03-03", ["dossiers/d3"]),
        "activities/a2": ("2024-02-02", []),
    }


def _pages(store: GraphStore) -> list[Any]:
    version_cache.clear()
    return [
        get_committee_detail(store, "b", status=status, limit=limit, offset=offset)
        for status in (None, "open", "closed")
        for limit, offset in ((100, 0), (2, 1), (2, 10))
    ] + [
        get_committee_activities(store, slug, limit=limit, offset=offset)
        for slug in ("b", "x")
        for limit, offset in ((100, 0), (2, 1), (2, 4), (2, 50))
    ]


def test_the_pages_from_the_table_are_those_of_the_walk(store: GraphStore) -> None:
    """Before the fill the pages walk the edges; after it the same pages from the table,
    and noted filled; a new database is filled from new by the triggers alone."""
    _committee_graph(store)
    walked = _pages(store)
    store.execute("DELETE FROM lg_led")  # as written before the triggers
    assert not committee_led.is_filled(store)
    assert committee_led.fill_led(store) > 0
    assert committee_led.is_filled(store)
    assert _pages(store) == walked
    # and it is the table that is read: a dossier kept with an item shows
    store.execute(
        "UPDATE lg_led SET dossiers = ARRAY['dossiers/d2']"
        " WHERE item_id = 'activities/a6'"
    )
    version_cache.clear()
    detail = get_committee_detail(store, "b", status=None)
    assert detail is not None and detail["dossier_total"] == 5


def _relations(plan: dict[str, Any]) -> list[str]:
    return [n["Relation Name"] for n in plan_nodes(plan) if "Relation Name" in n]


def test_the_pages_read_no_edge_and_no_activity_past_the_page(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once filled, the dossiers are those kept with the items (no edge read) and the
    activities a range of the table's index, the page's rows alone read from their table."""
    _committee_graph(store)
    committee_led.fill_led(store)
    store.vacuum_analyze()
    version_cache.clear()
    calls = recorded(store, monkeypatch)
    get_committee_detail(store, "b", status=None)
    get_committee_activities(store, "b", limit=2)
    # the statements of the two pages (not the members of the committee)
    seen = [
        (c.statement, c.params)
        for c in calls
        if c.params and "committee_id" in c.params and "limit" in c.params
    ]
    assert len(seen) == 2
    for statement, params in seen:
        plan = explain(store, statement, params)
        assert "edges" not in _relations(plan), statement


def test_a_release_without_the_table_starts_on_a_database_with_it(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rollback: a release that knows no ``lg_led`` checks only the tables of its own
    schema, so it starts on a database that has the table and its triggers; and those
    triggers go on keeping the table while it runs."""
    without = {
        table: columns
        for table, columns in schema.expected_columns().items()
        if not table.startswith("lg_led")
    }
    monkeypatch.setattr(schema, "expected_columns", lambda: without)
    with store.pool.connection() as conn:
        assert schema.schema_drift(conn) == []
    g = Graph(store)
    g.node("committees", "c1", name="Financiën")
    g.node("activities", "a1", date="2024-01-01")
    g.edge("activities/a1", RELATION_LED_BY, "committees/c1")
    g.write()
    assert _led(store) == {"activities/a1": ("2024-01-01", [])}
