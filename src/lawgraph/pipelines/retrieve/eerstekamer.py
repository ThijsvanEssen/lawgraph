"""Retrieve pipeline for Eerste Kamer OData API."""

from __future__ import annotations

from lawgraph.clients.eerstekamer import EerstekamerClient
from lawgraph.config.constants import RAW_KIND_EK_STUK, SOURCE_EERSTEKAMER
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)

# EK Stemmingen are stored under the same raw kind; the meta field
# ``record_type`` distinguishes them from Kamerstukken during normalization.


class EerstekamerRetrievePipeline(RetrievePipelineBase):
    """Retrieve Eerste Kamer Kamerstukken and Stemmingen."""

    def __init__(
        self, store: ArangoStore, client: EerstekamerClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or EerstekamerClient()

    def fetch(
        self,
        *,
        since: str | None = None,
        max_records: int = 50000,
        skip_decisions: bool = False,
        **kwargs,
    ) -> list[RetrieveRecord]:
        records: list[RetrieveRecord] = []

        kamerstukken = self.client.list_kamerstukken(
            since=since, max_records=max_records
        )
        for stuk in kamerstukken:
            item_id = str(stuk.get("Id") or "")
            if not item_id:
                continue
            records.append(
                RetrieveRecord(
                    source=SOURCE_EERSTEKAMER,
                    kind=RAW_KIND_EK_STUK,
                    external_id=item_id,
                    payload_json=stuk,
                    meta={
                        "record_type": "kamerstuk",
                        "kind": stuk.get("Soort"),
                        "date": stuk.get("Datum"),
                        "dossier_number": stuk.get("DossierNummer"),
                    },
                )
            )

        logger.info("EK retrieve: prepared %d kamerstuk records.", len(records))

        if not skip_decisions:
            decisions = self.client.list_stemmingen(
                since=since, max_records=max_records
            )
            for stemming in decisions:
                item_id = str(stemming.get("Id") or "")
                if not item_id:
                    continue
                # Prefix to avoid key collision with kamerstukken
                records.append(
                    RetrieveRecord(
                        source=SOURCE_EERSTEKAMER,
                        kind=RAW_KIND_EK_STUK,
                        external_id=f"stemming-{item_id}",
                        payload_json=stemming,
                        meta={
                            "record_type": "stemming",
                            "parliamentary_paper_id": stemming.get("KamerstukId"),
                            "meeting_id": stemming.get("VergaderingId"),
                            "passed": stemming.get("Aangenomen"),
                        },
                    )
                )
            logger.info("EK retrieve: prepared %d vote records.", len(decisions))

        return records
