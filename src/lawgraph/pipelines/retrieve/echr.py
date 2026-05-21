"""Retrieve pipeline for ECHR HUDOC judgments."""

from __future__ import annotations

from lawgraph.clients.echr import EchrClient
from lawgraph.config.constants import RAW_KIND_ECHR_JUDGMENT, SOURCE_ECHR
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class EchrRetrievePipeline(RetrievePipelineBase):
    """Retrieve ECHR HUDOC judgments for a given respondent country."""

    def __init__(self, store: ArangoStore, client: EchrClient | None = None) -> None:
        super().__init__(store)
        self.client = client or EchrClient()

    def fetch(
        self,
        *,
        respondent: str = "NLD",
        since_date: str | None = None,
        max_records: int = 10000,
        **kwargs,
    ) -> list[RetrieveRecord]:
        judgments = self.client.search_judgments(
            respondent=respondent,
            since_date=since_date,
            max_records=max_records,
        )

        records: list[RetrieveRecord] = []
        for judgment in judgments:
            item_id = str(judgment.get("itemid") or "")
            if not item_id:
                continue
            records.append(
                RetrieveRecord(
                    source=SOURCE_ECHR,
                    kind=RAW_KIND_ECHR_JUDGMENT,
                    external_id=item_id,
                    payload_json=judgment,
                    meta={
                        "appno": judgment.get("appno"),
                        "docname": judgment.get("docname"),
                        "kpdate": judgment.get("kpdate"),
                        "respondent": respondent,
                    },
                )
            )

        logger.info(
            "ECHR retrieve: prepared %d judgment records (respondent=%s).",
            len(records),
            respondent,
        )
        return records

    def run(
        self,
        *,
        respondent: str = "NLD",
        since_date: str | None = None,
        max_records: int = 10000,
        **kwargs,
    ) -> PipelineResult:
        result = PipelineResult()
        records = self.fetch(
            respondent=respondent,
            since_date=since_date,
            max_records=max_records,
        )
        for record in records:
            try:
                self._insert(record)
                result.created += 1
            except Exception as exc:
                msg = f"Failed to store ECHR judgment {record.external_id}: {exc}"
                logger.error(msg)
                result.add_error(msg)
                result.skipped += 1
        return result

    def run_full(self, respondent: str = "NLD") -> PipelineResult:
        """Fetch all available ECHR judgments for the respondent."""
        return self.run(respondent=respondent, max_records=50000)
