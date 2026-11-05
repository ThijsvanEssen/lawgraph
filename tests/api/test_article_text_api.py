"""The narrow form of an article and the batch of them, on stubbed queries: the order asked,
what the data does not hold, and the bounds of ``refs``. ``tests/integration/
test_article_text.py`` reads real articles."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.schemas.article_text import BATCH_MAX, text_since
from lawgraph.db.queries.article_text import ArticleTextData
from tests.api.stubs import stub_route
from tests.asserts import assert_status

client = TestClient(app)


def _article(number: str) -> ArticleTextData:
    key = f"bwbr0052875_{number}"
    return ArticleTextData(
        article={
            "id": f"articles/{key}",
            "key": key,
            "props": {
                "bwb_id": "BWBR0052875",
                "article_number": number,
                "label": f"Artikel {number}",
                "text": "1. Een.\n2. Twee.",
                "parts": [
                    {"id": "lid-1", "kind": "lid", "number": "1", "start": 3, "end": 7},
                    {
                        "id": "lid-2",
                        "kind": "lid",
                        "number": "2",
                        "start": 11,
                        "end": 16,
                    },
                ],
            },
        },
        instrument=None,
        ended=None,
    )


def _texts(store: Any, keys: list[str]) -> tuple[dict[str, ArticleTextData], set]:
    held = {"bwbr0052875_19": _article("19"), "bwbr0052875_28": _article("28")}
    return {key: held[key] for key in keys if key in held}, set()


def test_the_batch_answers_in_the_order_asked(monkeypatch) -> None:
    stub_route(monkeypatch, "articles", get_article_texts=_texts)
    refs = "BWBR0052875/28,BWBR0052875/999,BWBR0052875/19,BWBR0052875/28"
    response = client.get("/api/articles/batch", params={"refs": refs})
    assert_status(response, 200)
    body = response.json()

    assert [item["ref"] for item in body["items"]] == [
        "BWBR0052875/28",
        "BWBR0052875/999",
        "BWBR0052875/19",
    ]
    assert [(i["article"] or {}).get("article_number") for i in body["items"]] == [
        "28",
        None,
        "19",
    ]
    assert body["not_in_data"] == ["BWBR0052875/999"]
    blocks = body["items"][0]["article"]["blocks"]
    assert [(b["anchor"], b["marker"], b["text"]) for b in blocks] == [
        ("lid-1", "1.", "Een."),
        ("lid-2", "2.", "Twee."),
    ]


def test_the_batch_takes_at_most_its_maximum(monkeypatch) -> None:
    stub_route(monkeypatch, "articles", get_article_texts=_texts)
    refs = ",".join(f"BWBR0052875/{n}" for n in range(1, BATCH_MAX + 2))
    response = client.get("/api/articles/batch", params={"refs": refs})
    assert_status(response, 422)
    assert f"at most {BATCH_MAX}" in response.json()["detail"]


def test_a_ref_names_its_law_and_its_article(monkeypatch) -> None:
    stub_route(monkeypatch, "articles", get_article_texts=_texts)
    response = client.get("/api/articles/batch", params={"refs": "BWBR0052875"})
    assert_status(response, 422)
    assert "{bwb_id}/{article_number}" in response.json()["detail"]


def test_an_article_the_data_does_not_hold_is_a_404(monkeypatch) -> None:
    stub_route(monkeypatch, "articles", get_article_texts=_texts)
    assert_status(client.get("/api/articles/BWBR0052875/999/text"), 404)
    assert_status(client.get("/api/articles/BWBR0052875/19/text"), 200)


def test_a_stub_and_the_divisions_of_an_article(monkeypatch) -> None:
    data = _article("19")
    data.article["props"] |= {
        "stub": True,
        "breadcrumb": [
            {"type": "hoofdstuk", "label": "Hoofdstuk 1", "title": "Algemeen"},
            {"type": "paragraaf", "label": "§ 1.2", "title": None},
        ],
    }
    data.versions = [_version("2000-01-01", None, "Een.")]
    stub_route(
        monkeypatch,
        "articles",
        get_article_texts=lambda store, keys: ({data.article["key"]: data}, set()),
    )
    response = client.get("/api/articles/BWBR0052875/19/text")
    assert_status(response, 200)
    body = response.json()

    assert body["stub"] is True
    assert body["valid_from"] == "2000-01-01"
    assert [c["label"] for c in body["breadcrumb"]] == ["Hoofdstuk 1", "§ 1.2"]
    assert body["breadcrumb"][1]["anchor"] == "deel-hoofdstuk-1-1.2"


def _version(start: str | None, end: str | None, text: str) -> dict[str, Any]:
    return {"valid_from": start, "valid_until": end, "text": text}


def test_a_wording_starts_where_its_text_changed() -> None:
    versions = [
        _version("2000-01-01", "2010-01-01", "Oud."),
        _version("2010-01-01", "2020-01-01", "Nieuw."),
        _version("2020-01-01", None, "Nieuw.\u00a0"),
    ]

    assert text_since(versions, "2026-11-05") == "2010-01-01"
    assert text_since(versions, "2005-06-01") == "2000-01-01"


def test_a_coming_version_is_not_the_text_of_today() -> None:
    versions = [
        _version("2000-01-01", "2030-01-01", "Oud."),
        _version("2030-01-01", None, "Nieuw."),
    ]

    assert text_since(versions, "2026-11-05") == "2000-01-01"


def test_no_text_since_without_a_version_that_holds() -> None:
    lapsed = [
        _version("2000-01-01", "2020-01-01", "Oud."),
        _version("2020-01-01", "2020-01-01", ""),
    ]

    assert text_since(lapsed, "2026-11-05") is None
    assert text_since([], "2026-11-05") is None
    assert text_since([_version("2030-01-01", None, "Nieuw.")], "2026-11-05") is None
    assert text_since([_version(None, None, "Zonder datum.")], "2026-11-05") is None
