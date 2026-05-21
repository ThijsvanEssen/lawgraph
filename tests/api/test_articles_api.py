from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.queries import ArticleCitationEntry, ArticleDetailData

client = TestClient(app)

_ARTICLE_DOC = {
    "_id": "instrument_articles/BWBR0001854-287",
    "_key": "BWBR0001854-287",
    "props": {
        "bwb_id": "BWBR0001854",
        "article_number": "287",
        "display_name": "Artikel 287",
        "text": "Het artikel heeft wat tekst",
    },
    "labels": ["Article"],
}

_INSTRUMENT_DOC = {
    "_id": "instruments/BWBR0001854",
    "_key": "BWBR0001854",
    "props": {
        "display_name": "Burgerlijk Wetboek Boek 1",
    },
    "labels": ["Instrument"],
}

_JUDGMENT_DOC = {
    "_id": "judgments/NL:HR:2020:123",
    "_key": "NL:HR:2020:123",
    "props": {"display_name": "HR 2020", "ecli": "NL:HR:2020:123"},
    "labels": ["Judgment"],
}


_PAYLOAD = ArticleDetailData(
    article=_ARTICLE_DOC,
    instrument=_INSTRUMENT_DOC,
    judgments=[_JUDGMENT_DOC],
    metadata={"judgment_count": 1},
)


def test_get_article_detail_returns_expected_fields(monkeypatch):
    """Verifiëren dat het artikel endpoint de summarisatievelden teruggeeft."""
    monkeypatch.setattr(
        "lawgraph.api.routes.articles.get_article_with_relations",
        lambda store, bwb_id, article_number: _PAYLOAD,
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.articles.get_article_citations",
        lambda store, article_doc: [],
    )
    response = client.get("/api/articles/BWBR0001854/287")
    assert response.status_code == 200
    payload = response.json()

    article = payload["article"]
    assert article["display_name"] == "Artikel 287"
    assert article["bwb_id"] == "BWBR0001854"
    assert article["article_number"] == "287"
    assert article["text"] is not None and article["text"] != ""
    assert isinstance(payload["judgments"], list)
    assert payload["citations"] == []


def test_get_article_detail_returns_404_for_unknown_key(monkeypatch):
    """GET /api/articles/{bwb_id}/{article_number} returns 404 when the article is not found."""
    monkeypatch.setattr(
        "lawgraph.api.routes.articles.get_article_with_relations",
        lambda store, bwb_id, article_number: (_ for _ in ()).throw(
            ValueError("article not found")
        ),
    )
    response = client.get("/api/articles/instrument_articles/nonexistent-key-xyz")
    assert response.status_code == 404


def test_get_article_detail_exposes_citations(monkeypatch):
    """Controleren dat gevonden referenties via REFERS_TO_ARTICLE terugkomen."""
    monkeypatch.setattr(
        "lawgraph.api.routes.articles.get_article_with_relations",
        lambda store, bwb_id, article_number: _PAYLOAD,
    )
    citation_target = {
        "_id": "instrument_articles/BWBR0001854-24c",
        "_key": "BWBR0001854-24c",
        "props": {
            "bwb_id": "BWBR0001854",
            "article_number": "24c",
            "display_name": "Artikel 24c",
        },
        "labels": ["Article"],
    }
    entry = ArticleCitationEntry(
        target=citation_target,
        start=10,
        end=18,
        text="Artikel 24c",
        confidence=0.92,
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.articles.get_article_citations",
        lambda store, article_doc: [entry],
    )
    response = client.get("/api/articles/BWBR0001854/287")
    assert response.status_code == 200
    payload = response.json()
    assert payload["citations"]
    citation = payload["citations"][0]
    assert citation["start"] == 10
    assert citation["end"] == 18
    assert citation["text"] == "Artikel 24c"
    target = citation["target"]
    assert target["bwb_id"] == "BWBR0001854"
    assert target["article_number"] == "24c"
    assert target["display_name"] == "Artikel 24c"
