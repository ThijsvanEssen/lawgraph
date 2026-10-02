"""``GET /api/dossiers/{number}/changed-articles`` on a real PostgreSQL (BE-18)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from lawgraph.db.queries.dossier_changes import get_dossier_changed_articles

DOSSIER = "dossiers/36264"


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _edge(
    key: str, source: str, target: str, relation: str, **extra: Any
) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "status": "canoniek",
        "confidence": 1.0,
        "meta": {},
        **extra,
    }


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("36264", "dossier", number="36264", label="36264")]
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("bwbr0002", "instrument", bwb_id="BWBR0002", citation_title="Zwet"),
            _node("bwbr0001", "instrument", bwb_id="BWBR0001", citation_title="Awet"),
            _node(
                "stb_2026_154",
                "instrument",
                kind="publicatie",
                display_name="Stb. 2026, 154",
                official_id="stb-2026-154",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                "bwbr0001_2",
                "article",
                bwb_id="BWBR0001",
                article_number="2",
                position=2,
            ),
            _node(
                "bwbr0001_1",
                "article",
                bwb_id="BWBR0001",
                article_number="1",
                position=1,
            ),
            _node(
                "bwbr0002_9",
                "article",
                bwb_id="BWBR0002",
                article_number="9",
                position=1,
            ),
            # an article of a law that is not in the graph
            _node("bwbr0003_5", "article", bwb_id="BWBR0003", article_number="5"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("bill", "document", display_name="Voorstel van wet"),
            _node("amendment", "document", display_name="Amendement"),
        ],
    )
    stb = "instruments/stb_2026_154"
    store.bulk_insert_or_update_edges(
        [
            _edge("l", stb, DOSSIER, "LEGISLATED_IN"),
            _edge(
                "e1",
                stb,
                "articles/bwbr0001_2",
                "AMENDS",
                meta={"effective_date": "2026-09-01"},
            ),
            _edge(
                "e2",
                stb,
                "articles/bwbr0001_1",
                "REPEALS",
                meta={"effective_date": "2026-09-01"},
            ),
            _edge("e3", stb, "articles/bwbr0003_5", "INTRODUCES"),
            _edge("p1", "documents/bill", DOSSIER, "PART_OF"),
            _edge("p2", "documents/amendment", DOSSIER, "ABOUT"),
            _edge(
                "v1",
                "documents/bill",
                "articles/bwbr0002_9",
                "AMENDS",
                status="voorgesteld",
            ),
            _edge(
                "v2",
                "documents/amendment",
                "articles/bwbr0001_1",
                "AMENDS",
                status="voorgesteld",
            ),
            # no change: a citation, an explanation, a change not proposed
            _edge(
                "x1",
                "documents/bill",
                "articles/bwbr0001_2",
                "REFERS_TO",
                status="voorgesteld",
            ),
            _edge("x2", "documents/bill", "articles/bwbr0001_2", "EXPLAINS"),
            _edge("x3", "documents/bill", "articles/bwbr0002_9", "AMENDS"),
            # a change of another dossier's publication
            _edge("x4", "instruments/other", "articles/bwbr0001_2", "AMENDS"),
        ]
    )


def _brief(laws: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            law["law"]["bwb_id"],
            c["article"]["key"],
            c["relation"],
            c["stage"],
            c["source"]["key"],
        )
        for law in laws
        for c in law["changes"]
    ]


def test_the_changes_per_law_in_the_order_of_the_law(store: GraphStore) -> None:
    _seed(store)
    laws = get_dossier_changed_articles(store, DOSSIER)
    # the laws by title, one not in the graph last; in a law the order of its articles,
    # then enacted before proposed
    assert _brief(laws) == [
        ("BWBR0001", "bwbr0001_1", "REPEALS", "enacted", "stb_2026_154"),
        ("BWBR0001", "bwbr0001_1", "AMENDS", "proposed", "amendment"),
        ("BWBR0001", "bwbr0001_2", "AMENDS", "enacted", "stb_2026_154"),
        ("BWBR0002", "bwbr0002_9", "AMENDS", "proposed", "bill"),
        ("BWBR0003", "bwbr0003_5", "INTRODUCES", "enacted", "stb_2026_154"),
    ]
    assert laws[0]["law"] == {
        "id": "instruments/bwbr0001",
        "bwb_id": "BWBR0001",
        "celex": None,
        "display_name": "Awet",
    }
    assert laws[2]["law"]["id"] is None
    enacted = laws[0]["changes"][0]
    assert enacted["source"] == {
        "id": "instruments/stb_2026_154",
        "key": "stb_2026_154",
        "display_name": "Stb. 2026, 154",
        "official_id": "stb-2026-154",
    }
    assert enacted["effective_date"] == "2026-09-01"
    assert laws[0]["changes"][1]["effective_date"] is None
    assert get_dossier_changed_articles(store, "dossiers/none") == []


def test_the_route(store: GraphStore) -> None:
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        body = client.get("/api/dossiers/36264/changed-articles").json()
        missing = client.get("/api/dossiers/99999/changed-articles")
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert (body["total"], body["articles"], body["enacted"], body["proposed"]) == (
        5,
        4,
        3,
        2,
    )
    assert [(law["law"]["display_name"], law["total"]) for law in body["laws"]] == [
        ("Awet", 3),
        ("Zwet", 1),
        (None, 1),
    ]
    assert missing.status_code == 404
