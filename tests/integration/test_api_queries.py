"""The API queries the audit found unbounded, run for real on the chain's graph."""

from __future__ import annotations

import json
from typing import Any

from lawgraph.config.constants import COLLECTION_ARTICLES, RELATION_REFERS_TO
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.edges import make_edge_doc
from lawgraph.db.queries._helpers import _find_judgments_for_article, _load_judgment
from lawgraph.db.queries.instruments import get_instrument_judgments
from lawgraph.db.queries.relationships import search_relationships
from tests.integration.seed import seed

GRONDWET = "BWBR0001840"


def _size(value: Any) -> int:
    return len(json.dumps(value, default=str))


def test_the_judgment_lists_carry_what_is_shown_not_whole_judgments(
    database: str, cli: Any
) -> None:
    store = GraphStore()
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
    assert set(items[0]["judgment"]["props"]) == {
        "ecli",
        "display_name",
        "court_code",
        "tier",
        "court_kind",
        "date_eff",
        "advocate_general",  # of a conclusion (BE-47/BE-48)
        "advocate_general_role",
    }
    assert items[0]["cited_articles"][0]["article_number"] == "1"


def test_classified_relationships_are_counted_by_id_and_paged(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    seed(store, documents=5, judgments=2, regulations=4)
    cli("normalize", "all")
    cli("semantic", "all")

    rows, total = search_relationships(store, limit=5)
    assert len(rows) <= 5 and total >= len(rows)
    for row in rows:
        assert row["edge"]["semantic_type"] and row["source_article"] and row["target"]
    of_law, law_total = search_relationships(store, bwb_id=GRONDWET, limit=5)
    assert law_total <= total and len(of_law) <= 5


def test_relationships_are_searched_by_several_types_or_without_some(
    database: str,
) -> None:
    store = GraphStore()
    types = ["cross_reference", "definitional_reference", "scope_limitation"]
    articles = [
        {"_key": f"a{n}", "type": "article", "labels": [], "props": {"bwb_id": law}}
        for n, law in enumerate(["BWBR1", "BWBR1", "BWBR1", "BWBR2"])
    ]
    store.bulk_insert_or_update_nodes(COLLECTION_ARTICLES, articles)
    edges = [
        {
            **make_edge_doc(
                f"{COLLECTION_ARTICLES}/a{n}",
                f"{COLLECTION_ARTICLES}/a3",
                RELATION_REFERS_TO,
                source="test",
            ),
            "semantic_type": semantic_type,
        }
        for n, semantic_type in enumerate(types)
    ]
    store.bulk_insert_or_update_edges(edges)

    def found(**kwargs: Any) -> tuple[list[str], int]:
        rows, total = search_relationships(store, **kwargs)
        return sorted(row["edge"]["semantic_type"] for row in rows), total

    assert found() == (types, 3)
    assert found(semantic_types=["scope_limitation", "cross_reference"]) == (
        ["cross_reference", "scope_limitation"],
        2,
    )
    assert found(exclude_types=["cross_reference"]) == (types[1:], 2)
    assert found(
        semantic_types=["cross_reference", "scope_limitation"],
        exclude_types=["cross_reference"],
    ) == (["scope_limitation"], 1)
    assert found(exclude_types=["cross_reference"], bwb_id="BWBR1", limit=1)[1] == 2


def test_a_judgment_is_found_by_ecli_echr_id_or_application_number(
    database: str, cli: Any
) -> None:
    """An ECLI in any case, an ECHR id or an application number finds its judgment; an ECLI
    nobody loaded (a citation that is a stub elsewhere, a typo in a URL) finds none."""
    store = GraphStore()
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

    assert _load_judgment(store, "ecli:nl:hr:2020:7")["props"]["ecli"].endswith(":7")
    assert _load_judgment(store, "001-45678")["_key"] == old.key
    assert _load_judgment(store, "12345/67")["_key"] == old.key
    assert _load_judgment(store, "ECLI:NL:HR:1999:1") is None
