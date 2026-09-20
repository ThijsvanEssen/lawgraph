from __future__ import annotations

from collections.abc import Sequence

from lawgraph.clients.bwb import BWBClient, ToestandMeta
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_BWB_WTI_GENERAL,
    SOURCE_BWB,
)
from lawgraph.core.identifiers import clean_ids
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class BWBRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline that fetches BWB toestanden and WTI general information."""

    def __init__(
        self,
        store: ArangoStore,
        client: BWBClient | None = None,
    ) -> None:
        super().__init__(store)
        self.client = client or BWBClient()

    def run(
        self,
        *,
        bwb_ids: Sequence[str] | None = None,
        **kwargs: object,
    ) -> PipelineResult:
        """Fetch and store the current toestand and the WTI general information per ID."""
        normalized = clean_ids(bwb_ids)
        result = PipelineResult()

        if not normalized:
            logger.warning("BWB retrieve: no IDs to process.")
            return result

        done = self._recently_stored(SOURCE_BWB, RAW_KIND_BWB_TOESTAND)
        logger.info(
            "Starting BWB retrieve for %d IDs (%d already stored in the last 24 hours).",
            len(normalized),
            len(done),
        )

        for bwb_id in normalized:
            if bwb_id in done:
                continue
            try:
                meta = self.client.latest_toestand(bwb_id)
            except Exception as exc:
                msg = f"Could not fetch toestand metadata for {bwb_id}: {exc}"
                logger.error(msg)
                result.add_error(msg)
                result.skipped += 1
                continue

            if meta is None:
                logger.debug("No toestand found for %s; skipping.", bwb_id)
                result.skipped += 1
                continue

            try:
                xml_text = self.client.fetch_toestand_xml(meta)
            except Exception as exc:
                msg = f"Could not download toestand XML for {bwb_id}: {exc}"
                logger.error(msg)
                result.add_error(msg)
                result.skipped += 1
                continue

            record = RetrieveRecord(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND,
                external_id=bwb_id,
                payload_text=xml_text,
                meta={
                    "bwb_id": bwb_id,
                    "state_url": meta["locatie_toestand"],
                    "start_date": meta.get("geldigheidsperiode_startdatum"),
                    "end_date": meta.get("geldigheidsperiode_einddatum"),
                },
            )

            try:
                self._insert(record)
                result.created += 1
            except Exception as exc:
                msg = f"Could not store raw_source for {bwb_id}: {exc}"
                logger.error(msg)
                result.add_error(msg)
                result.skipped += 1

            self._store_wti_general_info(meta, result)

        logger.info(
            "BWB retrieve completed: %d stored, %d skipped, %d errors.",
            result.created,
            result.skipped,
            len(result.errors),
        )
        return result

    def _store_wti_general_info(
        self, meta: ToestandMeta, result: PipelineResult
    ) -> None:
        """Store the WTI general information (official abbreviations) of one regulation.

        A failure is reported but leaves the stored toestand alone.
        """
        bwb_id = meta["bwb_id"]
        try:
            general_info = self.client.fetch_wti_general_info(meta)
            if general_info is None:
                logger.debug("No WTI general information for %s.", bwb_id)
                return
            self._insert(
                RetrieveRecord(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_WTI_GENERAL,
                    external_id=bwb_id,
                    payload_text=general_info,
                    meta={"bwb_id": bwb_id, "wti_url": meta.get("locatie_wti")},
                )
            )
            result.created += 1
        except Exception as exc:
            msg = (
                f"Could not fetch or store WTI general information for {bwb_id}: {exc}"
            )
            logger.error(msg)
            result.add_error(msg)

    def run_history(
        self,
        *,
        bwb_ids: Sequence[str] | None = None,
        **kwargs: object,
    ) -> PipelineResult:
        """Fetch and store ALL historical BWB toestanden for given IDs.

        Each historical version is stored as a separate raw_source record keyed
        by ``{bwb_id}@{start_date}``.  Safe to re-run — ``_insert`` is
        upsert-based.
        """
        normalized = clean_ids(bwb_ids)
        result = PipelineResult()

        if not normalized:
            logger.warning("BWB history retrieve: no IDs to process.")
            return result

        logger.info("Starting BWB history retrieve for %d IDs.", len(normalized))

        for bwb_id in normalized:
            try:
                toestanden = self.client.search_toestanden(bwb_id)
            except Exception as exc:
                msg = f"Could not fetch toestanden list for {bwb_id}: {exc}"
                logger.error(msg)
                result.add_error(msg)
                result.skipped += 1
                continue

            if not toestanden:
                logger.debug("No toestanden found for %s; skipping.", bwb_id)
                result.skipped += 1
                continue

            logger.debug("Found %d toestanden for %s.", len(toestanden), bwb_id)

            for meta in toestanden:
                start_date = meta.get("geldigheidsperiode_startdatum") or "unknown"
                end_date = meta.get("geldigheidsperiode_einddatum")
                external_id = f"{bwb_id}@{start_date}"

                try:
                    xml_text = self.client.fetch_toestand_xml(meta)
                except Exception as exc:
                    msg = f"Could not download toestand XML for {external_id}: {exc}"
                    logger.error(msg)
                    result.add_error(msg)
                    result.skipped += 1
                    continue

                record = RetrieveRecord(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND_ALL,
                    external_id=external_id,
                    payload_text=xml_text,
                    meta={
                        "bwb_id": bwb_id,
                        "state_url": meta["locatie_toestand"],
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                )

                try:
                    self._insert(record)
                    result.created += 1
                except Exception as exc:
                    msg = f"Could not store raw_source for {external_id}: {exc}"
                    logger.error(msg)
                    result.add_error(msg)
                    result.skipped += 1

        logger.info(
            "BWB history retrieve completed: %d stored, %d skipped, %d errors.",
            result.created,
            result.skipped,
            len(result.errors),
        )
        return result

    def run_history_full(self) -> PipelineResult:
        """Full-load mode: enumerate ALL BWB laws via SRU wildcard, then fetch all toestanden.

        Uses ``BWBClient.enumerate_all_ids()`` to discover every BWBR ID
        registered in the SRU catalogue, then calls ``run_history(bwb_ids=...)``
        to fetch all historical versions.  Safe to interrupt and re-run.
        """
        logger.info("BWB history full-load: enumerating all BWBR IDs via SRU wildcard.")
        try:
            all_ids = self.client.enumerate_all_ids()
        except Exception as exc:
            result = PipelineResult()
            msg = f"BWB SRU enumeration failed: {exc}"
            logger.error(msg)
            result.add_error(msg)
            return result

        logger.info(
            "BWB history full-load: %d IDs found; starting retrieval.", len(all_ids)
        )
        return self.run_history(bwb_ids=all_ids)

    def run_full(self) -> PipelineResult:
        """Full-load mode: enumerate ALL BWB laws via SRU wildcard, then fetch each.

        Uses ``BWBClient.enumerate_all_ids()`` to discover every BWBR ID
        registered in the SRU catalogue, then calls ``run(bwb_ids=...)`` to
        fetch and store each toestand. Safe to interrupt and re-run — the
        upsert pattern ensures idempotency.
        """
        logger.info("BWB full-load: enumerating all BWBR IDs via SRU wildcard.")
        try:
            all_ids = self.client.enumerate_all_ids()
        except Exception as exc:
            result = PipelineResult()
            msg = f"BWB SRU enumeration failed: {exc}"
            logger.error(msg)
            result.add_error(msg)
            return result

        logger.info("BWB full-load: %d IDs found; starting retrieval.", len(all_ids))
        return self.run(bwb_ids=all_ids)
