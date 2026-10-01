"""The dossier hub, run for real (the committee pages and the authorship lists:
``tests/pg/test_committees_queries.py``).

Each test writes the small graph it needs (nodes and edges as the pipelines write them) and
asks the queries behind the endpoints, so a wrong traversal or a wrong edge direction shows.
The scale test builds a dossier that a big amending law would give.
"""

from __future__ import annotations

import time
from typing import Any

from lawgraph.config.constants import (
    EDGE_STATUS_VOORGESTELD,
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_LED_BY,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REPEALS,
)
from lawgraph.db import ArangoStore, make_edge_doc
from lawgraph.db.queries.dossiers import get_dossier_hub


class Graph:
    """Nodes and edges written straight into the test database."""

    def __init__(self, store: ArangoStore) -> None:
        self.store = store
        self._nodes: dict[str, list[dict[str, Any]]] = {}
        self._edges: list[dict[str, Any]] = []

    def node(
        self, collection: str, key: str, labels: list[str] | None = None, **props: Any
    ) -> str:
        self._nodes.setdefault(collection, []).append(
            {
                "_key": key,
                "type": collection[:-1],
                "labels": labels or [],
                "props": props,
            }
        )
        return f"{collection}/{key}"

    def edge(
        self,
        from_id: str,
        relation: str,
        to_id: str,
        *,
        status: str = "canoniek",
        **meta: Any,
    ) -> None:
        self._edges.append(
            make_edge_doc(from_id, to_id, relation, status=status, meta=meta)
        )

    def write(self) -> None:
        for collection, docs in self._nodes.items():
            self.store.bulk_insert_or_update_nodes(collection, docs)
        self.store.bulk_insert_or_update_edges(self._edges)
        self._nodes, self._edges = {}, []


