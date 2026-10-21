"""``retrieve tk-transposition-tables`` stores the PDF of each table the SRU lists as it is,
and the XML of each Kamerstuk and each Staatsblad naming one that holds a table, with what
the SRU says of it."""

from __future__ import annotations

import base64
from typing import Any

from lawgraph.clients.base import UnexpectedAnswer
from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.clients.koop_publications import STAATSBLAD, KoopPublicationClient
from lawgraph.config.constants import (
    RAW_KIND_STAATSBLAD_TRANSPOSITION,
    RAW_KIND_TK_TRANSPOSITION_DOCUMENT,
    RAW_KIND_TK_TRANSPOSITION_TABLE,
    SOURCE_STAATSBLAD,
    SOURCE_TK,
)
from lawgraph.pipelines.retrieve.tk_transposition_tables import (
    TKTranspositionTablesRetrievePipeline,
)
from tests.fakes import InMemoryStore, ScriptedSession
from tests.paths import FIXTURES, fixture_text

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
MEDIAWET = {
    "identifier": "kst-31356-3",
    "title": "Mediawet 20..; Memorie van Toelichting",
    "dossier": "31356",
    "xml_url": "https://repository.overheid.nl/frbr/officielepublicaties/kst/31356/"
    "kst-31356-3/1/xml/kst-31356-3.xml",
    "modified": "2017-06-29",
}
WITHOUT = {
    **MEDIAWET,
    "identifier": "kst-32317-90",
    "dossier": "32317",
    "xml_url": "https://repository.overheid.nl/frbr/officielepublicaties/kst/32317/"
    "kst-32317-90/1/xml/kst-32317-90.xml",
}


INVOERINGSBESLUIT = {
    "identifier": "stb-2020-400",
    "title": "Besluit van 16 september 2020 … (Invoeringsbesluit Omgevingswet)",
    "modified": "2020-10-28",
}
BESLUIT = {**INVOERINGSBESLUIT, "identifier": "stb-2024-12", "modified": "2024-01-20"}


def _publications(asked: list[str]) -> Any:
    """A client that lists two Staatsbladen naming a table: the Invoeringsbesluit
    Omgevingswet, whose nota van toelichting holds them, and one naming an EU table."""
    xml = {
        "stb-2020-400": fixture_text("stb_2020_400_excerpt.xml"),
        "stb-2024-12": "<officiele-publicatie><al>Transponeringstabel</al>"
        "</officiele-publicatie>",
    }

    def fetch_publication_xml(identifier: str) -> str:
        asked.append(identifier)
        return xml[identifier]

    client = type("Stb", (), {})()
    client.search_naming_tables = lambda: [INVOERINGSBESLUIT, BESLUIT]
    client.fetch_publication_xml = fetch_publication_xml
    return client


def _client(documents: dict[str, str], asked: list[str]) -> Any:
    """A client that lists the PDF of LISTED and *papers* (identifier -> XML)."""

    def fetch_pdf(url: str) -> bytes:
        asked.append(url)
        return PDF

    def fetch_xml(url: str) -> str:
        asked.append(url)
        return documents[url]

    client = type("Kst", (), {})()
    client.search_tables = lambda: [LISTED]
    client.search_documents_naming_tables = lambda: [MEDIAWET, WITHOUT]
    client.fetch_pdf = fetch_pdf
    client.fetch_xml = fetch_xml
    return client


def _documents() -> dict[str, str]:
    return {
        MEDIAWET["xml_url"]: fixture_text("kst_31356_3_excerpt.xml"),
        WITHOUT[
            "xml_url"
        ]: "<kamerstuk><al>Zie de transponeringstabel.</al></kamerstuk>",
    }


def test_the_pdf_is_stored_as_it_is_with_its_dossier(raw_reads: None) -> None:
    asked: list[str] = []
    store = InMemoryStore()

    result = TKTranspositionTablesRetrievePipeline(
        store, client=_client(_documents(), asked), publications=_publications([])
    ).run()

    assert (result.created, result.errors, asked[0]) == (5, [], LISTED["pdf_url"])
    record = next(r for r in store.raw.values() if r["external_id"] == "blg-1081574")
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


def test_the_pdf_of_a_table_that_is_also_xml_is_its_pdf_manifestation() -> None:
    """Of a table the repository also has as XML (blg-123216, 32291) the SRU's ``url`` is
    that XML; its PDF is the ``itemUrl`` of the manifestation ``pdf``."""
    page = fixture_text("sru_transposition_table_with_xml.xml")
    client = KamerstukClient(session=ScriptedSession(lambda sent: page))
    (table,) = client.search_tables()
    assert (table["identifier"], table["pdf_url"]) == (
        "blg-123216",
        "https://repository.overheid.nl/frbr/officielepublicaties/blg/onopgemaakt/"
        "blg-123216/1/pdf/blg-123216.pdf",
    ), table


