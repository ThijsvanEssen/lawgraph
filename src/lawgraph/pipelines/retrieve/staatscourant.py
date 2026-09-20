"""Retrieve pipeline for Dutch Staatscourant ministeriele regelingen."""

from __future__ import annotations

from collections.abc import Iterator

from lawgraph.clients.staatscourant import StaatscourantClient
from lawgraph.config.constants import RAW_KIND_STCRT_REGELING, SOURCE_STAATSCOURANT
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord, missing_record

logger = get_logger(__name__)


class StaatscourantRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for Staatscourant ministeriele regelingen XML documents."""

    def __init__(
        self, store: ArangoStore, client: StaatscourantClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or StaatscourantClient()

    def fetch(  # type: ignore[override]
        self,
        *,
        identifiers: list[str] | None = None,
        since: str | None = None,
        **kwargs: object,
    ) -> Iterator[RetrieveRecord]:
        """Yield the XML of each publication as it is downloaded.

        Without *identifiers* the SRU lists them (``since`` on ``dt.modified``), and what is
        stored and not modified since is left alone. Those stored in the last 24 hours are
        skipped: they were done by an interrupted run.
        """
        if not identifiers:
            listed = self.client.search_ministeriele_regelingen(since=since)
            identifiers = self._changed(
                SOURCE_STAATSCOURANT, RAW_KIND_STCRT_REGELING, listed
            )
            logger.info(
                "Staatscourant: %d publications listed, %d new or modified since they "
                "were stored.",
                len(listed),
                len(identifiers),
            )
        done = self._recently_stored(SOURCE_STAATSCOURANT, RAW_KIND_STCRT_REGELING)
        todo = self._without_missing(
            SOURCE_STAATSCOURANT,
            RAW_KIND_STCRT_REGELING,
            [i for i in identifiers if i not in done],
        )
        logger.info(
            "Staatscourant retrieve: %d publications, %d to download.",
            len(identifiers),
            len(todo),
        )
        self.progress.expect(len(todo))
        for identifier in todo:
            xml = self.client.fetch_publication_xml(identifier)
            if xml is None:
                self.progress.skip("no XML (HTTP 404)", identifier)
                yield missing_record(
                    SOURCE_STAATSCOURANT, RAW_KIND_STCRT_REGELING, identifier
                )
                continue
            yield RetrieveRecord(
                source=SOURCE_STAATSCOURANT,
                kind=RAW_KIND_STCRT_REGELING,
                external_id=identifier,
                payload_text=xml,
                meta={"identifier": identifier},
            )

    def run_full(self) -> PipelineResult:
        """Enumerate all ministeriele regelingen via SRU and fetch them."""
        return self.run(since=None)
