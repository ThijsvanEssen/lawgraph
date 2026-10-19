"""``retrieve tk-transposition-tables`` stores the PDF of each table the SRU lists as it is,
with what the SRU says of it."""

from __future__ import annotations

import base64

from lawgraph.config.constants import RAW_KIND_TK_TRANSPOSITION_TABLE, SOURCE_TK
from lawgraph.pipelines.retrieve.tk_transposition_tables import (
    TKTranspositionTablesRetrievePipeline,
)
from tests.fakes import InMemoryStore
from tests.paths import FIXTURES

PDF = (FIXTURES / "blg_1081574_excerpt.pdf").read_bytes()
LISTED = {
    "identifier": "blg-1081574",
    "title": "Transponeringstabellen nieuw naar huidig en huidig naar nieuw Sv",
    "dossier": "36327",
    "main_document": "kst-36327-3",
    "pdf_url": "https://repository.overheid.nl/frbr/officielepublicaties/blg/onopgemaakt/"
    "blg-1081574/1/pdf/blg-1081574.pdf",
    "modified": "2023-04-14",
}


def test_the_pdf_is_stored_as_it_is_with_its_dossier(raw_reads: None) -> None:
    asked: list[str] = []

    def fetch_pdf(url: str) -> bytes:
        asked.append(url)
        return PDF

    client = type("Kst", (), {})()
    client.search_tables = lambda: [LISTED]
    client.fetch_pdf = fetch_pdf
    store = InMemoryStore()

    result = TKTranspositionTablesRetrievePipeline(store, client=client).run()

    assert (result.created, result.errors, asked) == (1, [], [LISTED["pdf_url"]])
    (record,) = store.raw.values()
    assert (record["source"], record["kind"], record["external_id"]) == (
        SOURCE_TK,
        RAW_KIND_TK_TRANSPOSITION_TABLE,
        "blg-1081574",
    )
    assert base64.b64decode(record["payload_text"]) == PDF
    assert record["meta"] == {
        "identifier": "blg-1081574",
        "title": LISTED["title"],
        "dossier": "36327",
        "main_document": "kst-36327-3",
        "url": LISTED["pdf_url"],
        "modified": "2023-04-14",
        "content_type": "application/pdf",
        "encoding": "base64",
    }
