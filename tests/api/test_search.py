"""Tests for the /api/search endpoint and its parser."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import parse_search_query, tokenize_search_query

# ── Pure-function tests for the parser ────────────────────────────────────────


_ALIAS_MAP = {
    "sr": "BWBR0001854",
    "sv": "BWBR0001903",
    "wetboek van strafrecht": "BWBR0001854",
    "wetboek van strafvordering": "BWBR0001903",
    "grondwet": "BWBR0001840",
    "evrm": "21970A0718(02)",
}


@pytest.mark.parametrize(
    "query,expected_bwb,expected_article",
    [
        ("Art. 1 Grondwet", "BWBR0001840", "1"),
        ("art 287 Sr", "BWBR0001854", "287"),
        ("Sr 287", "BWBR0001854", "287"),
        ("artikel 5 Sv", "BWBR0001903", "5"),
        ("Wetboek van Strafrecht art 287", "BWBR0001854", "287"),
        ("Grondwet 1", "BWBR0001840", "1"),
    ],
)
def test_parse_search_query_recognises_article_intent(
    query, expected_bwb, expected_article
):
    parsed = parse_search_query(query, _ALIAS_MAP)
    assert parsed["kind"] == "article"
    assert parsed["bwb_id"] == expected_bwb
    assert parsed["article_number"] == expected_article


def test_parse_search_query_handles_article_without_law():
    parsed = parse_search_query("art 1", _ALIAS_MAP)
    assert parsed == {"kind": "article", "bwb_id": None, "article_number": "1"}


def test_parse_search_query_recognises_ecli():
    parsed = parse_search_query("ECLI:NL:HR:2023:123", _ALIAS_MAP)
    assert parsed["kind"] == "ecli"
    assert parsed["ecli"] == "ECLI:NL:HR:2023:123"


def test_parse_search_query_falls_back_to_text_when_law_unknown():
    # "Wetboek 287" — "Wetboek" is too generic to resolve in alias_map
    assert parse_search_query("Wetboek 287", _ALIAS_MAP) == {"kind": "text"}


def test_parse_search_query_empty_returns_text():
    assert parse_search_query("", _ALIAS_MAP) == {"kind": "text"}
    assert parse_search_query("   ", _ALIAS_MAP) == {"kind": "text"}


def test_tokenize_drops_short_tokens_and_lowercases():
    assert tokenize_search_query("Art. 1 Grondwet") == ["art.", "grondwet"]
    assert tokenize_search_query("BWBR0001854 a b cd") == ["bwbr0001854", "cd"]


# ── Route-level tests with a stubbed store ────────────────────────────────────


_GRONDWET_INSTRUMENT = {
    "_id": "instruments/bwbr0001840",
    "_key": "bwbr0001840",
    "type": "instrument",
    "props": {
        "bwb_id": "BWBR0001840",
        "title": "Grondwet",
        "citation_title": "Grondwet",
        "short_title": None,
    },
}

_SR_INSTRUMENT = {
    "_id": "instruments/bwbr0001854",
    "_key": "bwbr0001854",
    "type": "instrument",
    "props": {
        "bwb_id": "BWBR0001854",
        "title": "Wetboek van Strafrecht",
        "citation_title": "Wetboek van Strafrecht",
        "short_title": "Sr",
    },
}

_GRONDWET_ART_1 = {
    "id": "instrument_articles/bwbr0001840_1",
    "key": "bwbr0001840_1",
    "collection": "instrument_articles",
    "type": "article",
    "display_name": "Artikel 1 Grondwet",
    "snippet": "Allen die zich in Nederland bevinden ...",
    "extra": {
        "bwb_id": "BWBR0001840",
        "article_number": "1",
        "citation_title": "Grondwet",
        "short_title": None,
    },
}

_SR_ART_287 = {
    "id": "instrument_articles/bwbr0001854_287",
    "key": "bwbr0001854_287",
    "collection": "instrument_articles",
    "type": "article",
    "display_name": "Artikel 287 Sr.",
    "snippet": "Hij die opzettelijk ...",
    "extra": {
        "bwb_id": "BWBR0001854",
        "article_number": "287",
        "citation_title": "Wetboek van Strafrecht",
        "short_title": "Sr",
    },
}


class _StubStore:
    """Replays canned AQL responses keyed by the query text fingerprint."""

    def __init__(
        self, alias_rows: list[dict[str, Any]], hits: dict[str, list[dict[str, Any]]]
    ):
        self._alias_rows = alias_rows
        self._hits = hits

    def query(self, aql: str, bind_vars: dict[str, Any] | None = None):
        # Alias-map loader: returns bwb_id as a plain field (not as an object key).
        if "FOR i IN instruments" in aql and "bwb_id: i.props.bwb_id" in aql:
            return list(self._alias_rows)
        # Article precise lookup: keyed on @article_number.
        if "@article_number" in aql:
            article_number = (bind_vars or {}).get("article_number")
            bwb_id = (bind_vars or {}).get("bwb_id")
            return [
                row
                for row in self._hits.get("articles_precise", [])
                if row["extra"]["article_number"] == article_number
                and (bwb_id is None or row["extra"]["bwb_id"] == bwb_id)
            ]
        if "search_articles" in aql or "FOR doc IN instrument_articles" in aql:
            return list(self._hits.get("articles_text", []))
        if "search_judgments" in aql or "FOR doc IN judgments" in aql:
            return list(self._hits.get("judgments", []))
        return []


def _override_store(store):
    app.dependency_overrides[get_store] = lambda: store


@pytest.fixture(autouse=True)
def _cleanup_store_override():
    yield
    app.dependency_overrides.pop(get_store, None)


def test_search_article_intent_returns_grondwet_art_1_first():
    """`Art. 1 Grondwet` must surface BWBR0001840_1 in the top 3."""
    store = _StubStore(
        alias_rows=[
            {
                "bwb_id": "BWBR0001840",
                "short": None,
                "citation": "Grondwet",
                "title": "Grondwet",
            },
            {
                "bwb_id": "BWBR0001854",
                "short": "Sr",
                "citation": "Wetboek van Strafrecht",
                "title": "Wetboek van Strafrecht",
            },
        ],
        hits={"articles_precise": [_GRONDWET_ART_1]},
    )
    _override_store(store)

    response = TestClient(app).get(
        "/api/search", params={"q": "Art. 1 Grondwet", "types": "articles", "limit": 5}
    )
    assert response.status_code == 200
    data = response.json()
    articles = data["results"]["articles"]
    assert articles, "expected at least one article hit"
    assert articles[0]["id"] == "instrument_articles/bwbr0001840_1"
    assert articles[0]["extra"]["bwb_id"] == "BWBR0001840"
    assert articles[0]["extra"]["citation_title"] == "Grondwet"


def test_search_sr_287_returns_strafrecht_article_in_top_3():
    """`Sr 287` must surface BWBR0001854_287 in the top 3."""
    store = _StubStore(
        alias_rows=[
            {
                "bwb_id": "BWBR0001854",
                "short": "Sr",
                "citation": "Wetboek van Strafrecht",
                "title": "Wetboek van Strafrecht",
            },
        ],
        hits={"articles_precise": [_SR_ART_287]},
    )
    _override_store(store)

    response = TestClient(app).get(
        "/api/search", params={"q": "Sr 287", "types": "articles", "limit": 5}
    )
    assert response.status_code == 200
    articles = response.json()["results"]["articles"]
    assert articles[0]["id"] == "instrument_articles/bwbr0001854_287"
    assert articles[0]["extra"]["short_title"] == "Sr"
    assert articles[0]["extra"]["citation_title"] == "Wetboek van Strafrecht"


def test_search_results_carry_citation_title_and_short_title():
    """Article hits must always include extra.citation_title / short_title."""
    store = _StubStore(
        alias_rows=[
            {
                "bwb_id": "BWBR0001854",
                "short": "Sr",
                "citation": "Wetboek van Strafrecht",
                "title": "Wetboek van Strafrecht",
            },
        ],
        hits={"articles_precise": [_SR_ART_287]},
    )
    _override_store(store)

    response = TestClient(app).get(
        "/api/search", params={"q": "Sr 287", "types": "articles", "limit": 5}
    )
    article = response.json()["results"]["articles"][0]
    assert "citation_title" in article["extra"]
    assert "short_title" in article["extra"]


def test_search_falls_back_to_text_for_free_form_queries():
    """Plain-text queries (no recognised pattern) hit the text-search path."""
    store = _StubStore(
        alias_rows=[
            {
                "bwb_id": "BWBR0001854",
                "short": "Sr",
                "citation": "Wetboek van Strafrecht",
                "title": "Wetboek van Strafrecht",
            },
        ],
        hits={"articles_text": [_SR_ART_287]},
    )
    _override_store(store)

    response = TestClient(app).get(
        "/api/search", params={"q": "moord", "types": "articles", "limit": 5}
    )
    articles = response.json()["results"]["articles"]
    assert len(articles) == 1
    assert articles[0]["id"] == "instrument_articles/bwbr0001854_287"