def test_a_paper_is_stored_with_its_xml_when_a_table_is_read_in_it(
    raw_reads: None,
) -> None:
    """The Mediawet 2008 (kst-31356-3) has a table under no heading that names it; a paper
    that only names one in a sentence is stored without its XML, so the next run leaves
    both alone until the SRU says they changed."""
    asked: list[str] = []
    store = InMemoryStore()
    TKTranspositionTablesRetrievePipeline(
        store, client=_client(_documents(), asked), publications=_publications([])
    ).run()

    documents = {
        r["external_id"]: r
        for r in store.raw.values()
        if r["kind"] == RAW_KIND_TK_TRANSPOSITION_DOCUMENT
    }
    assert documents["kst-31356-3"]["payload_text"] == fixture_text(
        "kst_31356_3_excerpt.xml"
    )
    assert documents["kst-31356-3"]["meta"] == {
        "identifier": "kst-31356-3",
        "title": MEDIAWET["title"],
        "dossier": "31356",
        "modified": "2017-06-29",
        "url": MEDIAWET["xml_url"],
        "tables": 1,
    }
    assert documents["kst-32317-90"].get("payload_text") is None
    assert documents["kst-32317-90"]["meta"]["tables"] == 0

    again: list[str] = []
    TKTranspositionTablesRetrievePipeline(
        store, client=_client(_documents(), again), publications=_publications(again)
    ).run()
    assert again == []


def test_a_paper_naming_a_table_is_listed_by_its_full_text_with_its_xml() -> None:
    """The full text search of the SRU; a paper without XML (a scan of Staten-Generaal
    Digitaal, a paper only a PDF) is not listed."""
    page = fixture_text("sru_transposition_table_with_xml.xml")
    without = page.replace(
        '<gzd:itemUrl manifestation="xml">', '<gzd:itemUrl manifestation="ocr">'
    )
    asked: list[dict] = []
    client = KamerstukClient(session=ScriptedSession(lambda sent: page, asked=asked))
    (document,) = client.search_documents_naming_tables()
    assert (document["identifier"], document["dossier"], document["xml_url"]) == (
        "blg-123216",
        "32291",
        "https://repository.overheid.nl/frbr/officielepublicaties/blg/onopgemaakt/"
        "blg-123216/1/xml/blg-123216.xml",
    )
    assert 'cql.textAndIndexes="transponeringstabel"' in asked[0]["query"]
    client = KamerstukClient(session=ScriptedSession(lambda sent: without))
    assert client.search_documents_naming_tables() == []


def test_a_failed_download_is_a_skip_and_the_next_run_asks_again(
    raw_reads: None,
) -> None:
    """On 20 October the repository once answered blg-123216 with something that was not a
    PDF; a day later it served the PDF. One such answer skips that table, the run stores
    the rest, and the next run asks for it again."""
    asked: list[str] = []
    store = InMemoryStore()
    client = _client(_documents(), asked)
    client.fetch_pdf = lambda url: (_ for _ in ()).throw(
        UnexpectedAnswer(f"not a PDF: {url}")
    )

    result = TKTranspositionTablesRetrievePipeline(
        store, client=client, publications=_publications([])
    ).run()

    assert (result.created, result.skipped, result.errors) == (4, 1, [])
    stored = {r["external_id"] for r in store.raw.values()}
    assert "blg-1081574" not in stored

    again: list[str] = []
    TKTranspositionTablesRetrievePipeline(
        store, client=_client(_documents(), again), publications=_publications(again)
    ).run()
    assert again == [LISTED["pdf_url"]]


def test_a_staatsblad_is_stored_with_its_xml_when_a_table_is_read_in_it(
    raw_reads: None,
) -> None:
    """The Invoeringsbesluit Omgevingswet (Stb. 2020, 400) holds its transposition tables
    in its nota van toelichting; a Staatsblad that only names one (an EU table, most of
    them) is stored without its XML, and neither is fetched again until the SRU says it
    changed."""
    asked: list[str] = []
    store = InMemoryStore()
    TKTranspositionTablesRetrievePipeline(
        store, client=_client(_documents(), []), publications=_publications(asked)
    ).run()

    assert asked == ["stb-2020-400", "stb-2024-12"]
    stored = {
        r["external_id"]: r
        for r in store.raw.values()
        if r["kind"] == RAW_KIND_STAATSBLAD_TRANSPOSITION
    }
    record = stored["stb-2020-400"]
    assert (record["source"], record["payload_text"]) == (
        SOURCE_STAATSBLAD,
        fixture_text("stb_2020_400_excerpt.xml"),
    )
    assert record["meta"] == {
        "identifier": "stb-2020-400",
        "title": INVOERINGSBESLUIT["title"],
        "modified": "2020-10-28",
        "tables": 4,  # a., b., r. and cc.; bb. is of another layout
    }
    assert stored["stb-2024-12"].get("payload_text") is None
    assert stored["stb-2024-12"]["meta"]["tables"] == 0

    again: list[str] = []
    TKTranspositionTablesRetrievePipeline(
        store, client=_client(_documents(), []), publications=_publications(again)
    ).run()
    assert again == []


def test_the_staatsbladen_naming_a_table_are_listed_by_their_full_text() -> None:
    """Any type of the Staatsblad (an AMvB, a law): the full text search of the SRU."""
    page = fixture_text("sru_transposition_table_with_xml.xml").replace(
        "blg-123216", "stb-2020-400"
    )
    asked: list[dict] = []
    client = KoopPublicationClient(
        STAATSBLAD, session=ScriptedSession(lambda sent: page, asked=asked)
    )
    (found,) = client.search_naming_tables()
    assert found["identifier"] == "stb-2020-400"
    assert asked[0]["query"].startswith("w.publicatienaam=Staatsblad AND (")
    assert 'cql.textAndIndexes="concordantietabellen"' in asked[0]["query"]
