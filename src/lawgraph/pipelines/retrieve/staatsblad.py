"""Retrieve pipeline for Dutch Staatsblad AMvB publications."""

from __future__ import annotations

from collections.abc import Iterator

from lawgraph.clients.staatsblad import StaatsbladClient
from lawgraph.config.constants import (
    RAW_KIND_STB_AMVB,
    SOURCE_STAATSBLAD,
)
from lawgraph.core.logging import describe, get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.publication_xml import staatsblad_ref_from_bwb_xml
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries

from .base import (
    RetrievePipelineBase,
    RetrieveRecord,
    missing_record,
)

logger = get_logger(__name__)


class StaatsbladRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for Staatsblad AMvB XML documents."""

    def __init__(
        self, store: GraphStore, client: StaatsbladClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or StaatsbladClient()

    def fetch(  # type: ignore[override]
        self, *, identifiers: list[str] | None = None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        """Yield the XML of each publication as it is downloaded."""
        yield from self._fetch_publications([(None, i) for i in identifiers or []])

    def run_from_bwb_graph(self, store: GraphStore) -> PipelineResult:
        """Retrieve the Staatsblad publications the stored BWB toestand XML refers to.

        Each toestand XML names the Staatsblad publication (year and number) it comes
        from; those not yet in raw_sources are fetched and stored.
        """
        candidates, without = self._candidates_from_bwb(store)
        existing = self._find_existing_identifiers(store, candidates)
        todo = [c for c in candidates if c[1] not in existing]
        logger.info(
            "Staatsblad from-graph: %d publications referred to by BWB toestanden, %d "
            "already stored (%d toestanden refer to none).",
            len(candidates),
            len(candidates) - len(todo),
            without,
        )
        result = self._store_all(self._fetch_publications(todo), what="publications")
        result.skipped += without + len(candidates) - len(todo)
        return result

    def _fetch_publications(
        self, todo: list[tuple[str | None, str]]
    ) -> Iterator[RetrieveRecord]:
        """The XML of each ``(bwb_id, identifier)``; a publication without XML is skipped.

        A download that fails is skipped too and asked for again the next run: one
        publication the source cannot serve (an HTTP 500) must not fail the step.
        """
        bwb_ids = {identifier: bwb_id for bwb_id, identifier in todo}
        wanted = self._without_missing(SOURCE_STAATSBLAD, RAW_KIND_STB_AMVB, bwb_ids)
        self.progress.expect(len(wanted))

        def records(identifier: str, xml: str) -> list[RetrieveRecord]:
            meta = {"identifier": identifier}
            if bwb_id := bwb_ids[identifier]:
                meta["bwb_id"] = bwb_id
            return [
                RetrieveRecord(
                    source=SOURCE_STAATSBLAD,
                    kind=RAW_KIND_STB_AMVB,
                    external_id=identifier,
                    payload_text=xml,
                    meta=meta,
                )
            ]

        yield from self._download_each(
            wanted,
            self.client.fetch_publication_xml,
            records,
            source="Staatsblad",
            # thousands of old publications have none: spread when they come due
            missing=lambda identifier, status: missing_record(
                SOURCE_STAATSBLAD,
                RAW_KIND_STB_AMVB,
                identifier,
                status=status,
                spread=True,
            ),
            failed_is_skipped=True,
        )

    def _candidates_from_bwb(
        self, store: GraphStore
    ) -> tuple[list[tuple[str | None, str]], int]:
        """``(bwb_id, identifier)`` per referred publication, and how many toestanden name none.

        The toestand XML is streamed and only the identifiers are kept: a toestand is
        tens of KB and there are over ten thousand. The WTI records of the same regulation
        hold no publication and are not read. A publication several regulations refer to is
        listed once.
        """
        candidates: dict[str, str] = {}
        without = 0
        rows = raw_queries.toestand_payload_refs(store)
        for row in store.with_payloads(rows):
            xml = row.get("payload_text")
            ref = staatsblad_ref_from_bwb_xml(xml) if xml else None
            if ref is None:
                without += 1
                continue
            candidates.setdefault(f"stb-{ref[0]}-{ref[1]}", row["bwb_id"])
        return [
            (bwb_id, identifier) for identifier, bwb_id in candidates.items()
        ], without

    def _find_existing_identifiers(
        self, store: GraphStore, candidates: list[tuple[str | None, str]]
    ) -> set[str]:
        """Which candidate Staatsblad identifiers are already in raw_sources."""
        if not candidates:
            return set()
        rows = raw_queries.stored_staatsblad_ids(
            store, [identifier for _, identifier in candidates]
        )
        return {row for row in rows if isinstance(row, str)}

    def run_full(self) -> PipelineResult:
        """Full-load mode: enumerate all AMvBs via SRU and fetch each."""
        logger.info("Staatsblad full-load: searching for all AMvBs via SRU.")
        try:
            amvbs = self.client.search_amvbs()
        except Exception as exc:  # noqa: BLE001 — a listing that fails is the step's error
            result = PipelineResult()
            msg = f"Staatsblad SRU search failed: {describe(exc)}"
            logger.error(msg, exc_info=True)
            result.add_error(msg)
            return result

        if not amvbs:
            result = PipelineResult()
            result.add_error("The Staatsblad listing is empty; nothing was retrieved.")
            return result
        identifiers = self._changed(SOURCE_STAATSBLAD, RAW_KIND_STB_AMVB, amvbs)
        logger.info(
            "Staatsblad full-load: %d AMvBs listed, %d new or modified since they were "
            "stored.",
            len(amvbs),
            len(identifiers),
        )
        if not identifiers:
            return PipelineResult()
        return self.run(identifiers=identifiers)
