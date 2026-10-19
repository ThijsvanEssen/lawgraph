"""The terms of practice (``tests/fixtures/practice_terms.json``): what a lawyer types for an
article whose words do not hold it ("wanprestatie": art. 6:74 BW, which speaks of a
"tekortkoming"). Each finds its article in the top 3, by what the case law calls it.

The graph stands for what lost that article on the full graph: it has no heading; the term
is in the summaries of a tenth of the judgments that cite it (a widely cited article is
cited on every subject), under the fifth that made a term, but half the judgments that use
the term cite it; and three regulations hold the term in their text. A regulation whose
heading is the term (a name, 0.75) still goes first: that is a tier of its own."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries.search import clause, dispatch
from lawgraph.pipelines.semantic.graph_article_terms import (
    GraphArticleTermsSemanticPipeline,
)

TERMS = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "practice_terms.json").read_text()
)
CITERS = 60  # the judgments that cite each article
USING = 6  # of them, those whose summary holds the term; as many others hold it too
OTHERS = 3  # the regulations that hold the term in their text


def _node(key: str, kind: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": kind, "labels": [], "props": props}


def _cites(judgment: str, article: str) -> dict[str, Any]:
    return {
        "key": f"{judgment}-{article}",
        "from_id": f"judgments/{judgment}",
        "to_id": f"articles/{article}",
        "relation": "REFERS_TO",
        "source": "test",
        "status": "canoniek",
        "confidence": 1.0,
        "meta": {},
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _target(entry: dict[str, Any]) -> str:
    first = entry["articles"][0]
    return make_node_key(first["law"], first["number"])


def _graph(store: GraphStore) -> None:
    version_cache.clear()
    articles, judgments, edges = [], [], []
    for n, entry in enumerate(TERMS):
        term = entry["term"]
        for article in entry["articles"]:
            articles.append(
                _node(
                    make_node_key(article["law"], article["number"]),
                    "article",
                    bwb_id=article["law"],
                    article_number=article["number"],
                    display_name=f"Artikel {article['number']} {article['law']}",
                    # the words of every summary, as any text of a law holds them
                    text="De bepaling geldt op het beroep en de eis bij de wet onder"
                    f" voorwaarden van artikel {article['number']}.",
                    inbound_citation_count=CITERS,
                )
            )
        for h in range(OTHERS):
            articles.append(
                _node(
                    f"bwbr9{n:03d}{h:03d}_1",
                    "article",
                    bwb_id=f"BWBR9{n:03d}{h:03d}",
                    article_number="1",
                    display_name=f"Artikel 1 Regeling {n} {h}",
                    text=f"Deze regeling gaat over {term}.",
                    inbound_citation_count=0,
                )
            )
        target = _target(entry)
        for j in range(CITERS):
            summary = (
                f"De rechter oordeelt over {term} in zaak {j}."
                if j < USING
                else f"Een geschil in zaak {n} {j}."
            )
            judgments.append(_node(f"c{n}_{j}", "judgment", summary=summary))
            edges.append(_cites(f"c{n}_{j}", target))
        judgments += [
            _node(f"u{n}_{j}", "judgment", summary=f"Een beroep op {term}, zaak {j}.")
            for j in range(USING)
        ]
    # the words every summary holds, in judgments that cite nothing
    judgments += [
        _node(
            f"b{j}",
            "judgment",
            summary=f"De rechtbank beslist op het beroep en de eis bij de wet onder {j}.",
        )
        for j in range(2_000)
    ]
    store.bulk_insert_or_update_nodes("articles", articles)
    store.bulk_insert_or_update_nodes("judgments", judgments)
    store.bulk_insert_or_update_edges(edges)
    for table in ("articles", "judgments"):
        store.execute(f"ANALYZE {table}")
    GraphArticleTermsSemanticPipeline(store).run()
    version_cache.clear()


def _rank(hits: list[dict[str, Any]], entry: dict[str, Any]) -> int | None:
    wanted = {
        f"articles/{make_node_key(a['law'], a['number'])}" for a in entry["articles"]
    }
    ranks = [n for n, hit in enumerate(hits, 1) if hit["id"] in wanted]
    return min(ranks, default=None)


def test_a_term_of_practice_finds_its_article_in_the_top_3(store: GraphStore) -> None:
    _graph(store)

    missed = {}
    for entry in TERMS:
        term = entry["term"]
        hits = dispatch.search_all(store, q=term, types=["articles"], limit=10)
        live, cut = dispatch.search_live(store, q=term, types=["articles"], limit=6)
        full_rank = _rank(hits["articles"], entry)
        # a live search cut off at its budget (a busy test server) has nothing to rank
        live_rank = 1 if cut else _rank(live["articles"], entry)
        if not (full_rank and full_rank <= 3 and live_rank and live_rank <= 3):
            missed[term] = (full_rank, live_rank)
    assert missed == {}


def test_the_termed_articles_of_a_common_word_are_the_most_cited(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past ``TERMED`` articles with a term, the most cited are taken, not the first by
    id: art. 6:162 BW comes after the articles of the Wetboek van Strafrecht."""
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node("bwbr0001854_1", "article", inbound_citation_count=2),
            _node("bwbr0001854_2", "article", inbound_citation_count=0),
            _node("bwbr0005289_162", "article", inbound_citation_count=900),
        ],
    )
    store.execute(
        "INSERT INTO lg_article_terms (article_id, terms)"
        " SELECT id, ARRAY['dad'] FROM articles"
    )
    monkeypatch.setattr(clause, "TERMED", 2)

    termed = clause.termed_articles(store, ["daad"])
    assert termed is not None
    assert set(termed[0]) == {"articles/bwbr0005289_162", "articles/bwbr0001854_1"}
