"""Retrieve pipeline for Dutch Staatsblad AMvB publications."""

from __future__ import annotations

from lawgraph.clients.staatsblad import StaatsbladClient
from lawgraph.config.constants import RAW_KIND_STB_AMVB, SOURCE_BWB, SOURCE_STAATSBLAD
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
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
        """Retrieve Staatsblad publications referenced from BWB instruments in the graph.

        For each BWB instrument, looks up the raw BWB XML and extracts the Staatsblad
        identifier from the XML. Fetches and stores any that are not yet in raw_sources.
        """
        result = PipelineResult()

        instrument_rows, error = self._get_bwb_instrument_rows(store)
        if error:
            result.add_error(error)
            return result

        logger.info(
            "Staatsblad from-graph: examining %d BWB raw_sources for Staatsblad refs.",
            len(instrument_rows),
        )

        bwb_xml_by_id = self._fetch_bwb_xml_batch(store, instrument_rows)
        candidate_refs = self._extract_stb_candidates(instrument_rows, bwb_xml_by_id, result)
        existing_identifiers = self._find_existing_identifiers(store, candidate_refs)
        self._fetch_and_store(result, candidate_refs, existing_identifiers)

        logger.info("Staatsblad from-graph: %s.", result.summary())
        return result

    def _get_bwb_instrument_rows(
        self, store: ArangoStore
    ) -> tuple[list[dict], str | None]:
        """Query raw_sources for all BWB instrument IDs. Returns (rows, error_msg)."""
        aql = """
        FOR r IN raw_sources
          FILTER r.source == @source AND r.external_id != null
          RETURN { bwb_id: r.external_id }
        """
        try:
            rows = list(store.query(aql, bind_vars={"source": SOURCE_BWB}))
            return rows, None
        except Exception as exc:
            msg = f"Could not query BWB raw_sources for Staatsblad retrieval: {exc}"
            logger.error(msg)
            return [], msg

    def _fetch_bwb_xml_batch(
        self, store: ArangoStore, instrument_rows: list[dict]
    ) -> dict[str, str]:
        """Bulk-fetch BWB raw XML for all instrument rows. Returns bwb_id → xml map."""
        bwb_ids = [row["bwb_id"] for row in instrument_rows if row.get("bwb_id")]
        bwb_xml_by_id: dict[str, str] = {}
        if not bwb_ids:
            return bwb_xml_by_id

        aql = """
        FOR r IN raw_sources
          FILTER r.source == 'bwb' AND r.external_id IN @bwb_ids
          RETURN { bwb_id: r.external_id, payload_text: r.payload_text }
        """
        try:
            for raw_row in store.query(aql, bind_vars={"bwb_ids": bwb_ids}):
                bid = raw_row.get("bwb_id")
                txt = raw_row.get("payload_text")
                if bid and isinstance(txt, str):
                    bwb_xml_by_id[bid] = txt
        except Exception as exc:
            logger.debug("Could not bulk-fetch BWB raw_sources: %s", exc)

        return bwb_xml_by_id

    def _extract_stb_candidates(
        self,
        instrument_rows: list[dict],
        bwb_xml_by_id: dict[str, str],
        result: PipelineResult,
    ) -> list[tuple[str, str, str]]:
        """Resolve Staatsblad identifiers from BWB XML.

        Returns (bwb_id, identifier, xml) triples.
        """
        candidate_refs: list[tuple[str, str, str]] = []
        for row in instrument_rows:
            bwb_id = row.get("bwb_id")
            if not bwb_id:
                continue
            bwb_xml = bwb_xml_by_id.get(bwb_id)
            if not bwb_xml:
                result.skipped += 1
                continue
            ref = StaatsbladClient.extract_staatsblad_ref_from_bwb_xml(bwb_xml)
            if not ref:
                result.skipped += 1
                continue
            year, number = ref
            identifier = f"stb-{year}-{number}"
            candidate_refs.append((bwb_id, identifier, bwb_xml))
        return candidate_refs

    def _find_existing_identifiers(
        self,
        store: ArangoStore,
        candidate_refs: list[tuple[str, str, str]],
    ) -> set[str]:
        """Bulk-check which candidate Staatsblad identifiers are already in raw_sources."""
        existing: set[str] = set()
        if not candidate_refs:
            return existing

        candidate_ids = list({identifier for _, identifier, _ in candidate_refs})
        aql = """
        FOR r IN raw_sources
          FILTER r.source == @source AND r.external_id IN @ext_ids
          RETURN r.external_id
        """
        try:
            for ext_id in store.query(
                aql,
                bind_vars={"source": SOURCE_STAATSBLAD, "ext_ids": candidate_ids},
            ):
                if isinstance(ext_id, str):
                    existing.add(ext_id)
        except Exception as exc:
            logger.debug("Staatsblad bulk existence check failed: %s", exc)

        return existing

    def _fetch_and_store(
        self,
        result: PipelineResult,
        candidate_refs: list[tuple[str, str, str]],
        existing_identifiers: set[str],
    ) -> None:
        """Fetch XML and store records for candidates not already present in raw_sources."""
        for bwb_id, identifier, _bwb_xml in candidate_refs:
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
