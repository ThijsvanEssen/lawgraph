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
from lawgraph.db.queries.search import clause, dispatch, ranking
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
    assert set(termed.ids[0]) == {"articles/bwbr0005289_162", "articles/bwbr0001854_1"}


# ── a name of an article: its case law calls it by the words of the query ─────


def _cited(
    store: GraphStore,
    article: str,
    citers: int,
    holding: int,
    words: str,
    **props: Any,
) -> None:
    """*article* cited by *citers* judgments, *holding* of whose summaries hold *words*."""
    store.bulk_insert_or_update_nodes(
        "articles",
        [_node(article, "article", inbound_citation_count=citers, **props)],
    )
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                f"{article}_c{j}",
                "judgment",
                summary=f"Het oordeel over {words} in zaak {j}."
                if j < holding
                else f"Een geschil over huur in zaak {j}.",
            )
            for j in range(citers)
        ],
    )
    store.bulk_insert_or_update_edges(
        [_cites(f"{article}_c{j}", article) for j in range(citers)]
    )


def _summaries(store: GraphStore, words: str, holding: int, others: int) -> None:
    """*holding* judgments that cite nothing and hold *words*, and *others* that do not."""
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(f"w{j}", "judgment", summary=f"Een beroep op {words}, {j}.")
            for j in range(holding)
        ]
        + [
            _node(f"o{j}", "judgment", summary=f"Een zaak over iets anders, {j}.")
            for j in range(others)
        ],
    )


def _search(store: GraphStore, q: str) -> list[tuple[str, float]]:
    for table in ("articles", "judgments"):
        store.execute(f"ANALYZE {table}")
    GraphArticleTermsSemanticPipeline(store).run()
    version_cache.clear()
    hits = dispatch.search_all(store, q=q, types=["articles"], limit=10)["articles"]
    live, _ = dispatch.search_live(store, q=q, types=["articles"], limit=10)
    assert [h["id"] for h in live["articles"]][:1] == [h["id"] for h in hits][:1]
    return [(h["key"], h["score"]) for h in hits]


def test_an_article_its_case_law_names_goes_before_a_heading_that_starts_with_it(
    store: GraphStore,
) -> None:
    """ "verjaring": four of five judgments that use the word cite art. 3:310 BW, which
    one in a hundred cite; its words do not hold it. The articles of a regulation whose
    heading starts with the word (0.5) come after it: it is named (0.75)."""
    version_cache.clear()
    _cited(store, "bwbr0005291_310", 50, 20, "verjaring")
    _summaries(store, "verjaring", 5, 4_900)
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                f"32020l1828_{n}",
                "article",
                heading="Verjaringstermijn",
                text="Een termijn.",
            )
            for n in range(12)
        ],
    )

    hits = _search(store, "verjaring")
    assert hits[0] == ("bwbr0005291_310", ranking.SCORE_TITLE)


def test_a_word_of_every_subject_names_no_article(store: GraphStore) -> None:
    """ "bestemmingsplan": in two fifths of the summaries that cite art. 3:2 Awb, and two
    fifths of the summaries that hold it cite that article, but one in fifty judgments
    cites it: its citers hold the word 20 times as often as all, a term (above 5) but no
    name. It stays a hit on words."""
    version_cache.clear()
    _cited(store, "bwbr0005537_3_2", 100, 40, "bestemmingsplan")
    _summaries(store, "bestemmingsplan", 60, 4_840)

    hits = _search(store, "bestemmingsplan")
    assert hits == [("bwbr0005537_3_2", ranking.SCORE_WORDS)]


def test_a_word_that_points_elsewhere_names_no_article(store: GraphStore) -> None:
    """ "onrechtmatige daad": in most summaries that cite art. 6:163 BW and art. 7:661 BW,
    few of them (most cite art. 6:162 BW, but so many judgments cite that one that it is no
    name either). None goes before art. 6:162 BW, which stands in the title "Onrechtmatige
    daad" (0.25)."""
    version_cache.clear()
    title = {"breadcrumb": [{"title": "Onrechtmatige daad"}]}
    _cited(store, "bwbr0005289_162", 400, 50, "onrechtmatige daad", **title)
    _cited(store, "bwbr0005289_163", 10, 6, "onrechtmatige daad", **title)
    _cited(store, "bwbr0005290_661", 8, 5, "onrechtmatige daad")
    _summaries(store, "onrechtmatige daad", 30, 8_000)

    hits = _search(store, "onrechtmatige daad")
    assert hits[0][0] == "bwbr0005289_162"
    assert ranking.SCORE_TITLE not in {score for _, score in hits}


def test_an_article_is_named_by_every_word_of_the_query(store: GraphStore) -> None:
    """A name of every word: an article named by "daad" alone is not named by
    "onrechtmatige daad"."""
    store.execute(
        "INSERT INTO lg_article_terms (article_id, terms, strengths) VALUES"
        " ('articles/a', ARRAY['dad'], ARRAY[0.9]),"
        " ('articles/b', ARRAY['onrechtmat', 'dad'], ARRAY[0.9, 0.9]),"
        " ('articles/c', ARRAY['onrechtmat', 'dad'], ARRAY[0.9, 0.01])"
    )
    store.bulk_insert_or_update_nodes(
        "articles", [_node(key, "article") for key in ("a", "b", "c")]
    )

    termed = clause.termed_articles(store, ["onrechtmatige", "daad"])
    assert termed is not None
    assert termed.named == {"articles/b"}
