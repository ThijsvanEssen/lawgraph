"""Tests for the /api/search endpoint: tokens, ranking and the citation intent."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.db import version_cache
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
    version_cache.clear()
    yield
    version_cache.clear()


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


def test_search_resolves_q_in_the_same_request_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = {
        "kind": "instrument",
        "confidence": 0.9,
        "match": {
            "id": "instruments/32016r0679",
            "key": "32016r0679",
            "collection": "instruments",
            "kind": "instrument",
            "display_name": "AVG",
            "confidence": 0.9,
        },
        "alternatives": [],
        "alternatives_total": 0,
        "qualifier": None,
    }
    asked: list[str] = []

    def resolve_query(store: Any, q: str) -> dict[str, Any]:
        asked.append(q)
        return resolved

    monkeypatch.setattr(
        "lawgraph.api.routes.search.search_all", lambda store, **kwargs: {}
    )
    monkeypatch.setattr("lawgraph.api.routes.search.resolve_query", resolve_query)
    client = TestClient(app)

    body = client.get("/api/search", params={"q": "AVG", "resolve": "true"}).json()
    assert body["resolved"] == {"q": "AVG", **resolved}
    # without it nothing is resolved; a query too long for resolve is no citation
    assert client.get("/api/search", params={"q": "AVG"}).json()["resolved"] is None
    long = "woord " * 40
    body = client.get("/api/search", params={"q": long, "resolve": "true"}).json()
    assert body["resolved"] == {"q": long, **NO_MATCH, "qualifier": None}
    assert asked == ["AVG"]


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
        "alternatives_total",
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
            "alternatives_total": 0,
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
        "alternatives_total": 0,
        "qualifier": None,
    }
    assert client.get("/api/resolve", params={"q": ""}).status_code == 422


def test_a_resolve_answer_says_how_many_alternatives_it_found() -> None:
    """``alternatives_total`` in every answer; a choice has no ``match``."""
    from lawgraph.api.schemas.resolve import ResolveResponse

    choice = ResolveResponse(
        q="art. 3 BW",
        kind="article",
        confidence=0.5,
        match=None,
        alternatives=[],
        alternatives_total=9,
        qualifier=None,
    )
    assert choice.model_dump()["alternatives_total"] == 9
    assert (
        ResolveResponse(
            q="x", kind="none", confidence=0, match=None, alternatives=[]
        ).alternatives_total
        == 0
    )


def test_a_live_search_says_which_types_it_cut_off(monkeypatch) -> None:
    """``mode=live``: ``partial`` names the types cut off; the full search has none."""
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.routes import search as route

    monkeypatch.setattr(
        route,
        "search_live",
        lambda store, **k: ({"judgments": [], "articles": []}, {"judgments"}),
    )
    monkeypatch.setattr(route, "search_all", lambda store, **k: {"articles": []})
    client = TestClient(app)
    live = client.get(
        "/api/search",
        params={"q": "huur", "mode": "live", "types": ["judgments", "articles"]},
    )
    assert live.status_code == 200 and live.json()["partial"] == {"judgments": True}
    full = client.get("/api/search", params={"q": "huur", "types": ["articles"]})
    assert full.status_code == 200 and full.json()["partial"] == {}
    assert (
        client.get("/api/search", params={"q": "huur", "mode": "x"}).status_code == 422
    )
