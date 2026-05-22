"""Retrieve pipeline for Dutch Staatscourant ministeriele regelingen."""

from __future__ import annotations

from lawgraph.clients.staatscourant import StaatscourantClient
from lawgraph.config.constants import RAW_KIND_STCRT_REGELING, SOURCE_STAATSCOURANT
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class StaatscourantRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for Staatscourant ministeriele regelingen XML documents."""

    def __init__(
        self, store: ArangoStore, client: StaatscourantClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or StaatscourantClient()

    def fetch(
        self,
        *,
        identifiers: list[str] | None = None,
        **kwargs,
    ) -> list[RetrieveRecord]:
        records: list[RetrieveRecord] = []
        if not identifiers:
            return records

        for identifier in identifiers:
            xml = self.client.fetch_publication_xml(identifier)
            if xml is None:
                logger.warning("Skipping Staatscourant %s: XML not found.", identifier)
                continue
            records.append(
                RetrieveRecord(
                    source=SOURCE_STAATSCOURANT,
                    kind=RAW_KIND_STCRT_REGELING,
                    external_id=identifier,
                    payload_text=xml,
                    meta={"identifier": identifier},
                )
            )

        logger.info(
            "Staatscourant retrieve: fetched %d/%d records.",
            len(records),
            len(identifiers) if identifiers else 0,
        )
        return records

    def run(
        self,
        *,
        identifiers: list[str] | None = None,
        since: str | None = None,
        **kwargs,
    ) -> PipelineResult:
        result = PipelineResult()

        if not identifiers:
            # Search SRU for identifiers
            search_results = self.client.search_ministeriele_regelingen(since=since)
            identifiers = [
                r["identifier"] for r in search_results if r.get("identifier")
            ]

        if not identifiers:
            return result

        records = self.fetch(identifiers=identifiers)
        for record in records:
            try:
                self._insert(record)
                result.created += 1
            except Exception as exc:
                msg = f"Failed to store Staatscourant {record.external_id}: {exc}"
                logger.error(msg)
                result.add_error(msg)
                result.skipped += 1

        return result

    def run_full(self) -> PipelineResult:
        """Enumerate all ministeriele regelingen via SRU and fetch them."""
        return self.run(since=None)
