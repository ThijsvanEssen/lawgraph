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
    "labels": ["TK"],
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
        "document_number": "2024D01234",
        "source": "tk",
        "text": "De inhoud van het stuk...",
    },
}


_LINKS = {
    "dossier_numbers": ["36000"],
    "explains": [
        {
            "id": "articles/bwbr0001_5",
            "key": "bwbr0001_5",
            "collection": "articles",
            "bwb_id": "BWBR0001",
            "article_number": "5",
        },
        {
            "id": "instruments/bwbr0001",
            "key": "bwbr0001",
            "collection": "instruments",
            "bwb_id": "BWBR0001",
            "article_number": None,
        },
    ],
}


class _Collection:
    def __init__(self, doc: dict | None) -> None:
        self._doc = doc

    def get(self, key: str) -> dict | None:
        return self._doc


class _Store:
    def __init__(self, doc: dict | None = None) -> None:
        self._doc = doc
        self.asked: list[tuple[str, dict]] = []

    def collection(self, name: str) -> _Collection:
        return _Collection(self._doc)

    def query(self, aql, bind_vars=None):
        self.asked.append((aql, bind_vars or {}))
        if "document_id" in (bind_vars or {}):
            return [_LINKS]
        return [{"total": 41, "items": [_ROW]}]


def _client(store: _Store) -> TestClient:
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_override():
    yield
    app.dependency_overrides.pop(get_store, None)


def test_the_index_returns_english_rows() -> None:
    body = _client(_Store()).get("/api/documents").json()
    assert body["total"] == 41  # what matches, not what this page holds
    assert body["items"][0]["kind"] == "Memorie van toelichting"
    assert body["items"][0]["date"] == "2024-03-01"
    assert body["items"][0]["linked_articles"] == 3
    assert body["items"][0]["chamber"] == "TK"
    assert body["items"][0]["source"] == "tk"
    assert body["items"][0]["is_explanatory"] is True


def test_the_index_passes_its_page_and_filters_on() -> None:
    store = _Store()
    _client(store).get("/api/documents?limit=5&offset=10&chamber=ek")
    ((_, bind),) = store.asked
    assert bind["limit"] == 5 and bind["offset"] == 10 and bind["chamber"] == "EK"


def test_the_dossier_filter_takes_a_dossier_number(monkeypatch) -> None:
    store = _Store()
    monkeypatch.setattr(
        "lawgraph.api.routes.documents.get_dossier_by_number",
        lambda store, number: {"_id": "dossiers/36000"} if number == "36000" else None,
    )
    client = _client(store)

    assert client.get("/api/documents?dossier=36000").json()["total"] == 41
    assert store.asked[0][1]["dossier_id"] == "dossiers/36000"

    unknown = client.get("/api/documents?dossier=99999").json()
    assert unknown == {"total": 0, "items": []}
    assert len(store.asked) == 1  # an unknown dossier asks nothing more
    assert client.get("/api/documents?dossier=abc").status_code == 422


def test_an_unknown_document_is_a_404() -> None:
    response = _client(_Store(None)).get("/api/documents/nonexistent-key")
    assert response.status_code == 404


def test_a_known_document_carries_its_text_its_page_and_its_file() -> None:
    body = _client(_Store(_DOCUMENT)).get("/api/documents/abc123").json()
    assert body["key"] == "abc123"
    assert body["title"] == "Memorie van Toelichting"
    assert body["kind"] == "Memorie van toelichting"
    assert body["text"].startswith("De inhoud")
    # tweedekamer.nl knows the document number, the Gegevensmagazijn the GUID
    assert body["tk_url"] == (
        "https://www.tweedekamer.nl/kamerstukken/detail?id=2024D01234&did=2024D01234"
    )
    assert body["file_url"].endswith("/Document(some-uuid)/resource")


def test_a_document_says_its_chamber_source_dossiers_and_what_it_explains() -> None:
    doc = {**_DOCUMENT, "props": {**_DOCUMENT["props"], "raw": {"Datum": "2024-03-01"}}}
    body = _client(_Store(doc)).get("/api/documents/abc123").json()
    assert body["chamber"] == "TK" and body["source"] == "tk"
    assert body["is_explanatory"] is True
    assert body["dossier_numbers"] == ["36000"]
    assert [t["collection"] for t in body["explains"]] == ["articles", "instruments"]
    assert body["explains"][0]["article_number"] == "5"
    assert body["explains"][1]["article_number"] is None


def test_an_eerste_kamer_document_is_not_explanatory_and_has_no_tk_url() -> None:
    ek = {
        "_id": "documents/ek_1",
        "_key": "ek_1",
        "labels": ["EersteKamer", "EK"],
        "props": {
            "source": "eerstekamer",
            "kind": "Verslag",
            "external_id": "ek-uuid",
        },
    }
    body = _client(_Store(ek)).get("/api/documents/ek_1").json()
    assert body["chamber"] == "EK" and body["source"] == "eerstekamer"
    assert body["is_explanatory"] is False and body["tk_url"] is None
    assert body["file_url"] is None
