"""Retrieve pipeline: the links of every Tweede Kamer Document, and nothing else.

A Document record of ``retrieve tk-dossiers`` is kilobytes; its links (the activity it is
the record of, its attachments, the letters it is an attachment of) are a few hundred bytes.
This fetches only those, so the links of every paper can be fetched again cheaply: the
papers stored before ``fetch_documents`` asked for them, and those whose links change
without the paper itself (``ApiGewijzigdOp`` moves with either). Stored idempotently in
``raw_sources`` as (source="tk", kind="tk-document-links", external_id=TK GUID).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from lawgraph.clients.tk import TKClient
from lawgraph.config.constants import RAW_KIND_TK_DOCUMENT_LINKS, SOURCE_TK
from lawgraph.core.logging import get_logger
from lawgraph.db import GraphStore
from lawgraph.pipelines.retrieve.base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class TKDocumentLinksRetrievePipeline(RetrievePipelineBase):
    """Retrieve the links of the TK Documents modified since a moment (all: from the epoch)."""

    def __init__(self, store: GraphStore, tk_client: TKClient | None = None) -> None:
        super().__init__(store)
        self.tk = tk_client or TKClient()

    def fetch(  # type: ignore[override]
        self, *, since: dt.datetime | None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        # The first page says how many records the query matches.
        self.tk.on_total = self.progress.expect
        for record in self.tk.fetch_document_links(since=since):
            external_id = str(record.get("Id") or "")
            if not external_id:
                self.progress.fail("record without Id")
                continue
            yield RetrieveRecord(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_DOCUMENT_LINKS,
                external_id=external_id,
                payload_json=record,
            )
