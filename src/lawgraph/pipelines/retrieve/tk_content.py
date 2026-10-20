"""Pipeline that fetches the XML of Tweede Kamer documents and stores it in raw_sources.

Every document numbered in a dossier qualifies: a Kamerstuk, which the repository publishes
(a letter of the government as much as a motie or a memorandum). ``kinds`` narrows a run to
the documents whose kind contains one of a few words.
The Tweede Kamer's own API serves only a PDF; the KOOP repository has the same document as
structured XML, filed under its dossier. ``normalize tk-content`` reads the XML from the
raw records.

Flow:
    1. The documents of the graph that are numbered in a dossier and have no raw XML yet
       (``_gaps.kamerstuk_gaps``)
    2. Build the identifier ``kst-<dossier>-<number>`` and fetch its XML
    3. Store it unchanged, keyed by the identifier; an answer of HTTP 404 becomes a record
       that says so
    4. Report created / skipped / error counts
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from lawgraph.clients.kamerstuk import KamerstukClient
from lawgraph.config.constants import RAW_KIND_TK_KAMERSTUK_XML, SOURCE_TK
from lawgraph.core.document_completeness import is_fresh
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.retrieve.base import (
    RetrievePipelineBase,
    RetrieveRecord,
    missing_record,
)

logger = get_logger(__name__)

# A document the repository has no XML for yet is asked for again the next night while its XML
# may be on its way (``core.document_completeness.is_fresh``; prod, Oct 2026: 41 of 105 documents
# of a day still had none after three days), not after the month of a document that was never
# there.
_FRESH_RETRY_DAYS = 1


class TKContentRetrievePipeline(RetrievePipelineBase):
    """Fetch the XML of Tweede Kamer documents and store it.

    Only documents numbered in a dossier of which no XML is stored yet are processed; with
    *kinds*, only those whose ``props.kind`` contains one of them (case-insensitive).
    """

    def __init__(
        self,
        *,
        store: GraphStore,
        client: KamerstukClient | None = None,
    ) -> None:
        super().__init__(store)
        self.client = client or KamerstukClient()

    def run(  # type: ignore[override]
        self,
        *,
        kinds: Sequence[str] = (),
        limit: int | None = None,
        dry_run: bool = False,
    ) -> PipelineResult:
        """Fetch the XML of every qualifying document that has none stored.

        Args:
            kinds: Case-insensitive substrings matched against ``props.kind``; none for
                every document.
            limit: At most this many documents; the rest are the gaps of the next run.
            dry_run: When True, log what would happen but make no changes.
        """
        documents = _gaps.kamerstuk_gaps(self.store, kinds)
        if limit:
            documents = _gaps.Gaps.capped(documents, "Kamerstukken without XML", limit)
        which = f" (kind contains one of {list(kinds)})" if kinds else ""
        if not documents:
            logger.info("No papers without XML found%s.", which)
            return PipelineResult()
        logger.info(
            "Fetching the XML of %d papers%s%s.",
            len(documents),
            which,
            " — DRY RUN" if dry_run else "",
        )
        result = self._store_all(
            self._fetch_documents(documents, dry_run), what="papers"
        )
        return _gaps.noted(result, documents)

    def _fetch_documents(
        self, documents: list[dict[str, Any]], dry_run: bool
    ) -> Iterator[RetrieveRecord]:
        if dry_run:
            self.progress.expect(len(documents))
            for document in documents:
                self.progress.skip("dry run", document["identifier"])
            return
        by_id = {document["identifier"]: document for document in documents}
        yield from self._download_each(
            list(by_id),
            self.client.fetch_kamerstuk_xml,
            lambda identifier, xml: [
                RetrieveRecord(
                    source=SOURCE_TK,
                    kind=RAW_KIND_TK_KAMERSTUK_XML,
                    external_id=identifier,
                    payload_text=xml,
                    meta={"document": by_id[identifier]["key"]},
                )
            ],
            label="Kamerstuk XML",
            missing=lambda identifier, status: missing_record(
                SOURCE_TK,
                RAW_KIND_TK_KAMERSTUK_XML,
                identifier,
                status=status,
                days=(
                    _FRESH_RETRY_DAYS
                    if is_fresh(by_id[identifier].get("date"), dutch_today())
                    else None
                ),
            ),
        )
