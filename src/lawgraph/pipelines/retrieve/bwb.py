from __future__ import annotations

from collections.abc import Sequence

from lawgraph.clients.bwb import BWBClient
from lawgraph.config.settings import RAW_KIND_BWB_TOESTAND, SOURCE_BWB
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class BWBRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline that fetches BWB toestanden for configured IDs."""
    def __init__(
        self,
        store: ArangoStore,
        *,
        client: BWBClient | None = None,
        bwb_ids: Sequence[str] | None = None,
    ) -> None:
        super().__init__(store)
        self.client = client or BWBClient()
        self.bwb_ids = self._normalize_ids(bwb_ids)

    def fetch(
        self,
        *args: object,
        **kwargs: object,
    ) -> Sequence[RetrieveRecord]:
        """Query the SRU service for each configured BWBR ID and store the raw XML."""
        if not self.bwb_ids:
            logger.warning("Geen BWB-IDs geconfigureerd; overslaan.")
            return []

        logger.info("Starting BWB retrieve for %d configured IDs.", len(self.bwb_ids))
        records: list[RetrieveRecord] = []
        stored = 0

        for bwb_id in self.bwb_ids:
            meta = self.client.latest_toestand(bwb_id)
            if meta is None:
                continue

            try:
                xml_text = self.client.fetch_toestand_xml(meta)
            except Exception as exc:
                logger.error(
                    "Kon toestand XML voor %s niet downloaden: %s",
                    bwb_id,
                    exc,
                )
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
                self.store.insert_raw_source(
                    source=record.source,
                    kind=record.kind,
                    external_id=record.external_id,
                    payload_json=record.payload_json,
                    payload_text=record.payload_text,
                    meta=record.meta,
                )
                stored += 1
                records.append(record)
            except Exception as exc:
                logger.error(
                    "Kon raw_source voor %s niet opslaan: %s",
                    bwb_id,
                    exc,
                )

        logger.info(
            "BWB retrieve slaagde voor %d van %d geconfigureerde IDs.",
            stored,
            len(self.bwb_ids),
        )
        return records

    @staticmethod
    def _normalize_ids(ids: Sequence[str] | None) -> list[str]:
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
        # preserve ordering while removing duplicates
        return list(dict.fromkeys(cleaned))
