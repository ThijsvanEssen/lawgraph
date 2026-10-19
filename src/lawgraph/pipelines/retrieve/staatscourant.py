"""Retrieve pipeline for Dutch Staatscourant ministeriele regelingen."""

from __future__ import annotations

from collections.abc import Iterator

from lawgraph.clients.koop_publications import (
    MINISTERIAL_REGULATION,
    KoopPublicationClient,
)
from lawgraph.config.constants import (
    RAW_KIND_STAATSCOURANT_REGELING,
    SOURCE_STAATSCOURANT,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore

from .base import (
    RetrievePipelineBase,
    RetrieveRecord,
    listed,
    missing_record,
)

logger = get_logger(__name__)


class StaatscourantRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for Staatscourant ministeriele regelingen XML documents."""

    def __init__(
        self, store: GraphStore, client: KoopPublicationClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or KoopPublicationClient(MINISTERIAL_REGULATION)

    def fetch(
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
        from_listing = not identifiers
        if from_listing:
            listing = self.client.search(since=since)
            if since is None:
                listed(listing, "Staatscourant ministeriele regelingen")
            # What is stored and not modified since is left alone; that is also what an
            # interrupted run did, so no 24-hour rule here: it would hide a publication that
            # is modified on the day it was stored until it has left the window.
            wanted = self._changed(
                SOURCE_STAATSCOURANT, RAW_KIND_STAATSCOURANT_REGELING, listing
            )
            logger.info(
                "Staatscourant: %d publications listed, %d new or modified since they "
                "were stored.",
                len(listing),
                len(wanted),
            )
        else:
            done = self._recently_stored(
                SOURCE_STAATSCOURANT, RAW_KIND_STAATSCOURANT_REGELING
            )
            wanted = [i for i in identifiers or [] if i not in done]
        # One publication that always answers 500 must not end every run at the same
        # place: the rest is fetched, and a dead source ends the step.
        yield from self._download_each(
            self._without_missing(
                SOURCE_STAATSCOURANT, RAW_KIND_STAATSCOURANT_REGELING, wanted
            ),
            self.client.fetch_publication_xml,
            lambda identifier, xml: [
                RetrieveRecord(
                    source=SOURCE_STAATSCOURANT,
                    kind=RAW_KIND_STAATSCOURANT_REGELING,
                    external_id=identifier,
                    payload_text=xml,
                    meta={"identifier": identifier},
                )
            ],
            label="Staatscourant",
            missing=lambda identifier, status: missing_record(
                SOURCE_STAATSCOURANT,
                RAW_KIND_STAATSCOURANT_REGELING,
                identifier,
                listed=from_listing,
                status=status,
            ),
        )

    def run_full(self) -> PipelineResult:
        """Enumerate all ministeriele regelingen via SRU and fetch them."""
        return self.run(since=None)
