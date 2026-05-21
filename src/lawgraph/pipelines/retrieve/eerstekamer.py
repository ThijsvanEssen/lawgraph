"""Retrieve pipeline for Eerste Kamer OData API."""

from __future__ import annotations

from lawgraph.clients.eerstekamer import EerstekamerClient
from lawgraph.config.settings import RAW_KIND_EK_STUK, SOURCE_EERSTEKAMER
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import PipelineResult

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)

# EK stemmingen are stored under the same kind; the soort='stemming' meta
# field distinguishes them from Kamerstukken during normalization.
RAW_KIND_EK_STEMMING = "ek-stuk-json"


class EerstekamerRetrievePipeline(RetrievePipelineBase):
    """Retrieve Eerste Kamer Kamerstukken and stemmingen."""

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
        skip_stemmingen: bool = False,
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
                        "soort": stuk.get("Soort"),
                        "datum": stuk.get("Datum"),
                        "dossier_nummer": stuk.get("DossierNummer"),
                    },
                )
            )

        logger.info("EK retrieve: prepared %d kamerstuk records.", len(records))

        if not skip_stemmingen:
            stemmingen = self.client.list_stemmingen(
                since=since, max_records=max_records
            )
            for stemming in stemmingen:
                item_id = str(stemming.get("Id") or "")
                if not item_id:
                    continue
                # Prefix to avoid key collision with kamerstukken
                records.append(
                    RetrieveRecord(
                        source=SOURCE_EERSTEKAMER,
                        kind=RAW_KIND_EK_STEMMING,
                        external_id=f"stemming-{item_id}",
                        payload_json=stemming,
                        meta={
                            "record_type": "stemming",
                            "kamerstuk_id": stemming.get("KamerstukId"),
                            "vergadering_id": stemming.get("VergaderingId"),
                            "aangenomen": stemming.get("Aangenomen"),
                        },
                    )
                )
            logger.info("EK retrieve: prepared %d stemming records.", len(stemmingen))

        return records

    def run(
        self,
        *,
        since: str | None = None,
        max_records: int = 50000,
        skip_stemmingen: bool = False,
        **kwargs,
    ) -> PipelineResult:
        result = PipelineResult()
        records = self.fetch(
            since=since, max_records=max_records, skip_stemmingen=skip_stemmingen
        )
        for record in records:
            try:
                self._insert(record)
                result.created += 1
            except Exception as exc:
                msg = f"Failed to store EK record {record.external_id}: {exc}"
                logger.error(msg)
                result.add_error(msg)
                result.skipped += 1
        return result
