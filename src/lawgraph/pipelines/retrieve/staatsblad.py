"""Retrieve pipeline for Dutch Staatsblad publications: the AMvBs the BWB names, and the laws
of the dossiers the graph holds as adopted."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.clients.koop_publications import AMVB, LAW, KoopPublicationClient
from lawgraph.config.constants import (
    RAW_KIND_STAATSBLAD_AMVB,
    RAW_KIND_STAATSBLAD_LAW,
    SOURCE_STAATSBLAD,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.publication_xml import staatsblad_ref_from_bwb_xml
from lawgraph.db import GraphStore, RawSourceWriter
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries import staatsblad_laws as law_queries

from .base import (
    RetrievePipelineBase,
    RetrieveRecord,
    listed,
    missing_record,
)

logger = get_logger(__name__)


class StaatsbladRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for Staatsblad XML documents: AMvBs and laws."""

    def __init__(
        self,
        store: GraphStore,
        client: KoopPublicationClient | None = None,
        laws: KoopPublicationClient | None = None,
    ) -> None:
        super().__init__(store)
        self.client = client or KoopPublicationClient(AMVB)
        self.laws = laws or KoopPublicationClient(LAW)

    def fetch(
        self, *, identifiers: list[str] | None = None, **kwargs: object
    ) -> Iterator[RetrieveRecord]:
        """Yield the XML of each publication as it is downloaded."""
        yield from self._fetch_publications([(None, i) for i in identifiers or []])

    def run_from_bwb_graph(self, store: GraphStore) -> PipelineResult:
        """Retrieve the Staatsblad publications the stored BWB toestand XML refers to.

        Each toestand names the Staatsblad publication it comes from (retrieve bwb keeps it
        in its meta); those not yet in raw_sources are fetched and stored.
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

    def run_laws_of_adopted_dossiers(self, store: GraphStore) -> PipelineResult:
        """Retrieve the laws (``DC.type`` ``Wet``) of the dossiers the graph holds as adopted
        that no instrument is ``LEGISLATED_IN`` yet (``dossiers_awaiting_their_law``): per
        dossier those the SRU lists (``w.behandeldDossier``), not stored yet or changed since.
        ``normalize staatsblad-laws`` reads a law the BWB does not hold from them."""

        def listing() -> Iterator[RetrieveRecord]:
            dossiers = [str(d) for d in law_queries.dossiers_awaiting_their_law(store)]
            listed = {
                law["identifier"]: law
                for dossier in dossiers
                for law in self.laws.search(dossier=dossier)
            }
            identifiers = self._changed(
                SOURCE_STAATSBLAD, RAW_KIND_STAATSBLAD_LAW, listed.values()
            )
            logger.info(
                "Staatsblad laws: %d adopted dossiers without a law in the graph, %d laws "
                "listed for them, %d new or changed.",
                len(dossiers),
                len(listed),
                len(identifiers),
            )
            yield from self._fetch_publications(
                [(None, i) for i in identifiers], kind=RAW_KIND_STAATSBLAD_LAW
            )

        return self._store_all(listing(), what="laws")

    def _fetch_publications(
        self,
        todo: list[tuple[str | None, str]],
        *,
        kind: str = RAW_KIND_STAATSBLAD_AMVB,
    ) -> Iterator[RetrieveRecord]:
        """The XML of each ``(bwb_id, identifier)``, stored as *kind*; a publication without
        XML is skipped.

        A download that fails is skipped too and asked for again the next run: one
        publication the source cannot serve (an HTTP 500) must not fail the step.
        """
        bwb_ids = {identifier: bwb_id for bwb_id, identifier in todo}
        wanted = self._without_missing(SOURCE_STAATSBLAD, kind, bwb_ids)

        def records(identifier: str, xml: str) -> list[RetrieveRecord]:
            meta = {"identifier": identifier}
            if bwb_id := bwb_ids[identifier]:
                meta["bwb_id"] = bwb_id
            return [
                RetrieveRecord(
                    source=SOURCE_STAATSBLAD,
                    kind=kind,
                    external_id=identifier,
                    payload_text=xml,
                    meta=meta,
                )
            ]

        yield from self._download_each(
            wanted,
            self.client.fetch_publication_xml,
            records,
            label="Staatsblad",
            # thousands of old publications have none: spread when they come due
            missing=lambda identifier, status: missing_record(
                SOURCE_STAATSBLAD,
                kind,
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

        Retrieve bwb keeps the publication of each toestand in its meta, so no payload is
        read; a toestand stored without it is read once and gets it (``_fill_refs``). A
        publication several regulations refer to is listed once.
        """
        candidates: dict[str, str] = {}
        without = 0
        rows = [*raw_queries.toestand_staatsblad_refs(store), *self._fill_refs(store)]
        for row in rows:
            if row["ref"] is None:
                without += 1
                continue
            candidates.setdefault(row["ref"], row["bwb_id"])
        return [
            (bwb_id, identifier) for identifier, bwb_id in candidates.items()
        ], without

    def _fill_refs(self, store: GraphStore) -> Iterator[dict[str, Any]]:
        """``{bwb_id, ref}`` of each toestand whose meta lacks the ref, read from its XML (as
        retrieve bwb does) and written into its meta, so the next run reads no payload."""
        records = raw_queries.toestanden_without_staatsblad_ref(store)
        filled = 0
        with RawSourceWriter(store) as writer:
            for record in store.with_payloads(records):
                xml = record.get("payload_text")
                published = staatsblad_ref_from_bwb_xml(xml) if xml else None
                ref = f"stb-{published[0]}-{published[1]}" if published else None
                doc = {k: v for k, v in record.items() if k != "id"}
                if doc.get(
                    "payload_ref"
                ):  # read for this run, kept in the payload store
                    doc.pop("payload_text", None)
                doc["meta"] = {**(doc.get("meta") or {}), "staatsblad_ref": ref}
                writer.add(doc)
                filled += 1
                yield {"bwb_id": record["external_id"], "ref": ref}
        if filled:
            logger.info("Staatsblad from-graph: the ref of %d toestanden kept.", filled)

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
        """Full-load mode: every AMvB the SRU lists that is new or modified since stored."""

        def listing() -> Iterator[RetrieveRecord]:
            amvbs = listed(self.client.search(), "Staatsblad AMvBs")
            identifiers = self._changed(
                SOURCE_STAATSBLAD, RAW_KIND_STAATSBLAD_AMVB, amvbs
            )
            logger.info(
                "Staatsblad full-load: %d AMvBs listed, %d new or modified since they "
                "were stored.",
                len(amvbs),
                len(identifiers),
            )
            yield from self._fetch_publications([(None, i) for i in identifiers])

        return self._store_all(listing(), what="publications")
