"""Tests for the /api/search endpoint: tokens, ranking and the citation intent."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.db.queries import search as search_module
from lawgraph.db.queries.resolve import NO_MATCH
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
        # The heading of an article and the aliases of a law are names of the hit.
        ("definities", hit(extra={"heading": "Definities"}), SCORE_TITLE),
        ("Boek 6 BW", hit(extra={"aliases": ["BW", "Boek 6 BW"]}), SCORE_TITLE),
        ("bw", hit(extra={"aliases": ["BW", "Boek 6 BW"]}), SCORE_TITLE),
        # The title of a division places an article without naming it.
        (
            "verhoging van strafbaarheid",
            hit(
                extra={
                    "division_titles": ["Uitsluiting en verhoging van strafbaarheid"]
                }
            ),
            SCORE_CONTAINS,
        ),
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


# ── The laws behind the citation parser ───────────────────────────────────────


def test_the_laws_are_read_once_for_many_searches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[str] = []

    def codes(store: Any) -> dict[str, str]:
        reads.append("codes")
        return {"Sr": "BWBR0001854"}

    def names(store: Any) -> dict[str, list[str]]:
        reads.append("names")
        return {"wetboek van strafrecht": ["BWBR0001854"]}

    monkeypatch.setattr(search_module, "load_code_aliases", codes)
    monkeypatch.setattr(search_module, "_load_law_names", names)

    first = search_module.load_notation_parser(None)
    again = search_module.load_notation_parser(None)

    assert again is first
    assert reads == ["codes", "names"]  # the abbreviations and the names, once each
    notation = first.parse("artikel 287 Sr")
    assert notation is not None and notation.kind == "article"
    assert [(a.law_id, a.number) for a in notation.articles] == [("BWBR0001854", "287")]


# ── Route-level tests with the search stubbed ─────────────────────────────────


_SR_ART_287 = {
    "id": "articles/bwbr0001854_287",
    "key": "bwbr0001854_287",
    "collection": "articles",
    "type": "article",
    "display_name": "Artikel 287 Wetboek van Strafrecht",
    "snippet": "Tekst ...",
    "extra": {"bwb_id": "BWBR0001854", "article_number": "287"},
    "score": SCORE_IDENTIFIER,
}


@pytest.fixture(autouse=True)
def _cleanup():
    search_module._law_cache.clear()
    yield
    search_module._law_cache.clear()


def test_the_search_route_passes_its_parameters_and_keeps_the_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, Any] = {}

    def search_all(store: Any, **kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        asked.update(kwargs)
        weaker = {**_SR_ART_287, "id": "articles/x", "key": "x", "score": SCORE_WORDS}
        return {"articles": [_SR_ART_287, weaker]}

    monkeypatch.setattr("lawgraph.api.routes.search.search_all", search_all)

    response = TestClient(app).get(
        "/api/search",
        params={"q": "Sr 287", "types": "articles", "kind": "Motie, Brief", "limit": 5},
    )

    assert response.status_code == 200
    assert asked == {
        "q": "Sr 287",
        "types": ["articles"],
        "kinds": ["Motie", "Brief"],
        "limit": 5,
    }
    articles = response.json()["results"]["articles"]
    assert [(a["key"], a["score"]) for a in articles] == [
        ("bwbr0001854_287", SCORE_IDENTIFIER),
        ("x", SCORE_WORDS),
    ]
    assert articles[0]["extra"]["article_number"] == "287"


def test_an_unknown_type_is_refused_before_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.search.search_all",
        lambda store, **kwargs: pytest.fail("searched"),
    )
    response = TestClient(app).get("/api/search", params={"q": "x", "types": "nope"})
    assert response.status_code == 400


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


def test_resolve_answers_no_match_with_200_and_a_citation_with_its_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    match = {
        "id": "articles/bwbr0005289_162",
        "key": "bwbr0005289_162",
        "collection": "articles",
        "kind": "article",
        "display_name": "Artikel 162",
        "confidence": 0.95,
    }
    answers = {
        "art. 6:162 BW": {
            "kind": "article",
            "confidence": 0.95,
            "match": match,
            "alternatives": [],
            "qualifier": None,
        },
        "zzzz onbekend": dict(NO_MATCH),
    }
    monkeypatch.setattr(
        "lawgraph.api.routes.resolve.resolve_query", lambda store, q: answers[q]
    )
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
