from __future__ import annotations

from collections.abc import Sequence

from lawgraph.clients.bwb import BWBClient
from lawgraph.config.settings import RAW_KIND_BWB_TOESTAND, SOURCE_BWB
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import PipelineResult

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)

NormalizedBWBID = str


class BWBRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline that fetches BWB toestanden for configured IDs."""

    def __init__(
        self,
        store: ArangoStore,
        client: BWBClient | None = None,
    ) -> None:
        super().__init__(store)
        self.client = client or BWBClient()

    def run(
        self,
        *args: object,
        bwb_ids: Sequence[NormalizedBWBID] | None = None,
        **kwargs: object,
    ) -> PipelineResult:
        """Fetch and store BWB toestanden with per-ID error handling."""
        normalized = self._normalize_ids(bwb_ids)
        result = PipelineResult()

        if not normalized:
            logger.warning("BWB retrieve: no IDs to process.")
            return result

        logger.info("Starting BWB retrieve for %d IDs.", len(normalized))

        for bwb_id in normalized:
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
                    "toestand_url": meta["locatie_toestand"],
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

        logger.info(
            "BWB retrieve completed: %d stored, %d skipped, %d errors.",
            result.created,
            result.skipped,
            len(result.errors),
        )
        return result

    def fetch(
        self,
        *args: object,
        bwb_ids: Sequence[NormalizedBWBID] | None = None,
        **kwargs: object,
    ) -> Sequence[RetrieveRecord]:
        """Return RetrieveRecords for each BWB ID without storing them."""
        normalized = self._normalize_ids(bwb_ids)
        records: list[RetrieveRecord] = []

        for bwb_id in normalized:
            meta = self.client.latest_toestand(bwb_id)
            if meta is None:
                continue
            xml_text = self.client.fetch_toestand_xml(meta)
            records.append(
                RetrieveRecord(
                    source=SOURCE_BWB,
                    kind=RAW_KIND_BWB_TOESTAND,
                    external_id=bwb_id,
                    payload_text=xml_text,
                    meta={
                        "bwb_id": bwb_id,
                        "toestand_url": meta["locatie_toestand"],
                        "start_date": meta.get("geldigheidsperiode_startdatum"),
                        "end_date": meta.get("geldigheidsperiode_einddatum"),
                    },
                )
            )

        return records

    @staticmethod
    def _normalize_ids(ids: Sequence[str] | None) -> Sequence[NormalizedBWBID]:
        """Clean incoming BWBR IDs, preserving order while removing duplicates."""
        if not ids:
            return []
        cleaned: list[str] = []
        for value in ids:
            if not value:
                continue
            candidate = value.strip()
            if candidate:
                cleaned.append(candidate)
        return list(dict.fromkeys(cleaned))
