from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.queries import JudgmentArticleRelation, JudgmentDetailData

client = TestClient(app)

_JUDGMENT_DOC = {
    "_id": "judgments/NL:HR:2020:123",
    "_key": "NL:HR:2020:123",
    "props": {"display_name": "HR 2020", "ecli": "NL:HR:2020:123"},
    "labels": ["Judgment"],
}

_ARTICLE_DOC = {
    "_id": "instrument_articles/BWBR0001854-287",
    "_key": "BWBR0001854-287",
    "props": {
        "display_name": "Artikel 287",
        "bwb_id": "BWBR0001854",
        "article_number": "287",
    },
    "labels": ["Article"],
}

_INSTRUMENT_DOC = {
    "_id": "instruments/BWBR0001854",
    "_key": "BWBR0001854",
    "props": {"display_name": "Burgerlijk Wetboek Boek 1"},
    "labels": ["Instrument"],
}


def _build_payload() -> JudgmentDetailData:
    relation = JudgmentArticleRelation(article=_ARTICLE_DOC, instrument=_INSTRUMENT_DOC)
    return JudgmentDetailData(
        judgment=_JUDGMENT_DOC,
        articles=[relation],
        metadata={"article_count": 1},
    )


def test_get_judgment_detail_returns_linked_articles(monkeypatch):
    """Verifiëren dat het judgment endpoint metadata en artikelrelaties levert."""
    monkeypatch.setattr(
        "lawgraph.api.routes.judgments.get_judgment_with_relations",
        lambda store, ecli: _build_payload(),
    )

    response = client.get("/api/judgments/NL:HR:2020:123")
    assert response.status_code == 200
    payload = response.json()

    judgment = payload["judgment"]
    assert judgment["display_name"] == "HR 2020"
    assert judgment["ecli"] == "NL:HR:2020:123"

    articles = payload["articles"]
    assert isinstance(articles, list) and len(articles) == 1
    article = articles[0]
    assert article["id"].startswith("instrument_articles")
    assert article["display_name"] == "Artikel 287"
    assert article["instrument"] is not None
