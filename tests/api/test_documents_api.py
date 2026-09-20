"""The document endpoints: the index and one document's text."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store

_ROW = {
    "key": "abc123",
    "title": "Memorie van Toelichting",
    "kind": "Memorie van toelichting",
    "date": "2024-03-01",
    "external_id": "some-uuid",
    "source": "tk",
    "has_text": True,
    "linked_articles": 3,
}

_DOCUMENT = {
    "_id": "documents/abc123",
    "_key": "abc123",
    "labels": ["TK"],
    "props": {
        "title": "Memorie van Toelichting",
        "kind": "Memorie van toelichting",
        "date": "2024-03-01",
        "external_id": "some-uuid",
        "source": "tk",
        "text": "De inhoud van het stuk...",
    },
}


class _Collection:
    def __init__(self, doc: dict | None) -> None:
        self._doc = doc

    def get(self, key: str) -> dict | None:
        return self._doc


class _Store:
    def __init__(self, doc: dict | None = None) -> None:
        self._doc = doc

    def collection(self, name: str) -> _Collection:
        return _Collection(self._doc)

    def query(self, aql, bind_vars=None):
        return [_ROW]


def _client(store: _Store) -> TestClient:
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_override():
    yield
    app.dependency_overrides.pop(get_store, None)


def test_the_index_returns_english_rows() -> None:
    body = _client(_Store()).get("/api/documents").json()
    assert body["total"] == 1
    assert body["items"][0]["kind"] == "Memorie van toelichting"
    assert body["items"][0]["date"] == "2024-03-01"
    assert body["items"][0]["linked_articles"] == 3


def test_an_unknown_document_is_a_404() -> None:
    response = _client(_Store(None)).get("/api/documents/nonexistent-key")
    assert response.status_code == 404


def test_a_known_document_carries_its_text_and_tk_url() -> None:
    body = _client(_Store(_DOCUMENT)).get("/api/documents/abc123").json()
    assert body["key"] == "abc123"
    assert body["title"] == "Memorie van Toelichting"
    assert body["kind"] == "Memorie van toelichting"
    assert body["text"].startswith("De inhoud")
    assert "some-uuid" in body["tk_url"]
