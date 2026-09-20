"""Retrieve pipeline for Dutch Staatsblad AMvB publications."""

from __future__ import annotations

from lawgraph.clients.staatsblad import StaatsbladClient
from lawgraph.config.constants import (
    COLLECTION_RAW_SOURCES,
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_STB_AMVB,
    SOURCE_BWB,
    SOURCE_STAATSBLAD,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.publication_xml import staatsblad_ref_from_bwb_xml
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class StaatsbladRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for Staatsblad AMvB XML documents."""

    def __init__(
        self, store: ArangoStore, client: StaatsbladClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or StaatsbladClient()

    def fetch(
        self, *, identifiers: list[str] | None = None, **kwargs
    ) -> list[RetrieveRecord]:
        """Fetch Staatsblad XML for the given identifiers."""
        records: list[RetrieveRecord] = []
        if not identifiers:
            return records

        for identifier in identifiers:
            xml = self.client.fetch_publication_xml(identifier)
            if xml is None:
                logger.warning("Skipping Staatsblad %s: XML not found.", identifier)
                continue
            records.append(
                RetrieveRecord(
                    source=SOURCE_STAATSBLAD,
                    kind=RAW_KIND_STB_AMVB,
                    external_id=identifier,
                    payload_text=xml,
                    meta={"identifier": identifier},
                )
            )

        logger.info(
            "Staatsblad retrieve: fetched %d/%d records.",
            len(records),
            len(identifiers) if identifiers else 0,
        )
        return records

    def run(self, *, identifiers: list[str] | None = None, **kwargs) -> PipelineResult:
        """Fetch records for the given identifiers and store them."""
        result = PipelineResult()
        if not identifiers:
            return result

        records = self.fetch(identifiers=identifiers)
        for record in records:
            try:
                self._insert(record)
                result.created += 1
            except Exception as exc:
                msg = f"Failed to store Staatsblad {record.external_id}: {exc}"
                logger.error(msg)
                result.add_error(msg)
                result.skipped += 1

        return result

    def run_from_bwb_graph(self, store: ArangoStore) -> PipelineResult:
        """Retrieve the Staatsblad publications the stored BWB toestand XML refers to.

        Each toestand XML names the Staatsblad publication (year and number) it comes
        from; those not yet in raw_sources are fetched and stored one by one.
        """
        result = PipelineResult()
        candidates = self._candidates_from_bwb(store, result)
        logger.info(
            "Staatsblad from-graph: %d publications referred to by BWB toestanden "
            "(%d toestanden refer to none).",
            len(candidates),
            result.skipped,
        )
        existing = self._find_existing_identifiers(store, candidates)
        self._fetch_and_store(result, candidates, existing)
        logger.info("Staatsblad from-graph: %s.", result.summary())
        return result

    def _candidates_from_bwb(
        self, store: ArangoStore, result: PipelineResult
    ) -> list[tuple[str, str]]:
        """``(bwb_id, identifier)`` per referred publication, from the stored toestand XML.

        The toestand XML is streamed and only the identifiers are kept: a toestand is
        tens of KB and there are over ten thousand. The WTI records of the same regulation
        hold no publication and are not read. A publication several regulations refer to is
        listed once.
        """
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
          FILTER r.source == @source AND r.kind == @kind AND r.external_id != null
          RETURN {{ bwb_id: r.external_id, xml: r.payload_text }}
        """
        candidates: dict[str, str] = {}
        rows = store.query(
            aql,
            bind_vars={"source": SOURCE_BWB, "kind": RAW_KIND_BWB_TOESTAND},
            batch_size=50,
        )
        for row in rows:
            ref = staatsblad_ref_from_bwb_xml(row["xml"]) if row.get("xml") else None
            if ref is None:
                result.skipped += 1
                continue
            candidates.setdefault(f"stb-{ref[0]}-{ref[1]}", row["bwb_id"])
        return [(bwb_id, identifier) for identifier, bwb_id in candidates.items()]

    def _find_existing_identifiers(
        self, store: ArangoStore, candidates: list[tuple[str, str]]
    ) -> set[str]:
        """Which candidate Staatsblad identifiers are already in raw_sources."""
        if not candidates:
            return set()
        aql = f"""
        FOR r IN {COLLECTION_RAW_SOURCES}
          FILTER r.source == @source AND r.kind == @kind AND r.external_id IN @ext_ids
          RETURN r.external_id
        """
        rows = store.query(
            aql,
            bind_vars={
                "source": SOURCE_STAATSBLAD,
                "kind": RAW_KIND_STB_AMVB,
                "ext_ids": [identifier for _, identifier in candidates],
            },
        )
        return {row for row in rows if isinstance(row, str)}

    def _fetch_and_store(
        self,
        result: PipelineResult,
        candidates: list[tuple[str, str]],
        existing_identifiers: set[str],
    ) -> None:
        """Fetch XML and store records for candidates not already present in raw_sources."""
        for bwb_id, identifier in candidates:
            if identifier in existing_identifiers:
                result.skipped += 1
                continue

            xml = self.client.fetch_publication_xml(identifier)
            if xml is None:
                logger.debug(
                    "Staatsblad XML not found for %s (bwb_id=%s)", identifier, bwb_id
                )
                result.skipped += 1
                continue

            record = RetrieveRecord(
                source=SOURCE_STAATSBLAD,
                kind=RAW_KIND_STB_AMVB,
                external_id=identifier,
                payload_text=xml,
                meta={"identifier": identifier, "bwb_id": bwb_id},
            )
            try:
                self._insert(record)
                result.created += 1
            except Exception as exc:
                msg = f"Failed to store Staatsblad {identifier}: {exc}"
                logger.error(msg)
                result.add_error(msg)
                result.skipped += 1

    def run_full(self) -> PipelineResult:
        """Full-load mode: enumerate all AMvBs via SRU and fetch each."""
        logger.info("Staatsblad full-load: searching for all AMvBs via SRU.")
        try:
            amvbs = self.client.search_amvbs()
        except Exception as exc:
            result = PipelineResult()
            msg = f"Staatsblad SRU search failed: {exc}"
            logger.error(msg)
            result.add_error(msg)
            return result

        identifiers = [r["identifier"] for r in amvbs]
        logger.info(
            "Staatsblad full-load: %d AMvB identifiers found.", len(identifiers)
        )
        return self.run(identifiers=identifiers)
