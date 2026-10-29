"""The live search of the articles finds its candidates through the indexes of their words,
not by walking the key index and testing every row (prod, 29 Oct: "burgerlijk wetboek" in
732,000 articles, never within the 250 ms of a live search)."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries.search.text import live_query
from lawgraph.db.queries.search.types import SEARCHES
from tests.pg.plans import explain, plan_nodes


def _article(n: int) -> dict[str, Any]:
    """An article of a code whose name and division hold the words searched, as the
    books of the BW do: most articles hold both."""
    return {
        "key": f"BWBR0005291_{n}",
        "type": "article",
        "labels": [],
        "props": {
            "display_name": f"Artikel {n} Burgerlijk Wetboek Boek {n % 10}",
            "heading": f"kop {n}",
            "text": "de wet bepaalt" if n % 3 else "een regel",
            "breadcrumb": [{"title": "Burgerlijk wetboek" if n % 7 else "Titel"}],
        },
    }


@pytest.fixture()
def articles(store: GraphStore) -> GraphStore:
    store.bulk_insert_or_update_nodes("articles", [_article(n) for n in range(6000)])
    store.execute("ANALYZE articles")
    return store


def _walked(plan: dict[str, Any]) -> list[str]:
    """The scans of the articles in an index's order that a filter picks the rows from,
    without a condition of the index: a walk over the whole table."""
    return [
        f"{node['Node Type']} on {node.get('Index Name')}: {node.get('Filter')}"
        for node in plan_nodes(plan)
        if node["Node Type"] in ("Index Scan", "Index Only Scan")
        and node.get("Relation Name") == "articles"
        and node.get("Filter")
        and not node.get("Index Cond")
    ]


@pytest.mark.parametrize(
    "words", [["burgerlijk", "wetboek"], ["wet"], ["burgerlijk", "boek"]]
)
def test_the_live_candidates_of_the_articles_are_found_by_their_words(
    articles: GraphStore, words: list[str]
) -> None:
    statement, params = live_query(SEARCHES["articles"], "r.id", words, 6)
    plan = explain(articles, statement, params, disable=["seqscan"])
    assert _walked(plan) == []
