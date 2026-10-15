"""What a member signed, counted per capacity over the whole of an AUTHORED bucket
(``capacity_counts``), not only over its page: Verbonden splits a member's papers by the
capacity they signed in, and a page of 200 of 1,483 papers gave lower bounds."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_MEMBERS,
    RELATION_AUTHORED,
    RELATION_MEMBER_OF,
)
from lawgraph.db import GraphStore, make_edge_doc

MEMBER = f"{COLLECTION_MEMBERS}/jetten"
# papers per capacity, and one without a capacity
DOCUMENTS = {"kamerlid": 3, "bewindspersoon": 4, "overig": 1, None: 1}


def _node(collection: str, key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": ["TK"], "props": props}


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_MEMBERS,
        [_node(COLLECTION_MEMBERS, "jetten", "member", name="Rob Jetten")],
    )
    store.bulk_insert_or_update_nodes(
        "factions", [_node("factions", "d66", "faction", name="D66")]
    )
    papers, cases, edges = [], [], []
    for capacity, count in DOCUMENTS.items():
        for n in range(count):
            key = f"kst_{capacity or 'geen'}_{n}"
            papers.append(
                _node(
                    COLLECTION_DOCUMENTS,
                    key,
                    "document",
                    kind="Brief",
                    date=f"2025-0{n + 1}-01",
                    title=key,
                )
            )
            meta = {
                "role": "Eerste ondertekenaar",
                **({"capacity": capacity} if capacity else {}),
            }
            edges.append(
                make_edge_doc(
                    MEMBER,
                    f"{COLLECTION_DOCUMENTS}/{key}",
                    RELATION_AUTHORED,
                    meta=meta,
                )
            )
    # two cases, as Kamerlid
    for n in range(2):
        cases.append(_node(COLLECTION_CASES, f"z_{n}", "case", kind="Motie"))
        edges.append(
            make_edge_doc(
                MEMBER,
                f"{COLLECTION_CASES}/z_{n}",
                RELATION_AUTHORED,
                meta={"capacity": "kamerlid"},
            )
        )
    edges.append(make_edge_doc(MEMBER, "factions/d66", RELATION_MEMBER_OF))
    store.bulk_insert_or_update_nodes(COLLECTION_DOCUMENTS, papers)
    store.bulk_insert_or_update_nodes(COLLECTION_CASES, cases)
    store.bulk_insert_or_update_edges(edges)  # fmt: skip


def _buckets(store: GraphStore, **query: Any) -> dict[tuple[str, str, str], Any]:
    app.dependency_overrides[get_store] = lambda: store
    try:
        found = TestClient(app).get("/api/nodes/members/jetten", params=query).json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    return {
        (b["relation"], b["direction"], b["collection"]): b
        for b in found["neighbors"]["buckets"]
    }


def test_a_member_signed_counted_per_capacity_over_the_whole_bucket(
    store: GraphStore,
) -> None:
    _seed(store)
    buckets = _buckets(store, limit=2)
    papers = buckets[(RELATION_AUTHORED, "outbound", COLLECTION_DOCUMENTS)]
    assert (papers["total"], len(papers["items"])) == (9, 2)
    assert papers["capacity_counts"] == {
        "kamerlid": 3, "bewindspersoon": 4, "overig": 1, "": 1
    }  # fmt: skip
    cases = buckets[(RELATION_AUTHORED, "outbound", COLLECTION_CASES)]
    assert cases["capacity_counts"] == {"kamerlid": 2}
    # every other bucket has none
    assert (
        buckets[(RELATION_MEMBER_OF, "outbound", "factions")]["capacity_counts"] is None
    )
    # a status filter the table does not know: none either
    filtered = _buckets(store, limit=2, status="canoniek")
    assert (
        filtered[(RELATION_AUTHORED, "outbound", COLLECTION_DOCUMENTS)][
            "capacity_counts"
        ]
        is None
    )
