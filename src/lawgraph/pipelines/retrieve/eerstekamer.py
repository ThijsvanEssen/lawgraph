"""Retrieve pipeline for the Kamerstukken of the Eerste Kamer (KOOP SRU)."""

from __future__ import annotations

from lawgraph.clients.eerstekamer import EerstekamerClient
from lawgraph.config.constants import RAW_KIND_EK_KAMERSTUK, SOURCE_EERSTEKAMER
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class EerstekamerRetrievePipeline(RetrievePipelineBase):
    """Store the SRU record of every Eerste Kamer Kamerstuk as ``ek-kamerstuk-json``."""

    def __init__(
        self, store: ArangoStore, client: EerstekamerClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerClient()

    def fetch(  # type: ignore[override]
        self,
        *,
        since: str | None = None,
        limit: int | None = None,
        **kwargs: object,
    ) -> list[RetrieveRecord]:
        papers = self.client.search_kamerstukken(since=since, limit=limit)
        records = [
            RetrieveRecord(
                source=SOURCE_EERSTEKAMER,
                kind=RAW_KIND_EK_KAMERSTUK,
                external_id=paper["identifier"],
                payload_json=paper,
                meta={
                    "dossier_number": paper.get("dossier_number"),
                    "modified": paper.get("modified"),
                },
            )
            for paper in papers
        ]
        logger.info("Eerste Kamer retrieve: prepared %d Kamerstukken.", len(records))
        return records
