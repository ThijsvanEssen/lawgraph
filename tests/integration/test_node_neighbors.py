"""The node explorer on a real graph: facets, pages per bucket, filters and hubs.

The unit suite runs on fake stores and never executes AQL, so what a bucket holds, where
its page ends and what a traversal follows is only shown by a server.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.queries.nodes import (
    NeighborFilter,
    get_node_facets,
    get_node_neighborhood,
    get_node_with_neighbors,
)
from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    EDGE_STATUS_CANONIEK,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
    RELATION_IMPLEMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
    RELATION_VERSION_OF,
)
from lawgraph.core.models import TYPE_OF_COLLECTION, NodeType
from lawgraph.db import ArangoStore
from lawgraph.db.edges import make_edge_doc

FOCAL = f"{COLLECTION_INSTRUMENTS}/focal"
ARTICLES = 45
JUDGMENTS = 12
META = {"start": 3, "end": 9, "raw_match": "artikel 3", "qualifier": "lid 2"}


def _node(node_type: NodeType, key: str, **props: Any) -> dict[str, Any]:
    return {
        "_key": key,
        "type": node_type.value,
        "labels": [],
        "props": {"display_name": key, **props},
    }


def _edge(
    from_id: str,
    to_id: str,
    relation: str,
    status: str = EDGE_STATUS_CANONIEK,
    **fields: Any,
) -> dict[str, Any]:
    return make_edge_doc(
        from_id, to_id, relation, source="test", status=status, **fields
    )


def _write(store: ArangoStore, collection: str, docs: list[dict[str, Any]]) -> None:
    for start in range(0, len(docs), 10_000):
        store.db.collection(collection).insert_many(docs[start : start + 10_000])


def _seed_small(store: ArangoStore) -> None:
    """An instrument with 45 articles (PART_OF), 12 judgments (REFERS_TO), two instruments
    that refer to each other, two changes (one proposed) and an annex and a version."""
    _write(
        store,
        COLLECTION_INSTRUMENTS,
        [
            _node(NodeType.INSTRUMENT, key)
            for key in ("focal", "other", "amends", "implements", "cited")
        ],
    )
    articles = [_node(NodeType.ARTICLE, f"a{n:02d}") for n in range(ARTICLES)]
    _write(store, COLLECTION_ARTICLES, articles)
    _write(
        store,
        COLLECTION_JUDGMENTS,
        [_node(NodeType.JUDGMENT, f"j{n:02d}") for n in range(JUDGMENTS)]
        + [_node(NodeType.JUDGMENT, "jz")],
    )
    _write(
        store,
        COLLECTION_ANNEXES,
        [_node(NodeType.ANNEX, "annex", entries=[{"row": "x" * 50}] * 20, label="I")],
    )
    _write(
        store,
        COLLECTION_INSTRUMENT_VERSIONS,
        [_node(NodeType.INSTRUMENT_VERSION, "version", valid_from="2020-01-01")],
    )
    _write(
        store,
        COLLECTION_ARTICLE_VERSIONS,
        [_node(NodeType.ARTICLE_VERSION, "aversion", text="lang " * 1000)],
    )

    edges = [
        _edge(f"{COLLECTION_ARTICLES}/a{n:02d}", FOCAL, RELATION_PART_OF)
        for n in range(ARTICLES)
    ]
    edges += [
        _edge(
            f"{COLLECTION_JUDGMENTS}/j{n:02d}",
            FOCAL,
            RELATION_REFERS_TO,
            confidence=0.9,
        )
        for n in range(JUDGMENTS)
    ]
    # ``jz`` reaches the instrument only through an article.
    edges.append(
        _edge(
            f"{COLLECTION_JUDGMENTS}/jz",
            f"{COLLECTION_ARTICLES}/a00",
            RELATION_REFERS_TO,
        )
    )
    # The same relation to the same collection in both directions.
    edges.append(
        _edge(FOCAL, f"{COLLECTION_INSTRUMENTS}/cited", RELATION_REFERS_TO, meta=META)
    )
    edges.append(_edge(f"{COLLECTION_INSTRUMENTS}/other", FOCAL, RELATION_REFERS_TO))
    edges.append(_edge(FOCAL, f"{COLLECTION_INSTRUMENTS}/amends", RELATION_AMENDS))
    edges.append(
        _edge(
            FOCAL,
            f"{COLLECTION_INSTRUMENTS}/implements",
            RELATION_IMPLEMENTS,
            EDGE_STATUS_VOORGESTELD,
        )
    )
    edges.append(_edge(f"{COLLECTION_ANNEXES}/annex", FOCAL, RELATION_PART_OF))
    edges.append(
        _edge(f"{COLLECTION_INSTRUMENT_VERSIONS}/version", FOCAL, RELATION_VERSION_OF)
    )
    edges.append(
        _edge(
            f"{COLLECTION_ARTICLE_VERSIONS}/aversion",
            f"{COLLECTION_ARTICLES}/a00",
            RELATION_VERSION_OF,
        )
    )
    _write(store, "edges", edges)


@pytest.fixture()
def store(database: str) -> Iterator[ArangoStore]:
    yield ArangoStore()


@pytest.fixture()
def small(store: ArangoStore) -> ArangoStore:
    _seed_small(store)
    return store


@pytest.fixture()
def client(store: ArangoStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.pop(get_store, None)


def _counts(facets: list[Any]) -> dict[tuple[str | None, str, str], int]:
    return {(f.relation, f.direction, f.collection): f.count for f in facets}


def test_facets_count_per_relation_direction_and_collection(small: ArangoStore) -> None:
    facets = get_node_facets(small, COLLECTION_INSTRUMENTS, "focal")

    assert _counts(facets) == {
        (RELATION_AMENDS, "outbound", "instruments"): 1,
        (RELATION_IMPLEMENTS, "outbound", "instruments"): 1,
        (RELATION_PART_OF, "inbound", "annexes"): 1,
        (RELATION_PART_OF, "inbound", "articles"): ARTICLES,
        # The same relation and collection in two directions are two facets.
        (RELATION_REFERS_TO, "inbound", "instruments"): 1,
        (RELATION_REFERS_TO, "inbound", "judgments"): JUDGMENTS,
        (RELATION_REFERS_TO, "outbound", "instruments"): 1,
        (RELATION_VERSION_OF, "inbound", "instrument_versions"): 1,
    }
    keys = [(f.relation, f.direction, f.collection) for f in facets]
    assert keys == sorted(keys)  # the same order on every request


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (
            NeighborFilter(relations=(RELATION_PART_OF,)),
            {("PART_OF", "inbound", "annexes"), ("PART_OF", "inbound", "articles")},
        ),
        (
            NeighborFilter(node_types=("judgment", "annex")),
            {("PART_OF", "inbound", "annexes"), ("REFERS_TO", "inbound", "judgments")},
        ),
        (
            NeighborFilter(direction="outbound"),
            {
                ("AMENDS", "outbound", "instruments"),
                ("IMPLEMENTS", "outbound", "instruments"),
                ("REFERS_TO", "outbound", "instruments"),
            },
        ),
        (
            NeighborFilter(status=EDGE_STATUS_VOORGESTELD),
            {("IMPLEMENTS", "outbound", "instruments")},
        ),
        (
            NeighborFilter(
                relations=(RELATION_REFERS_TO, RELATION_AMENDS),
                node_types=("instrument",),
                direction="inbound",
                status=EDGE_STATUS_CANONIEK,
            ),
            {("REFERS_TO", "inbound", "instruments")},
        ),
    ],
)
def test_facets_take_every_filter(
    small: ArangoStore, filters: NeighborFilter, expected: set[tuple[str, str, str]]
) -> None:
    facets = get_node_facets(small, COLLECTION_INSTRUMENTS, "focal", filters=filters)
    assert {(f.relation, f.direction, f.collection) for f in facets} == expected


def test_a_node_without_edges_has_no_facets_and_no_buckets(small: ArangoStore) -> None:
    assert get_node_facets(small, COLLECTION_ARTICLES, "a44")[0].count == 1
    _write(small, COLLECTION_INSTRUMENTS, [_node(NodeType.INSTRUMENT, "alone")])
    assert get_node_facets(small, COLLECTION_INSTRUMENTS, "alone") == []
    assert get_node_with_neighbors(small, COLLECTION_INSTRUMENTS, "alone").buckets == []


def _bucket(data: Any, relation: str, direction: str, collection: str) -> Any:
    (bucket,) = [
        b
        for b in data.buckets
        if (b.facet.relation, b.facet.direction, b.facet.collection)
        == (relation, direction, collection)
    ]
    return bucket


def test_a_bucket_is_paged_to_its_end(small: ArangoStore) -> None:
    """45 articles at 20 a page: 20, 20 and a last page of 5 that has no next page."""
    seen: list[str] = []
    offset: int | None = 0
    pages = []
    while offset is not None:
        data = get_node_with_neighbors(
            small, COLLECTION_INSTRUMENTS, "focal", limit=20, offset=offset
        )
        bucket = _bucket(data, RELATION_PART_OF, "inbound", "articles")
        assert bucket.facet.count == ARTICLES
        pages.append((offset, len(bucket.entries), bucket.next_offset))
        seen += [e.doc["_id"] for e in bucket.entries]
        offset = bucket.next_offset

    assert pages == [(0, 20, 20), (20, 20, 40), (40, 5, None)]
    assert (
        len(seen) == len(set(seen)) == ARTICLES
    )  # every article once, no page overlaps


def test_a_page_that_ends_exactly_at_the_total_has_no_next_page(
    small: ArangoStore,
) -> None:
    data = get_node_with_neighbors(
        small, COLLECTION_INSTRUMENTS, "focal", limit=15, offset=30
    )
    bucket = _bucket(data, RELATION_PART_OF, "inbound", "articles")
    assert len(bucket.entries) == 15 and bucket.next_offset is None
    first = get_node_with_neighbors(small, COLLECTION_INSTRUMENTS, "focal", limit=15)
    assert _bucket(first, RELATION_PART_OF, "inbound", "articles").next_offset == 15


def test_paging_applies_to_every_bucket_and_a_bucket_past_its_end_is_empty(
    small: ArangoStore,
) -> None:
    data = get_node_with_neighbors(
        small, COLLECTION_INSTRUMENTS, "focal", limit=10, offset=10
    )
    articles = _bucket(data, RELATION_PART_OF, "inbound", "articles")
    judgments = _bucket(data, RELATION_REFERS_TO, "inbound", "judgments")
    single = _bucket(data, RELATION_AMENDS, "outbound", "instruments")
    assert (len(articles.entries), articles.next_offset) == (10, 20)
    assert (len(judgments.entries), judgments.next_offset) == (2, None)  # 12 in all
    # One edge, and the page starts after it: the bucket is still there, with its total.
    assert (
        single.facet.count == 1 and single.entries == [] and single.next_offset is None
    )


def test_the_same_page_comes_back_on_every_request(small: ArangoStore) -> None:
    def ids() -> list[str]:
        data = get_node_with_neighbors(
            small, COLLECTION_INSTRUMENTS, "focal", limit=7, offset=7
        )
        return [
            e.doc["_id"]
            for e in _bucket(data, "PART_OF", "inbound", "articles").entries
        ]

    assert ids() == ids() and len(ids()) == 7


def test_buckets_of_the_two_directions_stay_apart(small: ArangoStore) -> None:
    data = get_node_with_neighbors(small, COLLECTION_INSTRUMENTS, "focal")
    out = _bucket(data, RELATION_REFERS_TO, "outbound", "instruments")
    into = _bucket(data, RELATION_REFERS_TO, "inbound", "instruments")
    assert [e.doc["_id"] for e in out.entries] == [f"{COLLECTION_INSTRUMENTS}/cited"]
    assert [e.doc["_id"] for e in into.entries] == [f"{COLLECTION_INSTRUMENTS}/other"]
    assert (
        out.entries[0].direction == "outbound"
        and into.entries[0].direction == "inbound"
    )


@pytest.mark.parametrize(
    "filters",
    [
        NeighborFilter(relations=(RELATION_REFERS_TO,)),
        NeighborFilter(node_types=("instrument",)),
        NeighborFilter(direction="inbound"),
        NeighborFilter(status=EDGE_STATUS_VOORGESTELD),
    ],
)
def test_the_neighbours_of_a_page_obey_the_filter_and_its_totals_count_the_rest(
    small: ArangoStore, filters: NeighborFilter
) -> None:
    data = get_node_with_neighbors(
        small, COLLECTION_INSTRUMENTS, "focal", filters=filters, limit=200
    )
    facets = get_node_facets(small, COLLECTION_INSTRUMENTS, "focal", filters=filters)
    assert [b.facet for b in data.buckets] == facets
    for bucket in data.buckets:
        assert len(bucket.entries) == bucket.facet.count
        for entry in bucket.entries:
            assert entry.direction == bucket.facet.direction
            assert entry.relation == bucket.facet.relation
            assert entry.doc["_id"].startswith(bucket.facet.collection + "/")
            if filters.status:
                assert entry.edge["status"] == filters.status


def test_an_entry_carries_its_edge(small: ArangoStore) -> None:
    data = get_node_with_neighbors(small, COLLECTION_INSTRUMENTS, "focal")
    entry = _bucket(data, RELATION_REFERS_TO, "outbound", "instruments").entries[0]
    assert entry.edge["meta"] == META and entry.edge["status"] == EDGE_STATUS_CANONIEK
    proposed = _bucket(data, RELATION_IMPLEMENTS, "outbound", "instruments").entries[0]
    assert proposed.edge["status"] == EDGE_STATUS_VOORGESTELD
    cited = _bucket(data, RELATION_REFERS_TO, "inbound", "judgments").entries[0]
    assert cited.confidence == 0.9


def test_every_node_type_lives_in_the_collection_that_says_so(
    small: ArangoStore, database: str
) -> None:
    """Facets say the type of a neighbour from its collection, without reading it."""
    for collection in TYPE_OF_COLLECTION:
        wrong = list(
            small.query(
                f"FOR n IN {collection} FILTER n.type != @type RETURN n._id",
                {"type": TYPE_OF_COLLECTION[collection].value},
            )
        )
        assert wrong == [], collection


def test_the_versions_and_annexes_can_be_explored(
    client: TestClient, small: ArangoStore
) -> None:
    for collection, key, relation, neighbour in [
        (COLLECTION_ANNEXES, "annex", RELATION_PART_OF, "instruments"),
        (COLLECTION_INSTRUMENT_VERSIONS, "version", RELATION_VERSION_OF, "instruments"),
        (COLLECTION_ARTICLE_VERSIONS, "aversion", RELATION_VERSION_OF, "articles"),
    ]:
        body = client.get(f"/api/nodes/{collection}/{key}").json()
        assert body["node"]["id"] == f"{collection}/{key}"
        (bucket,) = body["neighbors"]["buckets"]
        assert (bucket["relation"], bucket["direction"], bucket["collection"]) == (
            relation,
            "outbound",
            neighbour,
        )
        assert bucket["total"] == 1 and len(bucket["items"]) == 1
        assert client.get(f"/api/nodes/{collection}/{key}/facets").json()["total"] == 1
        assert (
            client.get(f"/api/nodes/{collection}/{key}/neighborhood").status_code == 200
        )
    assert client.get("/api/nodes/raw_sources/x").status_code == 400


def test_bulky_props_of_the_new_collections_stay_out_of_the_graph_views(
    client: TestClient, small: ArangoStore
) -> None:
    node = client.get("/api/nodes/annexes/annex").json()["node"]
    assert "entries" not in (node["props"] or {}) and node["props"]["label"] == "I"
    body = client.get("/api/nodes/instruments/focal").json()
    annex = next(
        b for b in body["neighbors"]["buckets"] if b["collection"] == "annexes"
    )
    assert "entries" not in annex["items"][0]["props"]
    version = client.get("/api/nodes/article_versions/aversion").json()["node"]
    assert "text" not in (version["props"] or {})
    hood = client.get("/api/nodes/instruments/focal/neighborhood?depth=1").json()
    assert all("entries" not in (n["props"] or {}) for n in hood["nodes"])


def test_the_route_pages_filters_and_describes_the_edge(
    client: TestClient, small: ArangoStore
) -> None:
    body = client.get(
        "/api/nodes/instruments/focal?relations=PART_OF&node_types=article&limit=20&offset=40"
    ).json()
    neighbors = body["neighbors"]
    assert neighbors["total"] == ARTICLES
    (bucket,) = neighbors["buckets"]
    assert bucket["type"] == "article" and bucket["total"] == ARTICLES
    assert len(bucket["items"]) == 5 and bucket["next_offset"] is None
    first = bucket["items"][0]
    assert first["edge_id"] and first["status"] == "canoniek" and first["meta"] == {}

    everything = client.get("/api/nodes/instruments/focal").json()["neighbors"]
    refers = next(
        b
        for b in everything["buckets"]
        if (b["relation"], b["direction"], b["collection"])
        == ("REFERS_TO", "outbound", "instruments")
    )
    assert refers["items"][0]["meta"] == META and refers["type"] == "instrument"
    articles = next(b for b in everything["buckets"] if b["collection"] == "articles")
    assert len(articles["items"]) == 30 and articles["next_offset"] == 30  # the default

    facets = client.get("/api/nodes/instruments/focal/facets?direction=outbound").json()
    assert facets["total"] == 3
    assert {(f["relation"], f["type"]) for f in facets["items"]} == {
        ("AMENDS", "instrument"),
        ("IMPLEMENTS", "instrument"),
        ("REFERS_TO", "instrument"),
    }


@pytest.mark.parametrize(
    "query",
    [
        "relations=NOPE",
        "relations=PART_OF,NOPE",
        "node_types=articles",
        "direction=sideways",
        "status=gone",
    ],
)
@pytest.mark.parametrize("path", ["", "/facets", "/neighborhood"])
def test_the_route_refuses_what_does_not_exist(
    client: TestClient, path: str, query: str
) -> None:
    assert client.get(f"/api/nodes/instruments/focal{path}?{query}").status_code == 422


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1"])
def test_the_route_bounds_the_page(client: TestClient, query: str) -> None:
    assert client.get(f"/api/nodes/instruments/focal?{query}").status_code == 422


def _hood(store: ArangoStore, **kwargs: Any) -> dict[str, Any]:
    return get_node_neighborhood(store, COLLECTION_INSTRUMENTS, "focal", **kwargs)


def _ids(rows: list[dict[str, Any]]) -> set[str]:
    return {row["_id"] for row in rows}


def test_the_neighbourhood_without_filters_walks_every_edge(small: ArangoStore) -> None:
    data = _hood(small, depth=2)
    assert f"{COLLECTION_JUDGMENTS}/jz" in _ids(data["nodes"])  # focal <- a00 <- jz
    assert f"{COLLECTION_ANNEXES}/annex" in _ids(data["nodes"])
    assert (
        len(data["nodes"]) == ARTICLES + JUDGMENTS + 1 + 4 + 3
    )  # jz, instruments, annex, versions


def test_the_neighbourhood_follows_only_the_relations_asked_for(
    small: ArangoStore,
) -> None:
    data = _hood(small, depth=2, filters=NeighborFilter(relations=(RELATION_PART_OF,)))
    assert {n["_id"].split("/")[0] for n in data["nodes"]} == {"articles", "annexes"}
    assert {e["relation"] for e in data["edges"]} == {RELATION_PART_OF}
    # a00 <- jz is REFERS_TO: a judgment two hops away is no longer reached.
    assert f"{COLLECTION_JUDGMENTS}/jz" not in _ids(data["nodes"])


def test_the_neighbourhood_can_follow_the_edges_one_way(small: ArangoStore) -> None:
    data = _hood(small, depth=2, filters=NeighborFilter(direction="outbound"))
    assert _ids(data["nodes"]) == {
        f"{COLLECTION_INSTRUMENTS}/{key}" for key in ("cited", "amends", "implements")
    }
    data = _hood(small, depth=1, filters=NeighborFilter(direction="inbound"))
    assert f"{COLLECTION_INSTRUMENTS}/cited" not in _ids(data["nodes"])
    assert f"{COLLECTION_INSTRUMENTS}/other" in _ids(data["nodes"])


def test_the_neighbourhood_can_keep_to_one_status(small: ArangoStore) -> None:
    data = _hood(small, filters=NeighborFilter(status=EDGE_STATUS_VOORGESTELD))
    assert _ids(data["nodes"]) == {f"{COLLECTION_INSTRUMENTS}/implements"}
    assert [e["status"] for e in data["edges"]] == [EDGE_STATUS_VOORGESTELD]


def test_the_neighbourhood_walks_only_through_the_node_types_asked_for(
    small: ArangoStore,
) -> None:
    data = _hood(small, depth=2, filters=NeighborFilter(node_types=("judgment",)))
    ids = _ids(data["nodes"])
    # The twelve that cite the instrument; ``jz`` cites an article, and articles are out.
    assert ids == {f"{COLLECTION_JUDGMENTS}/j{n:02d}" for n in range(JUDGMENTS)}

    data = _hood(
        small, depth=2, filters=NeighborFilter(node_types=("article", "judgment"))
    )
    assert f"{COLLECTION_JUDGMENTS}/jz" in _ids(data["nodes"])
    assert {n["type"] for n in data["nodes"]} == {"article", "judgment"}
    assert data["focal"]["_id"] == FOCAL  # the focal node is kept whatever its type


def test_the_filters_of_the_neighbourhood_run_in_the_traversal(
    small: ArangoStore,
) -> None:
    asked: list[tuple[str, dict[str, Any]]] = []
    run = small.query

    def recording(aql: str, bind_vars: dict[str, Any] | None = None, **kw: Any) -> Any:
        asked.append((aql, bind_vars or {}))
        return run(aql, bind_vars, **kw)

    small.query = recording  # type: ignore[method-assign]
    _hood(
        small,
        depth=3,
        filters=NeighborFilter(
            relations=(RELATION_PART_OF,), status=EDGE_STATUS_CANONIEK
        ),
    )
    (aql, bind_vars), *_ = asked
    nodes = small.db.aql.explain(aql, bind_vars=bind_vars)["nodes"]
    kinds = [node["type"] for node in nodes]
    traversal = kinds.index("TraversalNode")
    # Nothing filters the vertices behind the traversal: it never left along another edge.
    assert "FilterNode" not in kinds[traversal : kinds.index("ReturnNode")], kinds


def test_the_neighbourhood_response_follows_the_filters(
    client: TestClient, small: ArangoStore
) -> None:
    body = client.get(
        "/api/nodes/instruments/focal/neighborhood?depth=2&relations=PART_OF&node_types=article"
    ).json()
    assert {n["type"] for n in body["nodes"]} == {"instrument", "article"}
    assert body["nodes"][0]["id"] == FOCAL
    assert {e["relation"] for e in body["edges"]} == {"PART_OF"}


# ── the graph layers ────────────────────────────────────────────────────────────────────


def test_the_global_graph_keeps_the_node_types_and_relations_asked_for(
    small: ArangoStore,
) -> None:
    from lawgraph.api.queries.graph import get_global_graph

    everything = get_global_graph(small)
    assert len(everything.instruments) == 5 and len(everything.articles) == ARTICLES
    assert len(everything.judgments) == JUDGMENTS + 1
    assert {e.relation_type for e in everything.edges} == {
        RELATION_PART_OF,
        RELATION_REFERS_TO,
        RELATION_AMENDS,
        RELATION_IMPLEMENTS,
    }

    no_judgments = get_global_graph(small, node_types=("instrument", "article"))
    assert no_judgments.judgments == []
    assert {e.relation_type for e in no_judgments.edges} == {
        RELATION_PART_OF,
        RELATION_REFERS_TO,  # focal -> cited
        RELATION_AMENDS,
        RELATION_IMPLEMENTS,
    }
    assert all(e.from_id.split("/")[0] != "judgments" for e in no_judgments.edges)

    only_judgments = get_global_graph(small, node_types=("judgment",))
    assert only_judgments.instruments == [] and only_judgments.articles == []
    assert [e.relation_type for e in only_judgments.edges] == []  # jz -> a00 needs both

    part_of = get_global_graph(small, relations=(RELATION_PART_OF,))
    assert {e.relation_type for e in part_of.edges} == {RELATION_PART_OF}
    assert len(part_of.edges) == ARTICLES  # the annex is no node of this graph


def test_the_instrument_layer_returns_only_the_relations_asked_for(
    small: ArangoStore,
) -> None:
    from lawgraph.api.queries.graph import get_instrument_layer_graph

    every = get_instrument_layer_graph(small)
    assert {e.relation_type for e in every.edges} == {
        RELATION_REFERS_TO,
        RELATION_AMENDS,
        RELATION_IMPLEMENTS,
    }
    amends = get_instrument_layer_graph(small, relations=(RELATION_AMENDS,))
    assert [(e.relation_type, e.to_id) for e in amends.edges] == [
        (RELATION_AMENDS, f"{COLLECTION_INSTRUMENTS}/amends")
    ]
    assert len(amends.instruments) == len(every.instruments) == 5


# ── a hub ───────────────────────────────────────────────────────────────────────────────

HUB = f"{COLLECTION_INSTRUMENTS}/hub"
HUB_ARTICLES = 60_000
HUB_JUDGMENTS = 20_000
# What a query may hold: the edges of the hub with their meta are 60 MB. Read whole by the
# application, or gathered in the server (a COLLECT ... INTO group), they would not fit.
MEMORY_LIMIT = 12_000_000


def _seed_hub(store: ArangoStore) -> None:
    _write(store, COLLECTION_INSTRUMENTS, [_node(NodeType.INSTRUMENT, "hub")])
    _write(
        store,
        COLLECTION_ARTICLES,
        [_node(NodeType.ARTICLE, f"a{n}") for n in range(HUB_ARTICLES)],
    )
    _write(
        store,
        COLLECTION_JUDGMENTS,
        [_node(NodeType.JUDGMENT, f"j{n}") for n in range(HUB_JUDGMENTS)],
    )
    meta = {"snippet": "een tekst rondom de verwijzing " * 10, **META}
    edges = [
        _edge(f"{COLLECTION_ARTICLES}/a{n}", HUB, RELATION_PART_OF, meta=meta)
        for n in range(HUB_ARTICLES)
    ]
    edges += [
        _edge(f"{COLLECTION_JUDGMENTS}/j{n}", HUB, RELATION_REFERS_TO, meta=meta)
        for n in range(HUB_JUDGMENTS)
    ]
    _write(store, "edges", edges)


def _memory_limited(store: ArangoStore, limit: int) -> None:
    """Make every query of ``store`` fail when it holds more than ``limit`` bytes."""

    def query(aql: str, bind_vars: dict[str, Any] | None = None, **kw: Any) -> Any:
        cursor = store.db.aql.execute(
            aql, bind_vars=bind_vars or {}, memory_limit=limit, stream=True
        )
        return iter(cursor)  # type: ignore[arg-type]

    store.query = query  # type: ignore[method-assign]


def test_a_hub_with_tens_of_thousands_of_edges_is_counted_and_paged_in_the_database(
    store: ArangoStore,
) -> None:
    """The edges of a hub (an instrument with all its articles, a faction with its votes) are
    counted by the server and paged from the edge index: none is built as a whole, on either
    side, so a query that may hold 12 MB answers for 80,000 edges of 700 bytes."""
    _seed_hub(store)
    _memory_limited(store, MEMORY_LIMIT)

    facets = get_node_facets(store, COLLECTION_INSTRUMENTS, "hub")
    assert _counts(facets) == {
        (RELATION_PART_OF, "inbound", "articles"): HUB_ARTICLES,
        (RELATION_REFERS_TO, "inbound", "judgments"): HUB_JUDGMENTS,
    }

    first = get_node_with_neighbors(store, COLLECTION_INSTRUMENTS, "hub", limit=100)
    assert [len(b.entries) for b in first.buckets] == [100, 100]
    assert [b.next_offset for b in first.buckets] == [100, 100]

    last = get_node_with_neighbors(
        store, COLLECTION_INSTRUMENTS, "hub", limit=100, offset=HUB_ARTICLES - 30
    )
    articles = _bucket(last, RELATION_PART_OF, "inbound", "articles")
    assert len(articles.entries) == 30 and articles.next_offset is None
    judgments = _bucket(last, RELATION_REFERS_TO, "inbound", "judgments")
    assert judgments.entries == [] and judgments.facet.count == HUB_JUDGMENTS

    only = get_node_with_neighbors(
        store,
        COLLECTION_INSTRUMENTS,
        "hub",
        filters=NeighborFilter(
            relations=(RELATION_REFERS_TO,), status=EDGE_STATUS_CANONIEK
        ),
    )
    assert len(only.buckets) == 1 and only.buckets[0].facet.count == HUB_JUDGMENTS


def test_the_neighbourhood_of_a_hub_stops_at_its_cap(store: ArangoStore) -> None:
    _seed_hub(store)
    _memory_limited(store, MEMORY_LIMIT)

    data = get_node_neighborhood(store, COLLECTION_INSTRUMENTS, "hub", depth=2, cap=50)
    assert len(data["nodes"]) == 50
    filtered = get_node_neighborhood(
        store,
        COLLECTION_INSTRUMENTS,
        "hub",
        depth=2,
        cap=50,
        filters=NeighborFilter(
            relations=(RELATION_REFERS_TO,), node_types=("judgment",)
        ),
    )
    assert len(filtered["nodes"]) == 50
    assert {n["type"] for n in filtered["nodes"]} == {"judgment"}
    assert {e["relation"] for e in filtered["edges"]} == {RELATION_REFERS_TO}
