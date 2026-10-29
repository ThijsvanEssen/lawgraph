"""The derived neighbours on a real PostgreSQL: a dossier ``LED_BY`` the committees that lead
an activity about it, and a committee with those dossiers, which no edge holds."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_COMMITTEES,
    COLLECTION_DOSSIERS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_ABOUT,
    RELATION_LED_BY,
    RELATION_PART_OF,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries.derived_neighbors import DERIVED_BUCKETS
from lawgraph.db.queries.dossiers import get_dossier_hub
from lawgraph.db.queries.nodes import NeighborFilter, get_node_with_neighbors
from tests.asserts import assert_status
from tests.pg.committee_graph import Graph
from tests.pg.plans import explain, plan_nodes

DOSSIER = "dossiers/d1"


def _graph(store: GraphStore) -> None:
    """Dossier d1 with a case; committee def leads two activities about it, diza one about
    its case (and so about the dossier, as an activity names the dossiers of its cases),
    jv one about another dossier; a plenary activity about d1 has no committee."""
    g = Graph(store)
    for key in ("d1", "d2"):
        g.node("dossiers", key, number=key)
    g.node("cases", "k1")
    g.edge("cases/k1", RELATION_PART_OF, DOSSIER)
    for key, name in (("def", "Defensie"), ("diza", "Digitale Zaken"), ("jv", "J&V")):
        g.node("committees", key, name=name, abbreviation=key.upper(), slug=key)
    led = {"a1": "def", "a2": "def", "a3": "diza", "a4": "jv", "a5": None}
    about = {
        "a1": [DOSSIER],
        "a2": [DOSSIER],
        "a3": ["cases/k1", DOSSIER],
        "a4": ["dossiers/d2"],
        "a5": [DOSSIER],
    }
    for key, committee in led.items():
        activity = g.node("activities", key, date="2025-01-01")
        if committee:
            g.edge(activity, RELATION_LED_BY, f"committees/{committee}")
        for target in about[key]:
            g.edge(activity, RELATION_ABOUT, target)
    g.write()


@pytest.fixture()
def graph(store: GraphStore) -> GraphStore:
    _graph(store)
    return store


def _derived(
    store: GraphStore, collection: str, key: str, **kwargs: Any
) -> dict[tuple[str | None, str, str], list[tuple[str, dict[str, Any]]]]:
    data = get_node_with_neighbors(store, collection, key, **kwargs)
    return {
        (b.facet.relation, b.facet.direction, b.facet.collection): [
            (e.doc["id"], e.edge) for e in b.entries
        ]
        for b in data.buckets
    }


def test_a_dossier_is_led_by_the_committees_of_its_activities(
    graph: GraphStore,
) -> None:
    buckets = _derived(graph, COLLECTION_DOSSIERS, "d1")
    found = buckets[(RELATION_LED_BY, "outbound", COLLECTION_COMMITTEES)]

    assert [(other, edge["meta"]) for other, edge in found] == [
        (
            "committees/def",
            {"derived_from": "activities", "role": "lead", "activities": 2},
        ),
        (
            "committees/diza",
            {"derived_from": "activities", "role": "lead", "activities": 1},
        ),
    ]
    other, edge = found[0]
    assert edge["key"] == f"derived:{DOSSIER}:LED_BY:{other}"
    assert (edge["from_id"], edge["to_id"], edge["status"]) == (
        DOSSIER,
        other,
        "canoniek",
    )
    # the same committees as the dossier's own ``committees``
    hub = get_dossier_hub(graph, DOSSIER)
    assert sorted(c["id"] for c in hub["committees"]) == [o for o, _ in found]


def test_a_committee_has_the_dossiers_it_leads_an_activity_about(
    graph: GraphStore,
) -> None:
    for key, dossiers in (
        ("def", [(DOSSIER, 2)]),
        ("diza", [(DOSSIER, 1)]),
        ("jv", [("dossiers/d2", 1)]),
    ):
        buckets = _derived(graph, COLLECTION_COMMITTEES, key)
        found = buckets[(RELATION_LED_BY, "inbound", COLLECTION_DOSSIERS)]
        assert [(o, e["meta"]["activities"]) for o, e in found] == dossiers, key
        assert {e["to_id"] for _, e in found} == {f"committees/{key}"}


def test_the_derived_bucket_pages_ranks_and_filters(graph: GraphStore) -> None:
    key = (RELATION_LED_BY, "outbound", COLLECTION_COMMITTEES)
    page = get_node_with_neighbors(graph, COLLECTION_DOSSIERS, "d1", limit=1, offset=1)
    (bucket,) = [b for b in page.buckets if b.facet.collection == COLLECTION_COMMITTEES]
    assert (bucket.facet.count, bucket.next_offset) == (2, None)
    assert [e.doc["id"] for e in bucket.entries] == ["committees/diza"]

    for filters in (
        NeighborFilter(relations=(RELATION_ABOUT,)),
        NeighborFilter(node_types=("activity",)),
        NeighborFilter(direction="inbound"),
        NeighborFilter(status=EDGE_STATUS_VOORGESTELD),
    ):
        assert key not in _derived(graph, COLLECTION_DOSSIERS, "d1", filters=filters)
    kept = NeighborFilter(relations=(RELATION_LED_BY,), direction="outbound")
    assert key in _derived(graph, COLLECTION_DOSSIERS, "d1", filters=kept)
    canvas = _derived(graph, COLLECTION_DOSSIERS, "d1", canvas=True)[key]
    assert canvas[0][1]["meta"] == {"derived_from": "activities"}


@pytest.fixture()
def recent(graph: GraphStore) -> GraphStore:
    """Committee fin leads activities about four dossiers: d1 three times long ago, d2 once
    lately, d3 twice on that same day and once undated, d4 undated alone."""
    g = Graph(graph)
    g.node("committees", "fin", name="Financiën", abbreviation="FIN", slug="fin")
    for key in ("d3", "d4"):
        g.node("dossiers", key, number=key)
    led = {
        "f1": ("d1", "2019-03-01"),
        "f2": ("d1", "2019-05-01"),
        "f3": ("d1", "2018-01-01"),
        "f4": ("d2", "2026-10-01"),
        "f5": ("d3", "2026-10-01"),
        "f6": ("d3", "2024-06-01"),
        "f7": ("d3", None),
        "f8": ("d4", None),
    }
    for key, (dossier, date) in led.items():
        activity = g.node("activities", key, **({"date": date} if date else {}))
        g.edge(activity, RELATION_LED_BY, "committees/fin")
        g.edge(activity, RELATION_ABOUT, f"dossiers/{dossier}")
    g.write()
    return graph


def test_by_importance_a_committee_has_its_latest_dossiers_first(
    recent: GraphStore,
) -> None:
    """The latest activity first, undated last; on the same day the most activities."""
    bucket_key = (RELATION_LED_BY, "inbound", COLLECTION_DOSSIERS)
    found = _derived(recent, COLLECTION_COMMITTEES, "fin", importance=True)[bucket_key]
    assert [(o, e["meta"]["latest"], e["meta"]["activities"]) for o, e in found] == [
        ("dossiers/d3", "2026-10-01", 3),
        ("dossiers/d2", "2026-10-01", 1),
        ("dossiers/d1", "2019-05-01", 3),
        ("dossiers/d4", None, 1),
    ]
    # in key order without it; a page is a slice of the order
    plain = _derived(recent, COLLECTION_COMMITTEES, "fin")[bucket_key]
    assert [o for o, _ in plain] == [f"dossiers/d{n}" for n in (1, 2, 3, 4)]
    page = get_node_with_neighbors(
        recent, COLLECTION_COMMITTEES, "fin", limit=2, offset=1, importance=True
    )
    (bucket,) = [b for b in page.buckets if b.facet.collection == COLLECTION_DOSSIERS]
    assert [e.doc["id"] for e in bucket.entries] == ["dossiers/d2", "dossiers/d1"]
    assert (bucket.facet.count, bucket.next_offset) == (4, 3)


def test_the_dossiers_of_a_committee_are_a_range_of_lg_led(graph: GraphStore) -> None:
    """Read from the items it leads as ``lg_led`` keeps them, never from the edges of each
    activity (Financiën leads 17,920 items on prod)."""
    (bucket,) = [b for b in DERIVED_BUCKETS if b.of == COLLECTION_COMMITTEES]
    plan = explain(
        graph, bucket.statement, {"node_id": "committees/def"}, disable=("seqscan",)
    )
    scans = [(n.get("Relation Name"), n.get("Index Name")) for n in plan_nodes(plan)]
    assert ("lg_led", "lg_led_committee") in scans, scans
    assert "edges" not in {table for table, _ in scans}, scans


@pytest.fixture()
def client(graph: GraphStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: graph
    yield TestClient(app)
    app.dependency_overrides.pop(get_store, None)


def test_the_route_gives_the_derived_bucket_with_its_edges(client: TestClient) -> None:
    response = client.get("/api/nodes/dossiers/d1", params={"sort": "importance"})
    assert_status(response, 200)
    buckets = {
        (b["relation"], b["direction"], b["collection"]): b
        for b in response.json()["neighbors"]["buckets"]
    }
    bucket = buckets[(RELATION_LED_BY, "outbound", COLLECTION_COMMITTEES)]
    assert bucket["total"] == 2
    assert [(i["key"], i["meta"]["role"]) for i in bucket["items"]] == [
        ("def", "lead"),
        ("diza", "lead"),
    ]
    assert bucket["items"][0]["edge_id"] == f"derived:{DOSSIER}:LED_BY:committees/def"

    response = client.get("/api/nodes/committees/diza")
    assert_status(response, 200)
    (bucket,) = [
        b
        for b in response.json()["neighbors"]["buckets"]
        if b["collection"] == COLLECTION_DOSSIERS
    ]
    assert (bucket["relation"], bucket["direction"], bucket["total"]) == (
        RELATION_LED_BY,
        "inbound",
        1,
    )
    assert bucket["items"][0]["meta"]["latest"] == "2025-01-01"


def test_the_route_gives_a_committee_its_latest_dossiers_first(
    recent: GraphStore,
) -> None:
    app.dependency_overrides[get_store] = lambda: recent
    try:
        response = TestClient(app).get(
            "/api/nodes/committees/fin", params={"sort": "importance"}
        )
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert_status(response, 200)
    (bucket,) = [
        b
        for b in response.json()["neighbors"]["buckets"]
        if b["collection"] == COLLECTION_DOSSIERS
    ]
    assert [(i["key"], i["meta"]["latest"]) for i in bucket["items"]] == [
        ("d3", "2026-10-01"),
        ("d2", "2026-10-01"),
        ("d1", "2019-05-01"),
        ("d4", None),
    ]
