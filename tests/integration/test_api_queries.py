"""The API queries the audit found unbounded, run for real on the chain's graph."""

from __future__ import annotations

import json
from typing import Any

from lawgraph.api.queries._helpers import _find_judgments_for_article, _load_judgment
from lawgraph.api.queries.graph import get_global_graph, get_judgment_graph
from lawgraph.api.queries.instruments import get_instrument_judgments
from lawgraph.api.queries.relationships import search_relationships
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.db import ArangoStore
from tests.integration.seed import seed

GRONDWET = "BWBR0001840"


def _size(value: Any) -> int:
    return len(json.dumps(value, default=str))


def test_the_judgment_lists_carry_what_is_shown_not_whole_judgments(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    seed(store, documents=20, judgments=60, regulations=4)  # each cites art. 1 Grondwet
    cli("normalize", "all")
    cli("semantic", "all")

    article_id = f"articles/{make_node_key(GRONDWET, '1')}"
    citing = _find_judgments_for_article(store, article_id)
    assert len(citing) == 60
    assert set(citing[0]) == {"_id", "_key", "props"}
    assert set(citing[0]["props"]) == {"ecli", "display_name"}
    assert _size(citing) < 60 * 400  # a whole judgment is thousands of bytes each

    items, total = get_instrument_judgments(store, GRONDWET, limit=10)
    assert total == 60 and len(items) == 10
    assert set(items[0]["judgment"]["props"]) == {"ecli", "display_name"}
    assert items[0]["cited_articles"][0]["article_number"] == "1"

    graph = get_judgment_graph(store, max_judgments=25)
    assert len(graph.judgments) == 25
    assert (
        graph.edges and graph.instruments
    )  # judgments -> the laws they cite, weighted
    assert all(edge.weight >= 1 for edge in graph.edges)

    everything = get_global_graph(store, max_judgments=25)
    for judgment in everything.judgments:
        assert not {"text", "paragraphs", "summary"} & set(judgment["props"])
    for article in everything.articles:
        assert "text" not in article["props"]


def test_classified_relationships_are_counted_by_id_and_paged(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    seed(store, documents=5, judgments=2, regulations=4)
    cli("normalize", "all")
    cli("semantic", "all")

    rows, total = search_relationships(store, limit=5)
    assert len(rows) <= 5 and total >= len(rows)
    for row in rows:
        assert row["edge"]["semantic_type"] and row["source_article"] and row["target"]
    of_law, law_total = search_relationships(store, bwb_id=GRONDWET, limit=5)
    assert law_total <= total and len(of_law) <= 5


def test_a_judgment_is_found_by_key_or_index_never_by_reading_them_all(
    database: str, cli: Any
) -> None:
    """An ECLI nobody loaded (a citation that is a stub elsewhere, a typo in a URL) read
    every judgment twice: once comparing ``LOWER(props.ecli)``, once for the ECHR ids."""
    store = ArangoStore()
    seed(store, documents=0, judgments=30, regulations=0)
    cli("normalize", "rechtspraak")
    old = Node(  # an ECHR decision from before the court gave out ECLIs
        collection="judgments",
        type=NodeType.JUDGMENT,
        key=make_node_key("echr", "001-45678"),
        labels=["ECHR"],
        props={"source": "echr", "external_id": "001-45678", "appno": "12345/67"},
    )
    store.bulk_insert_or_update_nodes("judgments", [old.to_document()])

    queries: list[tuple[str, dict[str, Any]]] = []
    run = store.query

    def recording(aql: str, bind_vars: dict[str, Any] | None = None, **kw: Any) -> Any:
        queries.append((aql, bind_vars or {}))
        return run(aql, bind_vars, **kw)

    store.query = recording  # type: ignore[method-assign]

    assert _load_judgment(store, "ecli:nl:hr:2020:7")["props"]["ecli"].endswith(":7")
    assert _load_judgment(store, "001-45678")["_key"] == old.key
    assert _load_judgment(store, "12345/67")["_key"] == old.key
    assert _load_judgment(store, "ECLI:NL:HR:1999:1") is None

    for aql, bind_vars in queries:
        plan = store.db.aql.explain(aql, bind_vars=bind_vars)
        kinds = {node["type"] for node in plan["nodes"]}
        assert "EnumerateCollectionNode" not in kinds, aql
