from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.queries.articles import ArticleCitationEntry, ArticleDetailData
from lawgraph.api.schemas.articles import ArticleExplanationDTO

client = TestClient(app)

_ARTICLE_DOC = {
    "_id": "articles/BWBR0001854-287",
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
    monkeypatch.setattr(
        "lawgraph.api.routes.articles.get_article_with_relations",
        lambda store, bwb_id, article_number: _PAYLOAD,
    )
    citation_target = {
        "_id": "articles/BWBR0001854-24c",
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


_EXPLANATION_ROW = {
    "document_id": "documents/mvt_1",
    "key": "mvt_1",
    "kind": "Memorie van toelichting",
    "title": "MvT",
    "date": "2025-01-10T00:00:00",
    "source": "tk",
    "labels": ["TK"],
    "dossier_number": "36000",
    "target_id": "article_versions/av_5_new",
    "confidence": 1.0,
    "section_anchor": None,
}


def _explanation(**changes):
    return ArticleExplanationDTO.from_row({**_EXPLANATION_ROW, **changes})


def test_an_explanation_on_a_version_names_the_version_and_is_dossier_wide() -> None:
    item = _explanation()

    assert item.target == "article_version"
    assert item.article_version_key == "av_5_new"
    assert item.target_id == "article_versions/av_5_new"
    assert item.scope == "dossier" and item.section_anchor is None
    assert item.confidence == 1.0
    assert item.document.model_dump() == {
        "chamber": "TK",
        "source": "tk",
        "is_explanatory": True,
        "id": "documents/mvt_1",
        "key": "mvt_1",
        "kind": "Memorie van toelichting",
        "title": "MvT",
        "date": "2025-01-10",
        "dossier_number": "36000",
    }


def test_an_explanation_on_an_article_or_an_instrument_has_no_version_key() -> None:
    article = _explanation(target_id="articles/bwbr0002_5")
    instrument = _explanation(target_id="instruments/bwbr0002")

    assert (article.target, article.article_version_key) == ("article", None)
    assert (instrument.target, instrument.article_version_key) == ("instrument", None)


def test_an_explanation_with_a_section_anchor_is_scoped_to_the_article() -> None:
    item = _explanation(section_anchor="artikel-5")

    assert item.scope == "article" and item.section_anchor == "artikel-5"


def test_an_explanation_of_a_document_without_dates_or_dossier_is_still_one() -> None:
    item = _explanation(
        date=None, dossier_number=None, labels=["EersteKamer", "EK"], kind=None
    )

    assert item.document.date is None and item.document.dossier_number is None
    assert item.document.chamber == "EK" and item.document.is_explanatory is False


def test_explained_by_answers_a_page_with_its_total(monkeypatch) -> None:
    asked: list[tuple] = []

    def fake(store, bwb_id, article_number, *, limit, offset):
        asked.append((bwb_id, article_number, limit, offset))
        return {"total": 41, "items": [_EXPLANATION_ROW]}

    monkeypatch.setattr("lawgraph.api.routes.articles.get_article_explanations", fake)

    response = client.get(
        "/api/articles/BWBR0002/5/explained-by", params={"limit": 5, "offset": 10}
    )

    assert response.status_code == 200
    body = response.json()
    assert asked == [("BWBR0002", "5", 5, 10)]
    assert body["article_id"] == "articles/bwbr0002_5"
    assert body["total"] == 41 and len(body["items"]) == 1
    assert body["items"][0]["target"] == "article_version"
    assert body["items"][0]["document"]["dossier_number"] == "36000"


def test_explained_by_of_an_unknown_article_is_an_empty_page_not_a_404(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "lawgraph.api.routes.articles.get_article_explanations",
        lambda store, bwb_id, article_number, *, limit, offset: {
            "total": 0,
            "items": [],
        },
    )

    response = client.get("/api/articles/BWBR9999/1/explained-by")

    assert response.status_code == 200
    assert response.json() == {
        "article_id": "articles/bwbr9999_1",
        "total": 0,
        "items": [],
    }


def test_explained_by_bounds_its_page() -> None:
    for params in ({"limit": 0}, {"limit": 501}, {"offset": -1}):
        response = client.get("/api/articles/BWBR0002/5/explained-by", params=params)
        assert response.status_code == 422, params
