"""Retrieve pipeline for the transposition tables of the Kamerstukken: the attachments that are
one, and the papers that hold one.

* The SRU of the KOOP repository lists every attachment (``dt.type`` ``Bijlage``) whose title
  names a transposition or concordance table (``KamerstukClient.search_tables``), with its
  dossier, the paper it belongs to and the URL of its PDF. Its PDF is stored as it is
  (base64 in the text payload).
* Its full text search lists every Kamerstuk whose text names one
  (``KamerstukClient.search_documents_naming_tables``: a heading, a sentence, a cell). Its XML is
  stored as it is when ``core.transposition_xml`` reads a table in it, the table found by its
  own head: the Wet dieren's tables (kst-31389-3) stand under no heading that names them.
  A paper without one is stored without its XML, so a next run does not fetch it again
  until the SRU says it changed.

Each one not stored yet, or changed since, is fetched, with what the SRU says of it in
``meta``. A download that fails is skipped; the next run asks for it again. ``semantic
tk-transposition-tables`` reads them.
"""

from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from typing import Any

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.config.constants import (
    RAW_KIND_TK_TRANSPOSITION_DOCUMENT,
    RAW_KIND_TK_TRANSPOSITION_TABLE,
    SOURCE_TK,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.transposition_xml import read_tables
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord, listed, missing_record

logger = get_logger(__name__)


class TKTranspositionTablesRetrievePipeline(RetrievePipelineBase):
    """Store every transposition table the SRU lists, and every paper with one, that is new
    or changed."""

    def __init__(
        self, store: GraphStore, client: KamerstukClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or KamerstukClient()

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        """The PDFs, then the Kamerstukken: each listed when the one before is done."""
        yield from self._each(
            RAW_KIND_TK_TRANSPOSITION_TABLE,
            lambda: [
                table
                for table in listed(self.client.search_tables(), "transposition tables")
                if table.get("pdf_url")
            ],
            lambda table: self.client.fetch_pdf(table["pdf_url"]),
            _pdf_record,
        )
        yield from self._each(
            RAW_KIND_TK_TRANSPOSITION_DOCUMENT,
            lambda: listed(
                self.client.search_documents_naming_tables(),
                "Kamerstukken naming a transposition table",
            ),
            lambda document: self.client.fetch_xml(document["xml_url"]),
            _document_record,
        )

    def _each[T](
        self,
        kind: str,
        listing: Callable[[], list[dict[str, Any]]],
        fetch: Callable[[dict[str, Any]], T],
        record: Callable[[str, dict[str, Any], T], RetrieveRecord],
    ) -> Iterator[RetrieveRecord]:
        """The record of *kind* of each of the *listing* that is not stored or changed
        since."""
        by_id = {one["identifier"]: one for one in listing() if one.get("identifier")}
        todo = self._without_missing(
            SOURCE_TK, kind, self._changed(SOURCE_TK, kind, by_id.values())
        )
        logger.info("%s: %d listed, %d new or changed.", kind, len(by_id), len(todo))
        yield from self._download_each(
            todo,
            lambda identifier: fetch(by_id[identifier]),
            lambda identifier, got: [record(identifier, by_id[identifier], got)],
            label="KOOP",
            failed_is_skipped=True,
            missing=lambda identifier, status: missing_record(
                SOURCE_TK, kind, identifier, listed=True, status=status
            ),
        )


def _pdf_record(identifier: str, table: dict[str, Any], pdf: bytes) -> RetrieveRecord:
    return RetrieveRecord(
        source=SOURCE_TK,
        kind=RAW_KIND_TK_TRANSPOSITION_TABLE,
        external_id=identifier,
        payload_text=base64.b64encode(pdf).decode("ascii"),
        meta={
            **_meta(table),
            "main_document": table.get("main_document"),
            "url": table["pdf_url"],
            "content_type": "application/pdf",
            "encoding": "base64",
        },
    )


def _document_record(
    identifier: str, document: dict[str, Any], xml: str
) -> RetrieveRecord:
    """The paper with its XML when a table is read in it, or the XML does not read (which
    ``semantic tk-transposition-tables`` notes); without it otherwise."""
    try:
        tables: int | None = sum(
            t.problem is None for t in read_tables(xml, identifier)
        )
    except ET.ParseError:
        tables = None
    return RetrieveRecord(
        source=SOURCE_TK,
        kind=RAW_KIND_TK_TRANSPOSITION_DOCUMENT,
        external_id=identifier,
        payload_text=None if tables == 0 else xml,
        meta={**_meta(document), "url": document["xml_url"], "tables": tables},
    )


def _meta(listed: dict[str, Any]) -> dict[str, Any]:
    """What the SRU says of a table or a paper."""
    return {
        "identifier": listed["identifier"],
        "title": listed.get("title"),
        "dossier": listed.get("dossier"),
        "modified": listed.get("modified"),
    }