def _hub_graph(store: ArangoStore) -> None:
    g = Graph(store)
    dossier = g.node("dossiers", "36001", number="36001", label="36001", closed=False)
    other = g.node("dossiers", "36002", number="36002", label="36002", closed=False)
    case = g.node("cases", "case1", title="Zaak")

    # A regulation that came out of the dossier, one that only an amending publication
    # touched, an EU act, and a law nothing links to the dossier.
    law_a = g.node(
        "instruments",
        "bwbr0000001",
        bwb_id="BWBR0000001",
        display_name="Wet A",
        jurisdiction="nl",
    )
    law_b = g.node(
        "instruments",
        "bwbr0000002",
        bwb_id="BWBR0000002",
        display_name="Wet B",
        jurisdiction="nl",
    )
    law_c = g.node(
        "instruments",
        "bwbr0000003",
        bwb_id="BWBR0000003",
        display_name="Wet C",
        jurisdiction="nl",
    )
    directive = g.node(
        "instruments",
        "32016l0680",
        celex="32016L0680",
        display_name="Richtlijn X",
        jurisdiction="eu",
    )
    unrelated = g.node(
        "instruments",
        "bwbr0000009",
        bwb_id="BWBR0000009",
        display_name="Wet Z",
        jurisdiction="nl",
    )
    parents = {
        "bwbr0000001_5": law_a,
        "bwbr0000002_1": law_b,
        "bwbr0000002_2": law_b,
        "bwbr0000002_3": law_b,
        "bwbr0000003_1": law_c,
        "32016l0680_4": directive,
        "bwbr0000009_1": unrelated,
    }
    articles = {}
    for name, parent in parents.items():
        articles[name] = g.node("articles", name)
        g.edge(articles[name], RELATION_PART_OF, parent)

    g.edge(law_a, RELATION_LEGISLATED_IN, dossier)
    publication = g.node(
        "instruments", "stb_2020_1", publication_kind="Stb", display_name="Stb. 2020, 1"
    )
    elsewhere = g.node(
        "instruments", "stb_2020_2", publication_kind="Stb", display_name="Stb. 2020, 2"
    )
    g.edge(publication, RELATION_LEGISLATED_IN, dossier)
    g.edge(publication, RELATION_AMENDS, articles["bwbr0000002_1"])
    g.edge(
        publication, RELATION_AMENDS, articles["bwbr0000002_2"]
    )  # same law: one item
    g.edge(publication, RELATION_INTRODUCES, articles["bwbr0000002_3"])
    g.edge(
        publication, RELATION_AMENDS, articles["bwbr0000001_5"]
    )  # also legislated_in
    g.edge(publication, RELATION_REPEALS, articles["32016l0680_4"])
    g.edge(elsewhere, RELATION_LEGISLATED_IN, other)
    g.edge(elsewhere, RELATION_AMENDS, articles["bwbr0000009_1"])

    # Bills of the dossier: one direct, one through a case. Each proposes changes.
    motion = g.node(
        "documents", "d1", ["TK"], kind="Motie", date="2024-01-05", title="Motie"
    )
    amendment = g.node(
        "documents",
        "d2",
        ["TK"],
        kind="Amendement",
        date="2024-02-01",
        title="Amendement",
    )
    untyped = g.node("documents", "d3", ["TK"], kind="", date="2024-03-01")
    ek_late = g.node(
        "documents", "ek_2", ["EersteKamer", "EK"], kind="Brief", date="2024-05-01"
    )
    ek_early = g.node(
        "documents", "ek_1", ["EersteKamer", "EK"], kind="Brief", date="2024-04-01"
    )
    ek_other = g.node("documents", "ek_9", ["EK"], kind="Brief", date="2020-01-01")
    g.edge(motion, RELATION_PART_OF, dossier)
    g.edge(amendment, RELATION_PART_OF, case)
    g.edge(case, RELATION_PART_OF, dossier)
    g.edge(untyped, RELATION_PART_OF, dossier)
    g.edge(ek_late, RELATION_PART_OF, dossier)
    g.edge(ek_early, RELATION_PART_OF, dossier)
    g.edge(ek_other, RELATION_PART_OF, other)
    g.edge(
        motion, RELATION_AMENDS, law_c, status=EDGE_STATUS_VOORGESTELD
    )  # the instrument
    g.edge(
        amendment,
        RELATION_INTRODUCES,
        articles["bwbr0000003_1"],
        status=EDGE_STATUS_VOORGESTELD,
    )
    g.edge(
        amendment,
        RELATION_AMENDS,
        articles["bwbr0000002_1"],
        status=EDGE_STATUS_VOORGESTELD,
    )

    # Committees: an activity about the dossier, one about its case, a plenary one and one
    # about another dossier.
    lead_a = g.node(
        "committees", "c_a", name="Commissie A", slug="a", abbreviation="CA"
    )
    lead_b = g.node("committees", "c_b", name="Commissie B", slug="b")
    lead_c = g.node("committees", "c_c", name="Commissie C", slug="c")
    for key, about, committee in (
        ("act1", dossier, lead_a),
        ("act2", case, lead_b),
        ("act3", dossier, None),
        ("act4", other, lead_c),
    ):
        activity = g.node("activities", key, date="2024-06-01", kind="Commissiedebat")
        g.edge(activity, RELATION_ABOUT, about)
        if committee:
            g.edge(activity, RELATION_LED_BY, committee)
    both = g.node("activities", "act5", date="2024-06-02", kind="Commissiedebat")
    g.edge(both, RELATION_ABOUT, dossier)
    g.edge(both, RELATION_ABOUT, case)
    g.edge(both, RELATION_LED_BY, lead_a)
    g.write()


