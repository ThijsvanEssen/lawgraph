"""Retrieve pipeline for Dutch Staatsblad AMvB publications."""

from __future__ import annotations

from collections.abc import Iterator

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

from .base import RetrievePipelineBase, RetrieveRecord, missing_record

logger = get_logger(__name__)


class StaatsbladRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for Staatsblad AMvB XML documents."""

    def __init__(
        self, store: ArangoStore, client: StaatsbladClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or StaatsbladClient()

    def fetch(  # type: ignore[override]
        self, *, identifiers: list[str] | None = None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        """Yield the XML of each publication as it is downloaded."""
        yield from self._fetch_publications([(None, i) for i in identifiers or []])

    def run_from_bwb_graph(self, store: ArangoStore) -> PipelineResult:
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
        """The XML of each ``(bwb_id, identifier)``; a publication without XML is skipped."""
        wanted = set(
            self._without_missing(
                SOURCE_STAATSBLAD, RAW_KIND_STB_AMVB, [i for _, i in todo]
            )
        )
        todo = [
            (bwb_id, identifier) for bwb_id, identifier in todo if identifier in wanted
        ]
        self.progress.expect(len(todo))
        for bwb_id, identifier in todo:
            xml = self.client.fetch_publication_xml(identifier)
            if xml is None:
                self.progress.skip("no XML (HTTP 404)", identifier)
                yield missing_record(SOURCE_STAATSBLAD, RAW_KIND_STB_AMVB, identifier)
                continue
            meta = {"identifier": identifier}
            if bwb_id:
                meta["bwb_id"] = bwb_id
            yield RetrieveRecord(
                source=SOURCE_STAATSBLAD,
                kind=RAW_KIND_STB_AMVB,
                external_id=identifier,
                payload_text=xml,
                meta=meta,
            )

    def _candidates_from_bwb(
        self, store: ArangoStore
    ) -> tuple[list[tuple[str | None, str]], int]:
        """``(bwb_id, identifier)`` per referred publication, and how many toestanden name none.

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
        without = 0
        rows = store.query(
            aql,
            bind_vars={"source": SOURCE_BWB, "kind": RAW_KIND_BWB_TOESTAND},
            batch_size=50,
        )
        for row in rows:
            ref = staatsblad_ref_from_bwb_xml(row["xml"]) if row.get("xml") else None
            if ref is None:
                without += 1
                continue
            candidates.setdefault(f"stb-{ref[0]}-{ref[1]}", row["bwb_id"])
        return [
            (bwb_id, identifier) for identifier, bwb_id in candidates.items()
        ], without

    def _find_existing_identifiers(
        self, store: ArangoStore, candidates: list[tuple[str | None, str]]
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
