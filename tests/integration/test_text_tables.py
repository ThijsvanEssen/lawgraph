"""Tables in a Kamerstuk and in a judgment through the chain, on a real database: the real
``normalize tk-content`` and ``normalize rechtspraak`` keep them, and ``/api/documents/{key}``
and ``/api/judgments/{ecli}`` serve them as spans of the text."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.db import GraphStore
from lawgraph.pipelines.retrieve.tk_content import TKContentRetrievePipeline
from tests.asserts import assert_status, show_items
from tests.fakes import http_error
from tests.integration.seed import FIXTURES, seed, write_judgments

ECLI = "ECLI:NL:GHAMS:2025:118"


class _Repository:
    """The KOOP repository: one paper (kst-33478-3, a transposition table) for the first
    memorandum of the seed, HTTP 404 for the rest."""

    def fetch_kamerstuk_xml(self, identifier: str) -> str:
        if identifier != "kst-36000-1":
            raise http_error(404)
        return (FIXTURES / "kst_33478_3.xml").read_text(encoding="utf-8")


@pytest.fixture
def client(database: str) -> Iterator[tuple[GraphStore, TestClient]]:
    store = GraphStore()
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield store, TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _rows(text: str, table: dict[str, Any]) -> list[list[str]]:
    return [row.split("\t") for row in text[table["start"] : table["end"]].split("\n")]


def test_a_paper_serves_its_tables(
    client: tuple[GraphStore, TestClient], cli: Any
) -> None:
    store, api = client
    seed(store, documents=50, judgments=0, regulations=1)
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")
    TKContentRetrievePipeline(
        store=store, client=cast(KamerstukClient, _Repository())
    ).run(kinds=["toelichting"])
    cli("normalize", "tk-content")
    (key,) = store.query(
        "SELECT key FROM documents WHERE lg_num(props -> 'sequence') = 1"
    )

    answer = api.get(f"/api/documents/{key}")
    assert_status(answer, 200)
    body = answer.json()
    (table,) = body["tables"]
    rows = _rows(body["text"], table)
    assert rows[0][0] == "I. 1" and len(rows[0]) == 3
    assert len(rows[1]) == 2  # next to "I. 1", which spans two rows
    assert (table["head_rows"], table["columns"]) == (0, 3)
    assert table["spans"][0] == {"row": 0, "cell": 0, "cols": 1, "rows": 2}


def test_a_paragraph_of_a_judgment_serves_its_table(
    client: tuple[GraphStore, TestClient], cli: Any
) -> None:
    store, api = client
    xml = (FIXTURES / "rechtspraak_ghams_2025_118.xml").read_text(encoding="utf-8")
    write_judgments(store, {ECLI: xml})
    cli("normalize", "rechtspraak")

    answer = api.get(f"/api/judgments/{ECLI}")
    assert_status(answer, 200)
    body = answer.json()
    (paragraph,) = [
        p for p in body["judgment"]["paragraphs"] if p["paragraph_id"] == "rov-5.12"
    ]
    (table,) = paragraph["tables"]
    assert paragraph["text"][: table["start"]].endswith("worden begroot op:\n\n")
    assert _rows(paragraph["text"], table)[-1] == ["Totaal", "€", "7.671,00", ""]
    assert (table["head_rows"], table["columns"], table["spans"]) == (0, 4, [])
    others = [
        p["paragraph_id"]
        for p in body["judgment"]["paragraphs"]
        if p["tables"] and p["paragraph_id"] != "rov-5.12"
    ]
    assert not others, show_items(others)
