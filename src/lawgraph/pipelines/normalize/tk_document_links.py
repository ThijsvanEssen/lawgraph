"""Normalize the links of Tweede Kamer documents (``retrieve tk-document-links``) into edges.

A document is the record of an activity (a stenogram of its debate: MADE_IN) and a letter
has attachments (ACCOMPANIES, from the attachment to the letter). ``normalize tk-dossiers``
makes the same edges of the documents it reads, from their own records; this makes them of
the link records, which hold every paper, also those stored before their records named
their links. Edges only between nodes that exist; a link to a paper or activity not yet
stored is made by a later run.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import RAW_KIND_TK_DOCUMENT_LINKS, SOURCE_TK
from lawgraph.core import tk_records
from lawgraph.core.batching import chunked
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.raw_records import payload_json
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize import _tk_cases as tk_cases
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "tk-document-links"

# Link records written as edges at a time: the existence lookups are per batch.
_BATCH = 5000


class TKDocumentLinksNormalizePipeline(NormalizePipelineBase):
    """Write MADE_IN and ACCOMPANIES edges from the stored links of TK documents."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_TK,
            kinds=[RAW_KIND_TK_DOCUMENT_LINKS],
            since=since,
            batch_size=_BATCH,
        )

    def normalize_nodes(
        self, raw: Iterable[dict[str, Any]], result: PipelineResult
    ) -> int:
        """No nodes: the links are edges, written batch by batch as they are read."""
        count = 0
        for records in chunked(raw, _BATCH):
            links = [
                (str(payload["Id"]), tk_records.document_links(payload))
                for record in records
                if (payload := payload_json(record))
                and payload.get("Id")
                and not tk_records.is_deleted(payload)
            ]
            result.skipped += len(records) - len(links)
            tk_cases.link_documents(self.store, links, source=EDGE_SOURCE)
            count += len(links)
        logger.info("Document links: %d documents read.", count)
        return count

    def build_edges(self, raw: Iterable[dict[str, Any]], normalized: int) -> None:
        """Written in ``normalize_nodes``, batch by batch."""
