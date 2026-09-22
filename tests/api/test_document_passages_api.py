"""The sections of a document and the passages of a memorandum that explain an article."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store

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


class _Collection:
    def __init__(self, doc: dict[str, Any] | None) -> None:
        self._doc = doc

    def get(self, key: str) -> dict[str, Any] | None:
        return self._doc


class _Store:
    """The document, the article, and the edges of the article and of its version."""

    def __init__(self, docs: dict[str, dict[str, Any] | None]) -> None:
        self._docs = docs
        self.binds: list[dict[str, Any]] = []

    def collection(self, name: str) -> _Collection:
        return _Collection(self._docs.get(name))

    def query(self, aql: str, bind_vars: dict[str, Any] | None = None) -> list[Any]:
        self.binds.append(bind_vars or {})
        if "part_of" in (bind_vars or {}):  # get_document_links
            return [{"dossier_numbers": [], "explains": []}]
        if "article_versions" in aql:
            return ["article_versions/v2"]
        return [
            [_passage("s-2", "Onderdeel B", 42, len(_TEXT), 0.7)],
            [
                _passage("s-1", "Onderdeel A", 10, 41, 0.9),
                _passage("s-2", "Onderdeel B", 42, len(_TEXT), 0.9),
            ],
        ]


_ARTICLE = {"_id": "articles/bwbr1_5", "props": {"bwb_id": "BWBR1", "stam_id": "st1"}}
_PARAMS = {"bwb_id": "BWBR1", "article": "5"}


@pytest.fixture(autouse=True)
def _clear_override() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_store, None)


def _client(store: _Store) -> TestClient:
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def test_a_document_lists_its_sections_with_offsets_into_its_text() -> None:
    body = _client(_Store({"documents": _document()})).get("/api/documents/mvt1").json()

    assert [s["id"] for s in body["sections"]] == ["s-0", "s-1", "s-2"]
    assert body["sections"][0]["article_refs"] == [{"number": "I", "of": "self"}]
    for section in body["sections"]:
        assert section["char_end"] <= len(body["text"])
    second = body["sections"][1]
    assert body["text"][second["char_start"] : second["char_end"]].startswith(
        "Onderdeel A"
    )


def test_sections_that_do_not_lie_in_the_text_are_not_returned() -> None:
    cut = _client(_Store({"documents": _document(_TEXT[:30])}))
    assert cut.get("/api/documents/mvt1").json()["sections"] == []
    without = _client(_Store({"documents": _document(None)}))
    body = without.get("/api/documents/mvt1").json()
    assert body["sections"] == [] and body["text"] is None


def test_the_passages_of_an_article_are_in_document_order_with_their_text() -> None:
    store = _Store({"documents": _document(), "articles": _ARTICLE})

    body = _client(store).get("/api/documents/mvt1/passages", params=_PARAMS).json()

    assert body["total"] == 2
    first, second = body["items"]
    assert (first["section_id"], first["level"], first["match_type"]) == (
        "s-1",
        2,
        "heading_target",
    )
    assert first["text"] == _TEXT[10:41] and first["confidence"] == 0.9
    # a section that two edges name is one passage, with the higher confidence
    assert (second["section_id"], second["confidence"]) == ("s-2", 0.9)
    assert second["text"] == _TEXT[42:]
    # the article and its version are both looked at
    assert store.binds[-1]["targets"] == ["articles/bwbr1_5", "article_versions/v2"]


def test_an_article_without_passages_is_an_empty_list() -> None:
    client = _client(_Store({"documents": _document(), "articles": None}))

    response = client.get("/api/documents/mvt1/passages", params=_PARAMS)

    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}


def test_a_document_without_text_has_no_passages() -> None:
    store = _Store({"documents": _document(None), "articles": _ARTICLE})

    body = _client(store).get("/api/documents/mvt1/passages", params=_PARAMS).json()

    assert body == {"total": 0, "items": []}


def test_passages_of_an_unknown_document_are_a_404() -> None:
    response = _client(_Store({"documents": None})).get(
        "/api/documents/nope/passages", params=_PARAMS
    )
    assert response.status_code == 404


def test_passages_need_the_law_and_the_article() -> None:
    client = _client(_Store({"documents": _document()}))
    assert client.get("/api/documents/mvt1/passages").status_code == 422
    empty = {"bwb_id": "", "article": "5"}
    assert client.get("/api/documents/mvt1/passages", params=empty).status_code == 422
