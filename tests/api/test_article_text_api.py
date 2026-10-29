"""The narrow form of an article and the batch of them, on stubbed queries: the order asked,
what the data does not hold, and the bounds of ``refs``. ``tests/integration/
test_article_text.py`` reads real articles."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.schemas.article_text import BATCH_MAX
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
