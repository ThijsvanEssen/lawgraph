"""``GET /api/nodes/shared`` on a real graph: what two or three nodes have in common."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api import middleware
from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.core.models import NodeType
from lawgraph.db import GraphStore
from lawgraph.db.edges import make_edge_doc
from tests.asserts import assert_status

A, B, C, D, E = (f"{COLLECTION_ARTICLES}/{key}" for key in "abcde")
LAW = f"{COLLECTION_INSTRUMENTS}/law"


def _judgment(key: str, tier: str, cited: int, *subjects: str) -> dict[str, Any]:
    return {
        "key": key,
        "type": NodeType.JUDGMENT.value,
        "labels": [],
        "props": {
            "ecli": f"ECLI:NL:X:2020:{key}",
            "tier": tier,
            "court_code": "HR" if tier == "hoge_raad" else "RBAMS",
            "subjects": list(subjects),
            "inbound_citation_count": cited,
        },
    }


def _node(node_type: NodeType, key: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type.value, "labels": [], "props": props}


def _edge(source: str, target: str, relation: str, **fields: Any) -> dict[str, Any]:
    return make_edge_doc(source, target, relation, source="test", **fields)


@pytest.fixture()
def shared(store: GraphStore) -> GraphStore:
    """Articles a and b have the law, the judgments j1 and j2 and the article c in common
    (a refers to c, c refers to b); j3 cites a alone, j4 b alone, d is a's alone, and e
    shares j1 with them."""
    store.bulk_insert_or_update_nodes(
        COLLECTION_ARTICLES,
        [
            _node(NodeType.ARTICLE, key, inbound_citation_count=n)
            for key, n in zip("abcde", (9, 8, 7, 6, 5), strict=True)
        ],
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_INSTRUMENTS, [_node(NodeType.INSTRUMENT, "law")]
    )
    store.bulk_insert_or_update_nodes(
        COLLECTION_JUDGMENTS,
        [
            _judgment("j1", "hoge_raad", 50, "Strafrecht; Materieel strafrecht"),
            _judgment("j2", "rechtbank", 5, "Civiel recht; Verbintenissenrecht"),
            _judgment("j3", "rechtbank", 99, "Civiel recht"),
            _judgment("j4", "hoge_raad", 99, "Strafrecht"),
        ],
    )
    cites = [
        ("j1", A),
        ("j1", B),
        ("j1", E),
        ("j2", A),
        ("j2", B),
        ("j3", A),
        ("j4", B),
    ]
    store.bulk_insert_or_update_edges(
        [
            _edge(A, LAW, RELATION_PART_OF),
            _edge(B, LAW, RELATION_PART_OF),
            _edge(A, C, RELATION_REFERS_TO),
            _edge(C, B, RELATION_REFERS_TO),
            _edge(A, D, RELATION_REFERS_TO),
            # the two sources refer to each other: neither is the other's neighbour
            _edge(A, B, RELATION_REFERS_TO),
        ]
        + [
            _edge(f"{COLLECTION_JUDGMENTS}/{j}", a, RELATION_REFERS_TO)
            for j, a in cites
        ]
    )
    return store


@pytest.fixture()
def client(shared: GraphStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: shared
    yield TestClient(app)
    app.dependency_overrides.pop(get_store, None)


def _get(client: TestClient, ids: str, query: str = "") -> dict[str, Any]:
    response = client.get(f"/api/nodes/shared?ids={ids}{query}")
    assert_status(response, 200)
    body: dict[str, Any] = response.json()
    return body


def _keys(body: dict[str, Any], collection: str) -> list[str]:
    (bucket,) = [b for b in body["buckets"] if b["collection"] == collection]
    return [item["id"] for item in bucket["items"]]


def test_two_nodes_share_what_both_have_in_every_direction(client: TestClient) -> None:
    body = _get(client, f"{A},{B}")

    assert {b["collection"]: b["total"] for b in body["buckets"]} == {
        "articles": 1,  # c: a refers to it, it refers to b
        "instruments": 1,
        "judgments": 2,
    }
    assert body["total"] == 4
    assert _keys(body, "articles") == [C]
    assert _keys(body, "judgments") == [f"{COLLECTION_JUDGMENTS}/j1", "judgments/j2"]
    assert body["facets"]["collection"] == [
        {"value": "judgments", "count": 2},
        {"value": "articles", "count": 1},
        {"value": "instruments", "count": 1},
    ]


def test_a_neighbour_says_by_which_edge_it_hangs_at_each_node(
    client: TestClient,
) -> None:
    body = _get(client, f"{A},{B}")
    (article,) = [b for b in body["buckets"] if b["collection"] == "articles"][0][
        "items"
    ]

    assert [
        (link["source"], link["relation"], link["direction"])
        for link in article["links"]
    ] == [(A, "REFERS_TO", "outbound"), (B, "REFERS_TO", "inbound")]
    assert all(link["edge_id"] and link["status"] for link in article["links"]), (
        article["links"]
    )


def test_the_most_cited_comes_first_and_the_key_orders_when_asked(
    client: TestClient,
) -> None:
    assert _keys(_get(client, f"{A},{B}"), "judgments")[0] == "judgments/j1"
    by_key = _get(client, f"{A},{B}", "&sort=key")
    assert _keys(by_key, "judgments") == ["judgments/j1", "judgments/j2"]
    # j3 and j4 are cited more, but hang at one node alone
    assert "judgments/j3" not in _keys(by_key, "judgments")


def test_three_nodes_share_less_than_two(client: TestClient) -> None:
    body = _get(client, f"{A},{B},{E}")

    assert [(b["collection"], b["total"]) for b in body["buckets"]] == [
        ("judgments", 1)
    ]
    assert [link["source"] for link in body["buckets"][0]["items"][0]["links"]] == [
        A,
        B,
        E,
    ]


def test_a_page_of_a_bucket_counts_from_its_offset(client: TestClient) -> None:
    first = _get(client, f"{A},{B}", "&limit=1")
    (judgments,) = [b for b in first["buckets"] if b["collection"] == "judgments"]
    assert (judgments["total"], judgments["next_offset"]) == (2, 1)
    second = _get(client, f"{A},{B}", "&limit=1&offset=1")
    assert _keys(second, "judgments") == ["judgments/j2"]
    (last,) = [b for b in second["buckets"] if b["collection"] == "judgments"]
    assert last["next_offset"] is None
    # a bucket that ends before the offset keeps its total and has no items
    assert _keys(second, "articles") == []


def test_the_tier_and_area_narrow_the_judgments_and_count_each_other(
    client: TestClient,
) -> None:
    body = _get(client, f"{A},{B}", "&tier=hoge_raad")

    assert _keys(body, "judgments") == ["judgments/j1"]
    assert _keys(body, "articles") == [C]  # the others stay whole
    # the tier facet is under the area alone, the area facet under the tier
    assert body["facets"]["tier"] == [
        {"value": "hoge_raad", "count": 1},
        {"value": "rechtbank", "count": 1},
    ]
    assert body["facets"]["subject_area"] == [{"value": "Strafrecht", "count": 1}]

    by_area = _get(client, f"{A},{B}", "&subject_area=Civiel recht")
    assert _keys(by_area, "judgments") == ["judgments/j2"]
    assert by_area["facets"]["tier"] == [{"value": "rechtbank", "count": 1}]
    assert by_area["facets"]["subject_area"] == [
        {"value": "Civiel recht", "count": 1},
        {"value": "Strafrecht", "count": 1},
    ]


def test_the_edge_filters_of_the_node_route_narrow_what_is_shared(
    client: TestClient,
) -> None:
    body = _get(client, f"{A},{B}", "&relations=PART_OF")
    assert [(b["collection"], b["total"]) for b in body["buckets"]] == [
        ("instruments", 1)
    ]
    body = _get(client, f"{A},{B}", "&node_types=judgment&direction=outbound")
    assert body["buckets"] == []  # a judgment's edges reach the articles: inbound there


def test_a_request_that_names_no_pair_or_a_missing_node_is_refused(
    client: TestClient,
) -> None:
    assert_status(client.get(f"/api/nodes/shared?ids={A}"), 422)
    assert_status(client.get(f"/api/nodes/shared?ids={A},{A}"), 422)
    assert_status(client.get(f"/api/nodes/shared?ids={A},nonsense"), 422)
    assert_status(client.get(f"/api/nodes/shared?ids={A},articles/nope"), 404)


def test_shared_neighbours_need_one_connection_of_the_pool(
    client: TestClient, shared: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With every other connection of the pool taken (the explorer asks one per pair of
    nodes, some fifty at once), a request is answered: it read its one row and then the
    nodes it names while holding the read, so it waited for a second connection, as every
    request beside it did, until its deadline; the reads they held stayed idle in their
    transactions and the pool of eight was empty for 21 minutes (23 Oct 19:50 UTC)."""
    monkeypatch.setattr(middleware, "API_REQUEST_TIMEOUT_MS", 3000)
    pool = shared.pool
    others = [pool.getconn() for _ in range(pool.get_stats()["pool_size"] - 1)]
    try:
        response = client.get(f"/api/nodes/shared?ids={A},{B}")
    finally:
        for conn in others:
            pool.putconn(conn)
    assert_status(response, 200)
    usage = shared.pool_usage()["requests"]
    assert usage is not None and usage["free"] == usage["size"]
