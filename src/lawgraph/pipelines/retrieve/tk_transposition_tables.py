"""Retrieve pipeline for the transposition tables among the attachments of Kamerstukken.

The SRU of the KOOP repository lists every attachment (``dt.type`` ``Bijlage``) whose title
names a transposition or concordance table (``KamerstukClient.search_tables``), with its
dossier and the paper it belongs to; it is published as a PDF only. Each one not stored yet,
or changed since, is fetched and stored as it is (base64 in the text payload), with what the
SRU says of it in ``meta``. ``semantic tk-transposition-tables`` reads them.
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Any

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.config.constants import RAW_KIND_TK_TRANSPOSITION_TABLE, SOURCE_TK
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore

from .base import RetrievePipelineBase, RetrieveRecord, listed, missing_record

logger = get_logger(__name__)


class TKTranspositionTablesRetrievePipeline(RetrievePipelineBase):
    """Store the PDF of every transposition table the SRU lists that is new or changed."""

    def __init__(
        self, store: GraphStore, client: KamerstukClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or KamerstukClient()

    def fetch(self, **kwargs: object) -> Iterator[RetrieveRecord]:
        tables = {
            t["identifier"]: t
            for t in listed(self.client.search_tables(), "transposition tables")
            if t.get("identifier") and t.get("pdf_url")
        }
        todo = self._without_missing(
            SOURCE_TK,
            RAW_KIND_TK_TRANSPOSITION_TABLE,
            self._changed(SOURCE_TK, RAW_KIND_TK_TRANSPOSITION_TABLE, tables.values()),
        )
        logger.info(
            "Transposition tables: %d listed, %d new or changed.",
            len(tables),
            len(todo),
        )

        def records(identifier: str, pdf: bytes) -> list[RetrieveRecord]:
            return [
                RetrieveRecord(
                    source=SOURCE_TK,
                    kind=RAW_KIND_TK_TRANSPOSITION_TABLE,
                    external_id=identifier,
                    payload_text=base64.b64encode(pdf).decode("ascii"),
                    meta=_meta(tables[identifier]),
                )
            ]

        yield from self._download_each(
            todo,
            lambda identifier: self.client.fetch_pdf(tables[identifier]["pdf_url"]),
            records,
            label="KOOP",
            missing=lambda identifier, status: missing_record(
                SOURCE_TK,
                RAW_KIND_TK_TRANSPOSITION_TABLE,
                identifier,
                listed=True,
                status=status,
            ),
        )


def _meta(table: dict[str, Any]) -> dict[str, Any]:
    """What the SRU says of the table, and how its payload is written."""
    return {
        "identifier": table["identifier"],
        "title": table.get("title"),
        "dossier": table.get("dossier"),
        "main_document": table.get("main_document"),
        "url": table["pdf_url"],
        "modified": table.get("modified"),
        "content_type": "application/pdf",
        "encoding": "base64",
    }
