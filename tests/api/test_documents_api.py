"""The document endpoint: one document's text."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lawgraph.api.app import app

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


_ROUTES = "lawgraph.api.routes.documents"


def _client(monkeypatch, doc: dict | None) -> tuple[TestClient, list[tuple[str, str]]]:
    """A client whose document lookups answer ``doc``; records the keys and ids asked."""
    calls: list[tuple[str, str]] = []

    def get_document(store, key: str) -> dict | None:
        calls.append(("document", key))
        return doc

    def get_document_links(store, document_id: str) -> dict:
        calls.append(("links", document_id))
        return _LINKS

    monkeypatch.setattr(f"{_ROUTES}.get_document", get_document)
    monkeypatch.setattr(f"{_ROUTES}.get_document_links", get_document_links)
    monkeypatch.setattr(f"{_ROUTES}.get_document_decisions", lambda store, _id: [])
    return TestClient(app), calls


def test_an_unknown_document_is_a_404(monkeypatch) -> None:
    response = _client(monkeypatch, None)[0].get("/api/documents/nonexistent-key")
    assert response.status_code == 404


def test_a_known_document_carries_its_text_its_page_and_its_file(monkeypatch) -> None:
    body = _client(monkeypatch, _DOCUMENT)[0].get("/api/documents/abc123").json()
    assert body["key"] == "abc123"
    assert body["title"] == "Memorie van Toelichting"
    assert body["kind"] == "Memorie van toelichting"
    assert body["text"].startswith("De inhoud")
    # tweedekamer.nl knows the document number, the Gegevensmagazijn the GUID
    assert body["tk_url"] == (
        "https://www.tweedekamer.nl/kamerstukken/detail?id=2024D01234&did=2024D01234"
    )
    assert body["file_url"].endswith("/Document(some-uuid)/resource")


def test_a_document_says_its_chamber_source_dossiers_and_what_it_explains(
    monkeypatch,
) -> None:
    doc = {**_DOCUMENT, "props": {**_DOCUMENT["props"], "raw": {"Datum": "2024-03-01"}}}
    client, calls = _client(monkeypatch, doc)
    body = client.get("/api/documents/abc123").json()
    assert calls == [("document", "abc123"), ("links", "documents/abc123")]
    assert body["chamber"] == "TK" and body["source"] == "tk"
    assert body["is_explanatory"] is True
    assert body["dossier_numbers"] == ["36000"]
    assert [t["collection"] for t in body["explains"]] == ["articles", "instruments"]
    assert body["explains"][0]["article_number"] == "5"
    assert body["explains"][1]["article_number"] is None


def test_an_eerste_kamer_document_is_not_explanatory_and_has_no_tk_url(
    monkeypatch,
) -> None:
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
    body = _client(monkeypatch, ek)[0].get("/api/documents/ek_1").json()
    assert body["chamber"] == "EK" and body["source"] == "eerstekamer"
    assert body["is_explanatory"] is False and body["tk_url"] is None
    assert body["file_url"] is None
