from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.schemas.articles import ArticleExplanationDTO
from lawgraph.db.queries.articles import ArticleCitationEntry, ArticleDetailData
from lawgraph.db.queries.instruments import LawOnADate
from tests.api.stubs import stub_route

client = TestClient(app)

_ARTICLE_DOC = {
    "id": "articles/BWBR0001854-287",
    "key": "BWBR0001854-287",
    "props": {
        "bwb_id": "BWBR0001854",
        "article_number": "287",
        "display_name": "Artikel 287",
        "text": "Het artikel heeft wat tekst",
    },
    "labels": ["Article"],
}

_INSTRUMENT_DOC = {
    "id": "instruments/BWBR0001854",
    "key": "BWBR0001854",
    "props": {
        "display_name": "Burgerlijk Wetboek Boek 1",
    },
    "labels": ["Instrument"],
}

_PAYLOAD = ArticleDetailData(
    article=_ARTICLE_DOC,
    instrument=_INSTRUMENT_DOC,
    metadata={"judgment_count": 1},
)


def test_get_article_detail_returns_expected_fields(monkeypatch):
    """Verifiëren dat het artikel endpoint de summarisatievelden teruggeeft."""
    stub_route(
        monkeypatch,
        "articles",
        get_article_with_relations=_PAYLOAD,
        get_article_citations=[],
        article_terms=([], {}, []),
    )
    response = client.get("/api/articles/BWBR0001854/287")
    assert response.status_code == 200
    payload = response.json()
    assert payload["term_spans"] == [] and payload["definitions"] == []

    article = payload["article"]
    assert article["display_name"] == "Artikel 287"
    assert article["bwb_id"] == "BWBR0001854"
    assert article["article_number"] == "287"
    assert article["text"] is not None and article["text"] != ""
    # the number of citing judgments, not the list (``/cited-by`` pages them)
    assert "judgments" not in payload
    assert payload["metadata"] == {"judgment_count": 1}
    assert payload["citations"] == []


