"""The events of the feed per month or day (``GET /api/feed/periods``), from ``lg_feed_events``:
under the same filters each kind counts what the feed's own facet counts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core.models import NodeType
from lawgraph.db import GraphStore, NodeWriter
from lawgraph.db.queries.feed import FeedFilters, get_feed
from lawgraph.db.queries.feed_events import (
    get_periods,
    periods_query,
    word_queries,
    write_all,
    write_since,
)
from tests.pg.test_feed_queries import _document, _node, _seed


def _topics(store: GraphStore) -> None:
    """Papers whose title, or whose dossier's title, holds AI as a word, and one that
    holds it only inside a word."""
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _node(COLLECTION_DOSSIERS, NodeType.DOSSIER, "37100", number="37100",
                      label="37100", title="Uitvoering van de AI-verordening"),
                _document("motion_101", "Motie", "2026-09-08", "37000",
                          subject="Motie over toezicht op de AI-verordening"),
                _document("letter_102", "Brief regering", "2026-09-15", "37100",
                          subject="Stand van zaken"),
                _document("motion_103", "Motie", "2026-10-01", "37000",
                          subject="Motie over universitaire opleidingen"),
                _document("letter_104", "Brief regering", "2025-12-30", "37000",
                          subject="Brief over AI in het onderwijs"),
            ]
        )  # fmt: skip


@pytest.fixture()
def seeded(store: GraphStore) -> GraphStore:
    _seed(store)
    _topics(store)
    write_all(store)
    return store


def _feed_kinds(store: GraphStore, filters: FeedFilters) -> dict[str, int]:
    facets = get_feed(store, filters, limit=1)["facets"]
    return {f["value"]: f["count"] for f in facets["kind"] if f["count"]}


def _period_kinds(store: GraphStore, filters: FeedFilters, per: str) -> dict[str, int]:
    found: Counter[str] = Counter()
    for period in get_periods(store, filters, per)["periods"]:
        found.update(period["counts"])
    return dict(found)


FILTERS = [
    FeedFilters(),
    FeedFilters(q=("ai",)),
    FeedFilters(q=("AI-verordening",)),
    FeedFilters(q=("grens", "gemeenten")),
    FeedFilters(q=("voorbeeld",)),
    FeedFilters(chamber="TK"),
    FeedFilters(chamber="EK"),
    FeedFilters(faction="vvd"),
    FeedFilters(faction="d66"),
    FeedFilters(ministry="fin"),
    FeedFilters(dossier="37001"),
    FeedFilters(cabinet="jetten"),
    FeedFilters(q=("ai",), chamber="TK", since="2026-01-01"),
    FeedFilters(since="2026-05-01", until="2026-06-30"),
]


@pytest.mark.parametrize("filters", FILTERS, ids=[repr(f) for f in FILTERS])
def test_each_kind_counts_what_the_feed_counts(
    seeded: GraphStore, filters: FeedFilters
) -> None:
    feed = _feed_kinds(seeded, filters)
    assert _period_kinds(seeded, filters, "month") == feed
    assert _period_kinds(seeded, filters, "day") == feed


def test_a_short_word_is_a_whole_word_and_a_topic_goes_by_its_dossier(
    seeded: GraphStore,
) -> None:
    periods = get_periods(seeded, FeedFilters(q=("ai",)), "month")["periods"]
    assert [(p["period"], p["counts"]) for p in periods] == [
        ("2025-12-01", {"Brief regering": 1}),
        # the motion by its own title, the letter by its dossier's; not "universitaire"
        ("2026-09-01", {"Motie": 1, "Brief regering": 1}),
    ]
    assert periods[1]["total"] == 2


def test_a_month_and_its_days(seeded: GraphStore) -> None:
    filters = FeedFilters(kinds=("Motie",), since="2026-09-01", until="2026-10-31")
    months = get_periods(seeded, filters, "month")["periods"]
    assert [(p["period"], p["total"]) for p in months] == [
        ("2026-09-01", 1),
        ("2026-10-01", 1),
    ]
    days = get_periods(seeded, filters, "day")["periods"]
    assert [(p["period"], p["total"]) for p in days] == [
        ("2026-09-08", 1),
        ("2026-10-01", 1),
    ]


def test_the_days_since_are_written_again_in_place(seeded: GraphStore) -> None:
    with NodeWriter(seeded) as writer:
        writer.add(
            _document("motion_105", "Motie", "2026-10-02", "37000", subject="Nieuw")
        )
    month = FeedFilters(kinds=("Motie",), since="2026-10-01", until="2026-10-31")
    assert get_periods(seeded, month, "month")["periods"][0]["total"] == 1
    write_since(seeded, "2026-10-01")
    assert get_periods(seeded, month, "month")["periods"][0]["total"] == 2
    # what lies before the day is kept
    assert _period_kinds(seeded, FeedFilters(), "month") == _feed_kinds(
        seeded, FeedFilters()
    )


def test_the_words_are_found_by_index(seeded: GraphStore) -> None:
    """A word with a letter or digit is looked up in ``words`` (GIN), not tested on
    every row of a table of many events."""
    filters = FeedFilters(q=("ai", "AI-verordening"))
    statement, bind = periods_query(filters, "month", word_queries(seeded, filters))
    with seeded.pool.connection() as conn, conn.transaction():
        conn.execute(
            "INSERT INTO lg_feed_events (kind, id, date, factions, labels, title, words)"
            " SELECT 'Motie', 'documents/filler_' || n, '2020-01-01', '{}', '{}',"
            " 'motie ' || n, lg_alnum_tokens('motie ' || n)"
            " FROM generate_series(1, 20000) n"
        )
        conn.execute("ANALYZE lg_feed_events")
        plan = conn.execute("EXPLAIN (FORMAT JSON) " + statement, bind).fetchone()[0]
    nodes: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "Node Type" in node:
                nodes.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(plan)
    scans = {
        n["Node Type"] for n in nodes if n.get("Relation Name") == "lg_feed_events"
    }
    assert "Seq Scan" not in scans
    assert any(n.get("Index Name") == "lg_feed_events_words" for n in nodes)


@pytest.fixture()
def client(seeded: GraphStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: seeded
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_route(client: TestClient) -> None:
    body = client.get(
        "/api/feed/periods", params=[("q", "ai"), ("q", "grens"), ("chamber", "TK")]
    ).json()
    assert body["per"] == "month"
    assert body["partial"] is False
    assert body["written_at"]
    assert [p["period"] for p in body["periods"]] == sorted(
        p["period"] for p in body["periods"]
    )
    assert all(p["total"] == sum(p["counts"].values()) for p in body["periods"])
    assert "data_as_of" in body


@pytest.mark.parametrize(
    "params",
    [
        {"per": "day"},  # no first day
        {"per": "day", "since": "2025-01-01", "until": "2026-06-01"},  # past 400 days
        {"member": "x"},
        {"tier": "hoog"},
        {"per": "week"},
    ],
)
def test_what_the_route_does_not_count(client: TestClient, params: dict) -> None:
    assert client.get("/api/feed/periods", params=params).status_code == 422
