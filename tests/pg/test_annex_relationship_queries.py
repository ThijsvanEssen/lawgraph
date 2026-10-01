"""The annex and article relationship queries on a real PostgreSQL."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries.annexes import get_annex, get_annex_referenced_by
from lawgraph.db.queries.relationships import (
    get_article_relationship_data,
    search_relationships,
)


def _doc(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _edge(key: str, source: str, target: str, relation: str, **rest: Any) -> dict:
    return {
        "_key": key,
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "bwb",
        "status": "canoniek",
        **rest,
    }


@pytest.fixture()
def graph(store: GraphStore) -> GraphStore:
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _doc("A_1", "article", bwb_id="A", article_number="1"),
            _doc("A_2", "article", bwb_id="A", article_number="2"),
            _doc("B_1", "article", bwb_id="B", article_number="1"),
            _doc("B_2", "article", bwb_id="B", article_number="2"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments", [_doc("A", "instrument"), _doc("B", "instrument")]
    )
    store.bulk_insert_or_update_nodes(
        "annexes", [_doc("A_bijlage", "annex", bwb_id="A", title="Bijlage")]
    )
    store.bulk_insert_or_update_nodes("judgments", [_doc("ecli_x", "judgment")])
    store.bulk_insert_or_update_edges(
        [
            _edge("pa1", "articles/A_1", "instruments/A", "PART_OF"),
            _edge("pa2", "articles/A_2", "instruments/A", "PART_OF"),
            # B_1: the first PART_OF by target is gone, the next one counts
            _edge("pb0", "articles/B_1", "instruments/AAA", "PART_OF"),
            _edge("pb1", "articles/B_1", "instruments/B", "PART_OF"),
            # B_2 has no instrument: PART_OF points article → instrument, so an edge the
            # other way does not give it one
            _edge("pb2", "instruments/B", "articles/B_2", "PART_OF"),
            _edge(
                "r3",
                "articles/A_1",
                "articles/B_1",
                "REFERS_TO",
                semantic_type="definition",
                explanation="defines",
            ),
            _edge("r1", "articles/A_1", "articles/A_2", "REFERS_TO", confidence=1),
            _edge("r2", "articles/A_1", "articles/B_2", "REFERS_TO"),
            _edge("r9", "articles/A_1", "articles/gone", "REFERS_TO"),
            _edge("r4", "articles/B_2", "articles/A_1", "REFERS_TO", semantic_type="x"),
            _edge("r5", "judgments/ecli_x", "articles/A_1", "REFERS_TO"),
            _edge("r6", "articles/A_2", "articles/B_2", "REFERS_TO", semantic_type="y"),
            _edge(
                "r7",
                "judgments/ecli_x",
                "articles/B_2",
                "REFERS_TO",
                semantic_type="definition",
            ),
            _edge(
                "r8", "articles/B_1", "articles/gone", "REFERS_TO", semantic_type="x"
            ),
            _edge("s2", "articles/B_1", "annexes/A_bijlage", "SCOPED_BY"),
            _edge("s1", "articles/A_1", "annexes/A_bijlage", "SCOPED_BY"),
            _edge("s0", "articles/A_2", "annexes/A_bijlage", "SCOPED_BY"),
            _edge("s9", "articles/gone", "annexes/A_bijlage", "SCOPED_BY"),
            _edge("s8", "articles/A_1", "annexes/gone", "SCOPED_BY"),
        ]
    )
    return store


def test_an_annex_and_what_refers_to_it(graph: GraphStore) -> None:
    assert get_annex(graph, "A_bijlage") == {
        "_key": "A_bijlage",
        "_id": "annexes/A_bijlage",
        "type": "annex",
        "labels": [],
        "props": {"bwb_id": "A", "title": "Bijlage"},
    }
    assert get_annex(graph, "nope") is None
    rows = get_annex_referenced_by(graph, "A_bijlage")
    # by the article id; the edge from a missing article is left out
    assert [(r["edge"]["_key"], r["article"]["_id"]) for r in rows] == [
        ("s1", "articles/A_1"),
        ("s0", "articles/A_2"),
        ("s2", "articles/B_1"),
    ]
    assert list(rows[0]) == ["edge", "article"]
    assert rows[0]["edge"] == {
        "_key": "s1",
        "_id": "edges/s1",
        "_from": "articles/A_1",
        "_to": "annexes/A_bijlage",
        "relation": "SCOPED_BY",
        "source": "bwb",
        "status": "canoniek",
    }
    assert rows[0]["article"]["props"] == {"bwb_id": "A", "article_number": "1"}
    assert get_annex_referenced_by(graph, "nope") == []


def test_the_relationships_of_an_article(graph: GraphStore) -> None:
    data = get_article_relationship_data(graph, "articles/A_1")
    assert list(data) == ["upstream", "downstream", "scope"]
    # by edge key; the edge to a missing article is left out
    up = data["upstream"]
    assert [(r["edge"]["_key"], r["target"]["_id"]) for r in up] == [
        ("r1", "articles/A_2"),
        ("r2", "articles/B_2"),
        ("r3", "articles/B_1"),
    ]
    assert list(up[0]) == ["edge", "target", "instrument"]
    assert up[0]["instrument"] == {
        "_key": "A",
        "_id": "instruments/A",
        "type": "instrument",
        "labels": [],
        "props": {},
    }
    assert up[0]["edge"]["confidence"] == 1
    assert up[1]["instrument"] is None
    assert up[2]["instrument"]["_id"] == "instruments/B"
    assert up[2]["edge"]["semantic_type"] == "definition"
    assert up[2]["edge"]["explanation"] == "defines"
    # only from articles: the judgment's reference is not one
    down = data["downstream"]
    assert [(r["edge"]["_key"], r["target"]["_id"]) for r in down] == [
        ("r4", "articles/B_2")
    ]
    assert down[0]["instrument"] is None
    assert [(r["edge"]["_key"], r["annex"]["_id"]) for r in data["scope"]] == [
        ("s1", "annexes/A_bijlage")
    ]
    assert list(data["scope"][0]) == ["edge", "annex"]
    assert get_article_relationship_data(graph, "articles/none") == {
        "upstream": [],
        "downstream": [],
        "scope": [],
    }


def test_search_relationships_by_edge_key(graph: GraphStore) -> None:
    rows, total = search_relationships(graph)
    # r8 counts but its target is gone, so it is not shown
    assert total == 5
    assert [r["edge"]["_key"] for r in rows] == ["r3", "r4", "r6", "r7"]
    assert list(rows[0]) == ["edge", "source_article", "target"]
    assert rows[0]["source_article"]["_id"] == "articles/A_1"
    assert rows[0]["target"]["_id"] == "articles/B_1"
    # a judgment is a source too, without a law filter
    assert rows[3]["source_article"]["_id"] == "judgments/ecli_x"


def test_search_relationships_filters(graph: GraphStore) -> None:
    def keys(**kw: Any) -> tuple[list[str], int]:
        rows, total = search_relationships(graph, **kw)
        return [r["edge"]["_key"] for r in rows], total

    assert keys(semantic_types={"definition"}) == (["r3", "r7"], 2)
    assert keys(exclude_types={"definition"}) == (["r4", "r6"], 3)
    assert keys(semantic_types={"x", "y"}, exclude_types={"y"}) == (["r4"], 2)
    assert keys(bwb_id="A") == (["r3", "r6"], 2)
    assert keys(bwb_id="B") == (["r4"], 2)
    assert keys(bwb_id="Z") == ([], 0)


def test_search_relationships_pages_before_dropping_missing_ends(
    graph: GraphStore,
) -> None:
    def keys(**kw: Any) -> tuple[list[str], int]:
        rows, total = search_relationships(graph, **kw)
        return [r["edge"]["_key"] for r in rows], total

    assert keys(limit=2) == (["r3", "r4"], 5)
    assert keys(limit=2, offset=2) == (["r6", "r7"], 5)
    # the last page holds r8 alone, whose target is gone: the page is empty
    assert keys(limit=2, offset=4) == ([], 5)
