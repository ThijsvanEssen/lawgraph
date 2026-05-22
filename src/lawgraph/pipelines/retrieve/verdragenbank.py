"""Retrieve pipeline for Dutch Verdragenbank (treaty register)."""

from __future__ import annotations

from lawgraph.clients.verdragenbank import VerdragenbankClient
from lawgraph.config.constants import RAW_KIND_VERDRAG, SOURCE_VERDRAGENBANK
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class VerdragenbankRetrievePipeline(RetrievePipelineBase):
    """Retrieve treaty metadata from the Verdragenbank SPARQL endpoint."""

    def __init__(
        self, store: ArangoStore, client: VerdragenbankClient | None = None
    ) -> None:
        super().__init__(store)
        self.client = client or VerdragenbankClient()

    def fetch(
        self, *, max_records: int = 10000, **kwargs: object
    ) -> list[RetrieveRecord]:
        treaties = self.client.enumerate_treaties(max_records=max_records)
        records: list[RetrieveRecord] = []

        for treaty in treaties:
            uri = treaty.get("uri") or ""
            if not uri:
                continue
            # Use the last path segment as the external ID
            external_id = uri.rstrip("/").rsplit("/", 1)[-1] or uri

            records.append(
                RetrieveRecord(
                    source=SOURCE_VERDRAGENBANK,
                    kind=RAW_KIND_VERDRAG,
                    external_id=external_id,
                    payload_json=treaty,
                    meta={
                        "verdragsnummer": treaty.get("verdragsnummer"),
                        "status": treaty.get("status"),
                    },
                )
            )

        logger.info("Verdragenbank retrieve: prepared %d treaty records.", len(records))
        return records
