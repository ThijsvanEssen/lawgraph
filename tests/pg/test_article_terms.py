"""The terms of an article, what its case law calls it (``semantic graph-article-terms``)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.db import GraphStore, version_cache
from lawgraph.db.queries import search as search_queries
from lawgraph.pipelines.semantic import graph_article_terms as article_terms

NOODWEER = "articles/bwbr0001854_41"
DIEFSTAL = "articles/bwbr0001854_310"


def _node(key: str, kind: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": kind, "labels": [], "props": props}


def _cites(key: str, judgment: str, article: str, at: str) -> dict[str, Any]:
    return {
        "_key": key,
        "_from": judgment,
        "_to": article,
        "relation": "REFERS_TO",
        "source": "test",
        "status": "canoniek",
        "confidence": 1.0,
        "meta": {},
        "created_at": at,
    }


def _graph(store: GraphStore) -> None:
    """Art. 41 Sr, whose words hold no "noodweer", cited by 20 judgments: 11 of them about
    noodweer, 9 about mishandeling, all with "op"; and 200 judgments about other things
    that hold "mishandeling", "op" and the words of every summary (een beroep verworpen).
    Art. 310 Sr, cited by 3 about diefstal."""
    version_cache.clear()
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                "bwbr0001854_41",
                "article",
                bwb_id="BWBR0001854",
                article_number="41",
                display_name="Artikel 41 Wetboek van Strafrecht",
                text="Niet strafbaar is hij die een feit begaat, geboden door de"
                " noodzakelijke verdediging van eigen of eens anders lijf.",
                inbound_citation_count=20,
            ),
            _node(
                "bwbr0001854_310",
                "article",
                bwb_id="BWBR0001854",
                article_number="310",
                display_name="Artikel 310 Wetboek van Strafrecht",
                text="Hij die enig goed wegneemt, wordt als schuldig aan diefstal gestraft.",
                inbound_citation_count=3,
            ),
            _node(
                "bwbr0005290_1",
                "article",
                article_number="1",
                display_name="Artikel 1 Wet over het weer",
                text="Bij noodweer sluit de haven.",
                inbound_citation_count=0,
            ),
        ],
    )
    judgments = []
    for n in range(20):
        about = (
            "Beroep op noodweer verworpen." if n < 11 else "Een beroep op mishandeling."
        )
        judgments.append(_node(f"j41_{n}", "judgment", summary=about))
    for n in range(200):
        judgments.append(
            _node(
                f"other_{n}",
                "judgment",
                summary=f"Een beroep bij de rechter verworpen: mishandeling op straat {n}.",
            )
        )
    for n in range(3):
        judgments.append(
            _node(f"j310_{n}", "judgment", summary="Diefstal van een fiets op straat.")
        )
    store.bulk_insert_or_update_nodes("judgments", judgments)
    at = "2026-01-01T00:00:00+00:00"
    store.bulk_insert_or_update_edges(
        [_cites(f"c41_{n}", f"judgments/j41_{n}", NOODWEER, at) for n in range(20)]
        + [_cites(f"c310_{n}", f"judgments/j310_{n}", DIEFSTAL, at) for n in range(3)]
    )


def _terms(store: GraphStore) -> dict[str, list[str]]:
    return {
        row["article_id"]: list(row["terms"])
        for row in store.query("SELECT article_id, terms FROM lg_article_terms")
    }


def _version(store: GraphStore) -> int:
    return next(
        iter(
            store.query(
                "SELECT version FROM lg_data_version WHERE collection = 'articles'"
            )
        )
    )


def test_an_article_is_called_what_its_case_law_calls_it(store: GraphStore) -> None:
    _graph(store)
    before = _version(store)

    assert article_terms.run(store) == 2
    terms = _terms(store)
    # noodweer: in 11 of its 20 citers and in no other summary; "op" is in every summary
    # and "mishandeling" in more of all than of its citers: neither tells anything of it
    assert terms[NOODWEER] == ["noodwer"]
    assert "diefstal" in terms[DIEFSTAL] and "op" not in terms[DIEFSTAL]
    assert _version(store) == before + 1  # the search answers anew

    # a run again writes nothing and leaves the version
    assert article_terms.run(store) == 0
    assert _version(store) == before + 1


def test_the_search_finds_an_article_by_its_terms(store: GraphStore) -> None:
    _graph(store)
    article_terms.run(store)
    version_cache.clear()

    hits = search_queries.search_all(store, q="noodweer", types=["articles"])[
        "articles"
    ]
    # art. 41 Sr first, before the article whose text holds the word; a hit on words (0.1)
    assert [h["id"] for h in hits][:2] == [NOODWEER, "articles/bwbr0005290_1"]
    assert hits[0]["score"] == search_queries.SCORE_WORDS
    assert hits[0]["extra"]["terms"] == ["noodweer"]
    assert "terms" not in hits[1]["extra"]

    live, _ = search_queries.search_live(store, q="noodweer", types=["articles"])
    assert [h["id"] for h in live["articles"]][:2] == [
        NOODWEER,
        "articles/bwbr0005290_1",
    ]
    assert live["articles"][0]["extra"]["terms"] == ["noodweer"]

    # every word must still match: a term for one, the words for the other
    hits = search_queries.search_all(store, q="noodweer lijf", types=["articles"])
    assert [h["id"] for h in hits["articles"]] == [NOODWEER]


def test_a_run_since_keeps_the_terms_of_the_articles_cited_since(
    store: GraphStore,
) -> None:
    _graph(store)
    article_terms.run(store)
    # three judgments about diefstal cite art. 41 Sr later (an error of the source, say)
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(f"late_{n}", "judgment", summary="Noodweerexces bij diefstal.")
            for n in range(9)
        ],
    )
    later = "2026-06-01T00:00:00+00:00"
    store.bulk_insert_or_update_edges(
        [_cites(f"late_{n}", f"judgments/late_{n}", NOODWEER, later) for n in range(9)]
    )

    since = dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc)
    assert article_terms.run(store, since=since) == 1
    terms = _terms(store)
    # weighed against the counts of the last whole run: noodweerexces was in none then
    assert terms[NOODWEER][0] == "noodwer" and "noodweerexces" in terms[NOODWEER]
    # an article not cited since stays as it was
    assert "diefstal" in terms[DIEFSTAL]


def test_semantic_all_passes_its_since_on() -> None:
    """``daily.sh`` (``semantic all --since last``) keeps the terms of the articles cited
    since; ``weekly.sh`` (``semantic all``) counts the stems again."""
    from lawgraph.pipelines.command import accepts_since

    assert accepts_since(article_terms.main)
