from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.schemas.judgments import JudgmentDTO
from lawgraph.db.queries.judgments import (
    JudgmentArticleRelation,
    JudgmentDetailData,
    JudgmentFilters,
)

client = TestClient(app)

_JUDGMENT_DOC = {
    "_id": "judgments/ECLI:NL:HR:2020:123",
    "_key": "ECLI:NL:HR:2020:123",
    "props": {"display_name": "HR 2020", "ecli": "ECLI:NL:HR:2020:123"},
    "labels": ["Judgment"],
}

_ARTICLE_DOC = {
    "_id": "articles/BWBR0001854-287",
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


_PAYLOAD = JudgmentDetailData(
    judgment=_JUDGMENT_DOC,
    articles=[
        JudgmentArticleRelation(article=_ARTICLE_DOC, instrument=_INSTRUMENT_DOC)
    ],
    metadata={"article_count": 1},
)


def test_get_judgment_detail_returns_404_for_unknown_ecli(monkeypatch):
    """GET /api/judgments/{ecli} returns 404 when the judgment is not found."""
    monkeypatch.setattr(
        "lawgraph.api.routes.judgments.get_judgment_with_relations",
        lambda store, ecli: (_ for _ in ()).throw(ValueError("judgment not found")),
    )
    response = client.get("/api/judgments/ECLI:NL:XX:9999:NONEXISTENT")
    assert response.status_code == 404


def test_get_judgment_detail_returns_linked_articles(monkeypatch):
    """Verifiëren dat het judgment endpoint metadata en artikelrelaties levert."""
    monkeypatch.setattr(
        "lawgraph.api.routes.judgments.get_judgment_with_relations",
        lambda store, ecli: _PAYLOAD,
    )

    response = client.get("/api/judgments/ECLI:NL:HR:2020:123")
    assert response.status_code == 200
    payload = response.json()

    judgment = payload["judgment"]
    assert judgment["display_name"] == "HR 2020"
    assert judgment["ecli"] == "ECLI:NL:HR:2020:123"

    articles = payload["articles"]
    assert isinstance(articles, list) and len(articles) == 1
    article = articles[0]
    assert article["id"].startswith("articles")
    assert article["display_name"] == "Artikel 287"
    assert article["instrument"] is not None


def test_get_judgment_detail_names_its_series(monkeypatch):
    """A judgment of a series carries its id and size, and the other judgments in it."""
    judgment = {
        **_JUDGMENT_DOC,
        "props": {
            **_JUDGMENT_DOC["props"],
            "series_id": "ECLI:NL:HR:2020:122",
            "series_size": 2,
        },
    }
    other = {
        "_id": "judgments/ecli_nl_hr_2020_122",
        "_key": "ecli_nl_hr_2020_122",
        "props": {"display_name": "HR 2020/122", "ecli": "ECLI:NL:HR:2020:122"},
    }
    monkeypatch.setattr(
        "lawgraph.api.routes.judgments.get_judgment_with_relations",
        lambda store, ecli: JudgmentDetailData(
            judgment=judgment, articles=[], series=[other]
        ),
    )

    payload = client.get("/api/judgments/ECLI:NL:HR:2020:123").json()

    assert payload["judgment"]["series_id"] == "ECLI:NL:HR:2020:122"
    assert payload["judgment"]["series_size"] == 2
    assert [j["ecli"] for j in payload["series"]] == ["ECLI:NL:HR:2020:122"]


# ── the passages of the judgment that cite an article ───────────────────────

_MENTIONS = [
    {
        "paragraph_id": "rov-5.3",
        "paragraph_number": "5.3",
        "start": 4,
        "end": 15,
        "raw_match": "art. 287 Sr",
        "leden": [],
        "onderdelen": [],
        "aanhef": False,
        "snippet": "Zie art. 287 Sr en later.",
        "confidence": 0.7,
    },
    {
        "paragraph_id": "rov-5.3",
        "paragraph_number": "5.3",
        "start": 30,
        "end": 53,
        "raw_match": "art. 287, derde lid, Sr",
        "qualifier": "derde lid",
        "leden": ["3"],
        "onderdelen": [],
        "aanhef": False,
        "snippet": "en later art. 287, derde lid, Sr.",
        "confidence": 0.95,
    },
    {
        "paragraph_id": "rov-6",
        "paragraph_number": "6",
        "start": 0,
        "end": 11,
        "raw_match": "art. 287 Sr",
        "leden": [],
        "onderdelen": [],
        "aanhef": False,
        "snippet": "art. 287 Sr.",
        "confidence": 0.95,
    },
]

_JUDGMENT_WITH_PARAGRAPHS = {
    **_JUDGMENT_DOC,
    "props": {
        **_JUDGMENT_DOC["props"],
        "paragraphs": [
            {"id": "p-1", "number": None, "kind": "subheading", "text": "Arrest"},
            {
                "id": "rov-5.3",
                "number": "5.3",
                "kind": "body",
                "text": "Zie art. 287 Sr en later art. 287, derde lid, Sr.",
            },
            {"id": "rov-6", "number": "6", "kind": "body", "text": "art. 287 Sr."},
        ],
    },
}


def _detail(monkeypatch, meta):
    payload = JudgmentDetailData(
        judgment=_JUDGMENT_WITH_PARAGRAPHS,
        articles=[
            JudgmentArticleRelation(
                article=_ARTICLE_DOC,
                instrument=_INSTRUMENT_DOC,
                confidence=0.95,
                meta=meta,
            )
        ],
        metadata={"article_count": 1},
    )
    monkeypatch.setattr(
        "lawgraph.api.routes.judgments.get_judgment_with_relations",
        lambda store, ecli: payload,
    )
    return client.get("/api/judgments/ECLI:NL:HR:2020:123").json()


def test_a_paragraph_has_an_id_and_the_citations_stored_for_it(monkeypatch):
    body = _detail(monkeypatch, {"mention_count": 3, "mentions": _MENTIONS})

    paragraphs = {p["paragraph_id"]: p for p in body["judgment"]["paragraphs"]}
    assert list(paragraphs) == ["p-1", "rov-5.3", "rov-6"]
    assert paragraphs["rov-5.3"]["number"] == "5.3"
    assert paragraphs["p-1"]["number"] is None and paragraphs["p-1"]["citations"] == []

    text = paragraphs["rov-5.3"]["text"]
    first, second = paragraphs["rov-5.3"]["citations"]
    assert (first["start"], first["end"]) == (4, 15)
    assert text[first["start"] : first["end"]] == "art. 287 Sr"
    assert second["leden"] == ["3"] and second["text"] == "art. 287, derde lid, Sr"
    assert second["target"]["article_number"] == "287"
    assert [c["start"] for c in paragraphs["rov-6"]["citations"]] == [0]


def test_a_paragraph_normalized_before_paragraph_id_existed_falls_back_to_its_position():
    """A paragraph written before `paragraph_id` was part of the shape has no "id"; the
    judgment must still answer rather than 500 on one stale record."""
    doc = {
        **_JUDGMENT_DOC,
        "props": {
            **_JUDGMENT_DOC["props"],
            "paragraphs": [
                {"number": None, "kind": "subheading", "text": "Arrest"},
                {"id": "rov-1", "number": "1", "kind": "body", "text": "Overweging."},
                {"number": None, "kind": "body", "text": "Nog een oude alinea."},
            ],
        },
    }

    paragraphs = JudgmentDTO.from_document(doc).paragraphs

    assert [p.paragraph_id for p in paragraphs] == ["p-1", "rov-1", "p-3"]


def test_a_cited_article_says_where_and_what_it_names(monkeypatch):
    body = _detail(monkeypatch, {"mention_count": 3, "mentions": _MENTIONS})

    (cited,) = body["cited_articles"]
    assert cited["article"]["display_name"] == "Artikel 287"
    assert cited["article"]["instrument"] is not None
    assert cited["paragraph_ids"] == ["rov-5.3", "rov-6"]
    assert cited["paragraph_numbers"] == ["5.3", "6"]
    assert cited["mention_count"] == 3
    # the strongest mention (0.95, the first of them) speaks for the article
    assert cited["qualifier"] == "derde lid" and cited["leden"] == ["3"]
    assert cited["snippet"] == "en later art. 287, derde lid, Sr."
    assert cited["confidence"] == 0.95
    assert body["articles"][0]["key"] == cited["article"]["key"]


def test_a_cited_article_without_mentions_keeps_the_confidence_of_its_edge(
    monkeypatch,
):
    body = _detail(monkeypatch, {"raw_match": "art. 287 Sr"})

    (cited,) = body["cited_articles"]
    assert cited["paragraph_ids"] == [] and cited["mention_count"] == 0
    assert cited["confidence"] == 0.95 and cited["snippet"] is None
    assert cited["leden"] == []
    assert all(p["citations"] == [] for p in body["judgment"]["paragraphs"])


_LIST_ROW = {
    "_id": "judgments/ecli_nl_hr_2020_123",
    "_key": "ecli_nl_hr_2020_123",
    "ecli": "ECLI:NL:HR:2020:123",
    "tier": "hoge_raad",
    "date": "2020-01-02",
    "subjects": ["Bestuursrecht; Belastingrecht"],
    "inbound_citation_count": 4,
}


def test_the_judgment_list_filters_by_area_of_law_and_carries_facets(monkeypatch):
    asked: list[tuple[JudgmentFilters, dict]] = []
    facets = {
        "tier": [{"value": "hoge_raad", "count": 7}, {"value": None, "count": 1}],
        "year": [{"value": None, "count": 1}, {"value": "2020", "count": 7}],
    }

    def fake(store, filters, **kwargs):
        asked.append((filters, kwargs))
        return {"total": 8, "items": [_LIST_ROW], "facets": facets}

    monkeypatch.setattr("lawgraph.api.routes.judgments.get_judgments_list", fake)
    body = client.get(
        "/api/judgments",
        params={"subject": " Strafrecht ", "tier": "hoge_raad", "from": "2020-01-01"},
    ).json()

    assert asked[0][0] == JudgmentFilters(
        tier="hoge_raad", subject="Strafrecht", date_from="2020-01-01"
    )
    assert asked[0][1] == {"sort": "date_desc", "limit": 50, "offset": 0}
    assert body["total"] == 8
    assert body["items"][0]["subjects"] == ["Bestuursrecht; Belastingrecht"]
    assert body["facets"] == facets


def test_a_judgment_without_subjects_lists_none(monkeypatch):
    row = {k: v for k, v in _LIST_ROW.items() if k != "subjects"}
    monkeypatch.setattr(
        "lawgraph.api.routes.judgments.get_judgments_list",
        lambda store, filters, **kwargs: {"total": 1, "items": [row]},
    )
    body = client.get("/api/judgments").json()
    assert body["items"][0]["subjects"] == []
    assert body["facets"] == {"tier": [], "year": []}
