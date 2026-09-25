"""Tests for the /api/search endpoint: tokens, ranking and the citation intent."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db.queries import search as search_module
from lawgraph.db.queries.search import (
    SCORE_CONTAINS,
    SCORE_IDENTIFIER,
    SCORE_PREFIX,
    SCORE_TITLE,
    SCORE_WORDS,
    rank_hits,
    score_hit,
    tokenize_search_query,
)

# ── Pure-function tests ───────────────────────────────────────────────────────


def test_tokenize_drops_short_tokens_and_lowercases():
    assert tokenize_search_query("Art. 1 Grondwet") == ["art.", "grondwet"]
    assert tokenize_search_query("BWBR0001854 a b cd") == ["bwbr0001854", "cd"]


def hit(**fields: Any) -> dict[str, Any]:
    return {"id": "x/k", "key": "k", "display_name": None, "extra": {}, **fields}


@pytest.mark.parametrize(
    ("query", "the_hit", "score"),
    [
        # An identifier of the hit, in any case; the key of the node.
        ("BWBR0001854", hit(extra={"bwb_id": "BWBR0001854"}), SCORE_IDENTIFIER),
        ("bwbr0001854", hit(extra={"bwb_id": "BWBR0001854"}), SCORE_IDENTIFIER),
        ("Sr", hit(extra={"short_title": "Sr"}), SCORE_IDENTIFIER),
        ("36327", hit(extra={"number": "36327"}), SCORE_IDENTIFIER),
        ("36327", hit(extra={"dossier_number": "36327"}), SCORE_IDENTIFIER),
        (
            "ECLI:NL:HR:2020:7",
            hit(key="ecli_nl_hr_2020_7", extra={"ecli": "ECLI:NL:HR:2020:7"}),
            SCORE_IDENTIFIER,
        ),
        # The whole name.
        ("Grondwet", hit(display_name="Grondwet"), SCORE_TITLE),
        ("  grondwet ", hit(display_name="Grondwet"), SCORE_TITLE),
        (
            "Wetboek van Strafrecht",
            hit(extra={"citation_title": "Wetboek van Strafrecht"}),
            SCORE_TITLE,
        ),
        # The name of a judgment is a name of it.
        ("urgenda", hit(extra={"names": ["Urgenda"]}), SCORE_TITLE),
        ("Lindenbaum", hit(extra={"names": ["Lindenbaum/Cohen"]}), SCORE_PREFIX),
        ("moord", hit(extra={"names": None}), SCORE_WORDS),
        # The start of a name; a part of one; words only.
        ("wetboek van", hit(display_name="Wetboek van Strafrecht"), SCORE_PREFIX),
        ("strafrecht", hit(display_name="Wetboek van Strafrecht"), SCORE_CONTAINS),
        (
            "wetboek strafrecht",
            hit(display_name="Wetboek van Strafrecht"),
            SCORE_CONTAINS,
        ),
        ("moord", hit(display_name="Wetboek van Strafrecht"), SCORE_WORDS),
        ("moord", hit(), SCORE_WORDS),
        ("", hit(display_name="Grondwet"), SCORE_WORDS),
    ],
)
def test_score_is_the_rank_tier_of_the_best_match(
    query: str, the_hit: dict[str, Any], score: float
) -> None:
    assert score_hit(query, the_hit) == score


def test_the_tiers_are_ordered() -> None:
    assert (
        SCORE_IDENTIFIER > SCORE_TITLE > SCORE_PREFIX > SCORE_CONTAINS > SCORE_WORDS > 0
    )


def test_hits_come_best_score_first_and_ties_keep_their_order() -> None:
    hits = [
        hit(id="a", display_name="Iets met grond"),
        hit(id="b", display_name="Grondwet"),
        hit(id="c", display_name="Grondwet voor het Koninkrijk"),
        hit(id="d", display_name="Nog iets met grond"),
    ]
    ranked = rank_hits("grondwet", hits)
    assert [h["id"] for h in ranked] == ["b", "c", "a", "d"]
    assert [h["score"] for h in ranked] == [
        SCORE_TITLE,
        SCORE_PREFIX,
        SCORE_WORDS,
        SCORE_WORDS,
    ]


def test_a_hit_that_has_a_score_keeps_it() -> None:
    ranked = rank_hits("x", [hit(id="a", score=SCORE_IDENTIFIER)])
    assert ranked[0]["score"] == SCORE_IDENTIFIER


# ── Route-level tests with a stubbed store ────────────────────────────────────


def _article(key: str, number: str, bwb: str, title: str, short: str | None):
    return {
        "id": f"articles/{key}",
        "key": key,
        "collection": "articles",
        "type": "article",
        "display_name": f"Artikel {number} {title}",
        "snippet": "Tekst ...",
        "extra": {
            "bwb_id": bwb,
            "article_number": number,
            "instrument_title": title,
            "citation_title": title,
            "short_title": short,
        },
    }


_GRONDWET_ART_1 = _article("bwbr0001840_1", "1", "BWBR0001840", "Grondwet", None)
_SR_ART_287 = _article(
    "bwbr0001854_287", "287", "BWBR0001854", "Wetboek van Strafrecht", "Sr"
)
_BW6_ART_162 = _article(
    "bwbr0005289_162", "162", "BWBR0005289", "Burgerlijk Wetboek Boek 6", "BW6"
)

_LAWS = [
    {"law_id": "BWBR0001840", "names": [None, "Grondwet", "Grondwet"]},
    {
        "law_id": "BWBR0001854",
        "names": ["Sr", "Wetboek van Strafrecht", "Wetboek van Strafrecht"],
    },
    {"law_id": "BWBR0005289", "names": ["BW6", None, "Burgerlijk Wetboek Boek 6"]},
]
_CODES = [["Sr", "BWBR0001854"], ["BW6", "BWBR0005289"]]


class _StubStore:
    """Replays canned AQL responses keyed by the query text fingerprint."""

    def __init__(self, articles: list[dict[str, Any]]):
        self._articles = articles
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def query(self, aql: str, bind_vars: dict[str, Any] | None = None):
        bind = bind_vars or {}
        self.queries.append((aql, bind))
        if "names: [i.props.short_title" in aql:
            return list(_LAWS)
        if "RETURN [i.props.short_title" in aql:
            return list(_CODES)
        if "@keys" in aql:
            return [a for a in self._articles if a["key"] in bind["keys"]]
        if "@numbers" in aql:
            return [
                a
                for a in self._articles
                if a["extra"]["article_number"] in bind["numbers"]
            ]
        if "search_articles" in aql:
            return list(self._articles)
        return []


@pytest.fixture(autouse=True)
def _cleanup():
    search_module._law_cache.clear()
    yield
    search_module._law_cache.clear()
    app.dependency_overrides.pop(get_store, None)


def _search(store: _StubStore, q: str) -> list[dict[str, Any]]:
    app.dependency_overrides[get_store] = lambda: store
    response = TestClient(app).get(
        "/api/search", params={"q": q, "types": "articles", "limit": 5}
    )
    assert response.status_code == 200
    return response.json()["results"]["articles"]


@pytest.mark.parametrize(
    ("query", "key"),
    [
        ("Art. 1 Grondwet", "bwbr0001840_1"),
        ("Sr 287", "bwbr0001854_287"),
        ("artikel 287 Sr", "bwbr0001854_287"),
        ("art. 6:162 BW", "bwbr0005289_162"),  # the book picks the regulation
    ],
)
def test_search_a_citation_finds_its_article_first_with_the_top_score(
    query: str, key: str
) -> None:
    store = _StubStore([_GRONDWET_ART_1, _SR_ART_287, _BW6_ART_162])
    articles = _search(store, query)
    assert articles[0]["key"] == key
    assert articles[0]["score"] == SCORE_IDENTIFIER
    assert articles[0]["extra"]["instrument_title"]


def test_search_an_article_without_law_looks_at_every_law_with_that_number() -> None:
    store = _StubStore([_GRONDWET_ART_1, _SR_ART_287])
    articles = _search(store, "artikel 1")
    assert [a["key"] for a in articles][0] == "bwbr0001840_1"
    assert any("@numbers" in aql for aql, _ in store.queries)


def test_search_falls_back_to_text_for_free_form_queries():
    store = _StubStore([_SR_ART_287])
    articles = _search(store, "moord")
    assert [a["key"] for a in articles] == ["bwbr0001854_287"]
    assert articles[0]["score"] == SCORE_WORDS


def test_the_laws_are_read_once_for_many_searches():
    store = _StubStore([_SR_ART_287])
    _search(store, "moord")
    _search(store, "doodslag")
    reads = [
        aql
        for aql, _ in store.queries
        if "names: [i.props.short_title" in aql or "RETURN [i.props.short_title" in aql
    ]
    assert len(reads) == 2  # the abbreviations and the names, once each


# ── /api/resolve ──────────────────────────────────────────────────────────────


def test_resolve_is_in_the_schema_with_its_answer_typed() -> None:
    spec = app.openapi()
    operation = spec["paths"]["/api/resolve"]["get"]
    assert "resolve" in operation["tags"] and operation["summary"]
    schemas = spec["components"]["schemas"]
    assert set(schemas["ResolveResponse"]["properties"]) == {
        "q",
        "kind",
        "confidence",
        "match",
        "alternatives",
        "qualifier",
    }
    assert set(schemas["ResolveMatch"]["properties"]) == {
        "id",
        "key",
        "collection",
        "kind",
        "display_name",
        "confidence",
    }
    q = next(p for p in operation["parameters"] if p["name"] == "q")
    assert q["required"] and q["schema"]["maxLength"] == 200


def test_resolve_answers_no_match_with_200_and_a_citation_with_its_target() -> None:
    store = _StubStore([_BW6_ART_162])
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app)

    found = client.get("/api/resolve", params={"q": "art. 6:162 BW"})
    assert found.status_code == 200
    body = found.json()
    assert (body["kind"], body["match"]["id"]) == (
        "article",
        "articles/bwbr0005289_162",
    )
    assert body["confidence"] == 0.95 and body["alternatives"] == []

    nothing = client.get("/api/resolve", params={"q": "zzzz onbekend"})
    assert nothing.status_code == 200
    assert nothing.json() == {
        "q": "zzzz onbekend",
        "kind": "none",
        "confidence": 0.0,
        "match": None,
        "alternatives": [],
        "qualifier": None,
    }
    assert client.get("/api/resolve", params={"q": ""}).status_code == 422
