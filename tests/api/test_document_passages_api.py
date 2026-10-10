"""The sections of a document and the passages of a memorandum that explain an article."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app

_TEXT = "Artikel I\nOnderdeel A\nEerste toelichting.\nOnderdeel B\nTweede toelichting."


def _section(
    section_id: str, heading: str, start: int, end: int, parent: str | None
) -> dict[str, Any]:
    return {
        "id": section_id,
        "heading": heading,
        "level": 2 if parent else 1,
        "parent": parent,
        "kind": "onderdeel" if parent else "article",
        "number": None if parent else "I",
        "number_scheme": None if parent else "roman",
        "article_refs": [] if parent else [{"number": "I", "of": "self"}],
        "law": None,
        "char_start": start,
        "char_end": end,
    }


_SECTIONS = [
    _section("s-0", "Artikel I", 0, len(_TEXT), None),
    _section("s-1", "Onderdeel A", 10, 41, "s-0"),
    _section("s-2", "Onderdeel B", 42, len(_TEXT), "s-0"),
]


def _document(text: str | None = _TEXT) -> dict[str, Any]:
    return {
        "_id": "documents/mvt1",
        "_key": "mvt1",
        "labels": ["TK"],
        "props": {
            "title": "Memorie van toelichting",
            "kind": "Memorie van toelichting",
            "text": text,
            "sections": _SECTIONS,
        },
    }


def _passage(section_id: str, heading: str, start: int, end: int, conf: float) -> dict:
    return {
        "section_anchor": section_id,
        "heading": heading,
        "char_start": start,
        "char_end": end,
        "match_type": "heading_target",
        "confidence": conf,
    }


# What the db layer answers for the article: one row per section, unsorted.
_PASSAGES = [
    _passage("s-2", "Onderdeel B", 42, len(_TEXT), 0.9),
    _passage("s-1", "Onderdeel A", 10, 41, 0.9),
]
_PARAMS = {"bwb_id": "BWBR1", "article": "5"}
_ROUTES = "lawgraph.api.routes.documents"


def _client(
    monkeypatch: pytest.MonkeyPatch,
    document: dict[str, Any] | None,
    passages: list[dict[str, Any]] | None = None,
) -> tuple[TestClient, list[tuple[str, str, str]]]:
    """A client that finds ``document`` and ``passages``; records the passages asked for."""
    asked: list[tuple[str, str, str]] = []

    def get_document_passages(
        store: Any, document_id: str, bwb_id: str, article_number: str
    ) -> list[dict[str, Any]]:
        asked.append((document_id, bwb_id, article_number))
        return list(passages or [])

    monkeypatch.setattr(f"{_ROUTES}.get_document", lambda store, key: document)
    monkeypatch.setattr(
        f"{_ROUTES}.get_document_links",
        lambda store, document_id: {"dossier_numbers": [], "explains": []},
    )
    monkeypatch.setattr(f"{_ROUTES}.get_document_passages", get_document_passages)
    monkeypatch.setattr(f"{_ROUTES}.get_document_decisions", lambda store, _id: [])
    monkeypatch.setattr(f"{_ROUTES}.get_replacements", lambda store, ids: {})
    return TestClient(app), asked


def test_a_document_lists_its_sections_with_offsets_into_its_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client(monkeypatch, _document())
    body = client.get("/api/documents/mvt1").json()

    assert [s["id"] for s in body["sections"]] == ["s-0", "s-1", "s-2"]
    assert body["sections"][0]["article_refs"] == [{"number": "I", "of": "self"}]
    for section in body["sections"]:
        assert section["char_end"] <= len(body["text"])
    second = body["sections"][1]
    assert body["text"][second["char_start"] : second["char_end"]].startswith(
        "Onderdeel A"
    )


def test_sections_that_do_not_lie_in_the_text_are_not_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cut, _ = _client(monkeypatch, _document(_TEXT[:30]))
    assert cut.get("/api/documents/mvt1").json()["sections"] == []
    without, _ = _client(monkeypatch, _document(None))
    body = without.get("/api/documents/mvt1").json()
    assert body["sections"] == [] and body["text"] is None


def test_the_passages_of_an_article_are_in_document_order_with_their_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, asked = _client(monkeypatch, _document(), _PASSAGES)

    body = client.get("/api/documents/mvt1/passages", params=_PARAMS).json()

    assert asked == [("documents/mvt1", "BWBR1", "5")]
    assert body["total"] == 2
    first, second = body["items"]
    assert (first["section_id"], first["level"], first["match_type"]) == (
        "s-1",
        2,
        "heading_target",
    )
    assert first["text"] == _TEXT[10:41] and first["confidence"] == 0.9
    assert (second["section_id"], second["confidence"]) == ("s-2", 0.9)
    assert second["text"] == _TEXT[42:]


def test_a_passage_that_does_not_lie_in_the_text_is_left_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beyond = _passage("s-9", "Onderdeel Z", 42, len(_TEXT) + 1, 1.0)
    client, _ = _client(monkeypatch, _document(), [beyond, *_PASSAGES])

    body = client.get("/api/documents/mvt1/passages", params=_PARAMS).json()

    assert [p["section_id"] for p in body["items"]] == ["s-1", "s-2"]


def test_an_article_without_passages_is_an_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client(monkeypatch, _document(), [])

    response = client.get("/api/documents/mvt1/passages", params=_PARAMS)

    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}


def test_a_document_without_text_has_no_passages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, asked = _client(monkeypatch, _document(None), _PASSAGES)

    body = client.get("/api/documents/mvt1/passages", params=_PARAMS).json()

    assert body == {"total": 0, "items": []}
    assert asked == []


def test_passages_of_an_unknown_document_are_a_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = _client(monkeypatch, None)
    response = client.get("/api/documents/nope/passages", params=_PARAMS)
    assert response.status_code == 404


def test_passages_need_the_law_and_the_article(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _client(monkeypatch, _document())
    assert client.get("/api/documents/mvt1/passages").status_code == 422
    empty = {"bwb_id": "", "article": "5"}
    assert client.get("/api/documents/mvt1/passages", params=empty).status_code == 422