def test_the_hub_gathers_instruments_committees_and_documents_in_one_query(
    database: str,
) -> None:
    store = ArangoStore()
    _hub_graph(store)

    asked: list[str] = []
    real = store.query

    def recording(aql: str, *args: Any, **kwargs: Any) -> Any:
        asked.append(aql)
        return real(aql, *args, **kwargs)

    store.query = recording  # type: ignore[method-assign]
    hub = get_dossier_hub(store, "dossiers/36001")
    assert len(asked) == 1

    rows = [(i["display_name"], i["relation"], i["status"]) for i in hub["instruments"]]
    assert rows == [
        ("Wet A", "legislated_in", "canoniek"),
        ("Wet A", "amends", "canoniek"),
        ("Wet B", "amends", "canoniek"),
        ("Wet B", "amends", "voorgesteld"),
        ("Wet C", "amends", "voorgesteld"),
        ("Wet B", "introduces", "canoniek"),
        ("Wet C", "introduces", "voorgesteld"),
        ("Richtlijn X", "repeals", "canoniek"),
    ]
    by_key = {(i["key"], i["relation"]): i for i in hub["instruments"]}
    assert by_key[("bwbr0000001", "legislated_in")]["bwb_id"] == "BWBR0000001"
    assert by_key[("bwbr0000001", "legislated_in")]["jurisdiction"] == "nl"
    assert by_key[("32016l0680", "repeals")]["celex"] == "32016L0680"
    assert by_key[("32016l0680", "repeals")]["bwb_id"] is None
    assert not any(key == "bwbr0000009" for key, _ in by_key)  # another dossier's
    assert len(rows) == len(set(rows))  # one item per (instrument, relation, status)

    assert [c["slug"] for c in hub["committees"]] == [
        "a",
        "b",
    ]  # once, plenary and other left out
    assert hub["committees"][0]["abbreviation"] == "CA"

    assert hub["documents_by_kind"] == {
        "Motie": 1,
        "Amendement": 1,
        "Brief": 2,
    }  # the case's document counts, the untyped one and another dossier's do not
    assert hub["senate"] == {"document_count": 2, "first_date": "2024-04-01"}


def test_a_dossier_without_links_has_an_empty_hub(database: str) -> None:
    store = ArangoStore()
    g = Graph(store)
    g.node("dossiers", "36003", number="36003", label="36003")
    g.write()

    hub = get_dossier_hub(store, "dossiers/36003")

    assert hub == {
        "instruments": [],
        "committees": [],
        "documents_by_kind": {},
        "senate": {"document_count": 0, "first_date": None},
    }


def test_the_hub_of_a_big_amending_law_walks_indexes_and_stays_fast(
    database: str,
) -> None:
    """One publication that amends 3,000 articles of 300 laws, and 600 documents."""
    store = ArangoStore()
    g = Graph(store)
    dossier = g.node("dossiers", "36004", number="36004", label="36004")
    publication = g.node("instruments", "stb_2021_9", publication_kind="Stb")
    g.edge(publication, RELATION_LEGISLATED_IN, dossier)
    for law in range(300):
        instrument = g.node(
            "instruments",
            f"bwbr{law:07d}",
            bwb_id=f"BWBR{law:07d}",
            display_name=f"Wet {law}",
        )
        for number in range(10):
            article = g.node("articles", f"bwbr{law:07d}_{number}")
            g.edge(article, RELATION_PART_OF, instrument)
            g.edge(publication, RELATION_AMENDS, article)
    for number in range(600):
        document = g.node(
            "documents", f"doc{number}", ["TK"], kind="Motie", date="2024-01-01"
        )
        g.edge(document, RELATION_PART_OF, dossier)
    g.write()

    started = time.monotonic()
    hub = get_dossier_hub(store, "dossiers/36004")
    elapsed = time.monotonic() - started

    assert len(hub["instruments"]) == 300
    assert hub["documents_by_kind"] == {"Motie": 600}
    assert elapsed < 2.0, elapsed

    from lawgraph.db.queries import dossiers

    body = dossiers._dossier_documents_aql(dossiers._DOSSIER_HUB_BODY)
    aql = f"LET dossier_id = @dossier_id\n{body}"
    plan = store.db.aql.explain(
        aql,
        bind_vars={
            "dossier_id": "dossiers/36004",
            "part_of": RELATION_PART_OF,
            "about": RELATION_ABOUT,
            "led_by": RELATION_LED_BY,
            "legislated_in": RELATION_LEGISLATED_IN,
            "changes": [RELATION_AMENDS],
            "canonical": "canoniek",
            "relation_order": ["legislated_in", "amends"],
        },
    )
    kinds = {node["type"] for node in plan["nodes"]}
    assert "EnumerateCollectionNode" not in kinds


def test_the_routes_answer_from_the_real_graph(database: str) -> None:
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store

    store = ArangoStore()
    _hub_graph(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        hub = client.get("/api/dossiers/36001").json()
        assert hub["number"] == "36001" and hub["documents_by_kind"]["Amendement"] == 1
        assert hub["instruments"][0]["relation"] == "legislated_in"
        assert [c["slug"] for c in hub["committees"]] == ["a", "b"]
        assert hub["senate"]["first_date"] == "2024-04-01"
    finally:
        app.dependency_overrides.pop(get_store, None)
