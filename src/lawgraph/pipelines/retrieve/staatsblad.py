"""Retrieve pipeline for Dutch Staatsblad AMvB publications."""

from __future__ import annotations

from lawgraph.clients.staatsblad import StaatsbladClient
from lawgraph.config.settings import RAW_KIND_STB_AMVB, SOURCE_STAATSBLAD
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import PipelineResult

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

        # Get all BWB IDs from instruments
        aql_instruments = """
        FOR inst IN instruments
          FILTER inst.props.bwb_id != null
          RETURN { bwb_id: inst.props.bwb_id, key: inst._key }
        """
        try:
            instrument_rows = list(store.query(aql_instruments))
        except Exception as exc:
            msg = f"Could not query instruments for Staatsblad retrieval: {exc}"
            logger.error(msg)
            result.add_error(msg)
            return result

        logger.info(
            "Staatsblad from-graph: examining %d instruments for Staatsblad refs.",
            len(instrument_rows),
        )

        for row in instrument_rows:
            bwb_id = row.get("bwb_id")
            if not bwb_id:
                continue

            # Look up the BWB raw_source XML
            aql_raw = """
            FOR r IN raw_sources
              FILTER r.source == 'bwb' AND r.external_id == @bwb_id
              LIMIT 1
              RETURN r.payload_text
            """
            try:
                raw_rows = list(store.query(aql_raw, bind_vars={"bwb_id": bwb_id}))
            except Exception as exc:
                logger.debug("Could not look up BWB raw_source for %s: %s", bwb_id, exc)
                continue

            if not raw_rows:
                result.skipped += 1
                continue

            bwb_xml = raw_rows[0]
            if not isinstance(bwb_xml, str):
                result.skipped += 1
                continue

            ref = StaatsbladClient.extract_staatsblad_ref_from_bwb_xml(bwb_xml)
            if not ref:
                result.skipped += 1
                continue

            year, number = ref
            identifier = f"stb-{year}-{number}"

            # Check if already in raw_sources
            aql_exists = """
            FOR r IN raw_sources
              FILTER r.source == @source AND r.external_id == @ext_id
              LIMIT 1
              RETURN 1
            """
            try:
                exists = list(
                    store.query(
                        aql_exists,
                        bind_vars={"source": SOURCE_STAATSBLAD, "ext_id": identifier},
                    )
                )
                if exists:
                    result.skipped += 1
                    continue
            except Exception:
                pass

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

        logger.info("Staatsblad from-graph: %s.", result.summary())
        return result

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