def test_get_article_detail_exposes_citations(monkeypatch):
    stub_route(
        monkeypatch,
        "articles",
        get_article_with_relations=_PAYLOAD,
    )
    citation_target = {
        "id": "articles/BWBR0001854-24c",
        "key": "BWBR0001854-24c",
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
    stub_route(monkeypatch, "articles", get_article_citations=[entry])
    definition = {
        "article_key": "bwbr0001854_1",
        "article_number": "1",
        "term": "wet",
        "text": "het Wetboek van Strafrecht",
        "place": "a",
        "jci": None,
        "scope": {"kind": "wet", "path": ""},
        "refers_to": "BWBR0001854",
    }
    stub_route(
        monkeypatch,
        "articles",
        article_terms=(
            [
                {
                    "start": 30,
                    "end": 33,
                    "term": "wet",
                    "definition_ref": "bwbr0001854_1:a:wet",
                }
            ],
            {0: "bwbr0001854_1:a:wet"},
            [definition],
        ),
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
    # the defined terms: a span of its own, and the definition the citation names
    assert payload["term_spans"] == [
        {"start": 30, "end": 33, "term": "wet", "definition_ref": "bwbr0001854_1:a:wet"}
    ]
    assert citation["definition_ref"] == "bwbr0001854_1:a:wet"
    assert payload["definitions"][0]["ref"] == "bwbr0001854_1:a:wet"
    assert payload["definitions"][0]["text"] == "het Wetboek van Strafrecht"


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
        # the row names no number of its own: no nr. and no address
        "sequence": None,
        "path": None,
        "kind_group": "overig",
    }
    assert (item.heading, item.char_start, item.excerpt) == (None, None, None)


def test_an_explanation_on_an_article_has_no_version_key() -> None:
    article = _explanation(target_id="articles/bwbr0002_5")

    assert (article.target, article.article_version_key) == ("article", None)


def test_an_explanation_with_a_section_anchor_is_scoped_to_the_article() -> None:
    item = _explanation(section_anchor="artikel-5")

    assert item.scope == "article" and item.section_anchor == "artikel-5"


def test_an_explanation_of_a_section_names_its_paper_heading_and_opening() -> None:
    """The memorandum by its number (nr. 3) and the section by its heading, with the
    opening of what it says after that heading: the reader sees which passage explains the
    article without opening it."""
    body = "De zorgplicht houdt in dat een entiteit passende maatregelen neemt. " * 8
    item = _explanation(
        section_anchor="s-292",
        heading="Artikel 21 (zorgplicht)",
        char_start=368033,
        char_end=375735,
        opening="Artikel 21 (zorgplicht)\n" + body,
        paper={"dossier_number": "36764", "dossier_suffix": None, "sequence": 3},
    )

    assert item.document.sequence == 3
    assert item.document.path == "/kamerstukken/36764/3"
    assert (item.heading, item.char_start, item.char_end) == (
        "Artikel 21 (zorgplicht)",
        368033,
        375735,
    )
    assert item.excerpt is not None
    assert item.excerpt.startswith("De zorgplicht houdt in")
    assert item.excerpt.endswith("…") and len(item.excerpt) <= 300
    # a short section whole, without the ellipsis
    short = _explanation(
        section_anchor="s-1", heading="Artikel 1", opening="Artikel 1\nBegrippen."
    )
    assert short.excerpt == "Begrippen."


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

    stub_route(monkeypatch, "articles", get_article_explanations=fake)

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
    stub_route(
        monkeypatch,
        "articles",
        get_article_explanations={
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


def test_the_articles_on_a_date_are_paged_with_a_preview(monkeypatch):
    asked: list[tuple] = []
    version: dict[str, Any] = {
        "key": "bwbr0001854_av_287_1",
        "props": {
            "bwb_id": "BWBR0001854",
            "article_number": "287",
            "valid_from": "2020-01-01",
            "valid_until": None,
            "current": True,
            "text": "Hij die opzettelijk een ander van het leven berooft",
            "parts": [
                {
                    "id": "onder-_1",
                    "kind": "onderdeel",
                    "number": "–",
                    "start": 0,
                    "end": 51,
                    "term": "Hij",
                }
            ],
        },
    }

    def fake(store, bwb_id, at_date, *, limit, offset):
        asked.append((bwb_id, at_date, limit, offset))
        return LawOnADate(items=[version], total=41, first_version_from="2002-04-01")

    stub_route(monkeypatch, "instruments", get_articles_at=fake)
    body = client.get(
        "/api/instruments/BWBR0001854/articles/at/2024-01-01",
        params={"limit": 1, "offset": 40, "text_preview_chars": 3},
    ).json()

    assert asked == [("BWBR0001854", "2024-01-01", 1, 40)]
    assert body["total"] == 41 and body["at_date"] == "2024-01-01"
    (article,) = body["items"]
    assert article["text_preview"] == "Hij"
    assert article["text"] is None  # the preview was asked for
    assert article["parts"] == []
    assert article["official_url"]
    assert body["first_version_from"] == "2002-04-01"

    whole = client.get("/api/instruments/BWBR0001854/articles/at/2024-01-01").json()
    assert asked[1][2:] == (2000, 0)  # the defaults of /articles
    assert whole["items"][0]["text"] == version["props"]["text"]
    # The whole-law reader nests the text by its parts, as the article does.
    assert whole["items"][0]["parts"] == version["props"]["parts"]


def test_the_articles_on_a_date_bound_their_page_and_preview():
    path = "/api/instruments/BWBR0001854/articles/at/2024-01-01"
    for query in ("limit=0", "limit=2001", "offset=-1", "text_preview_chars=601"):
        assert client.get(f"{path}?{query}").status_code == 422, query
    assert client.get(f"{path.rsplit('/', 1)[0]}/2024-13-01").status_code == 422
