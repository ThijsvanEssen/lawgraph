from __future__ import annotations

from collections.abc import Sequence

from lawgraph.clients.eu import EUClient
from lawgraph.config.settings import RAW_KIND_EU_CELEX, SOURCE_EURLEx
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

from .base import RetrieveRecord, RetrievePipelineBase

logger = get_logger(__name__)


class EurlexRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for EUR-Lex CELEX html dumps."""

    def __init__(self, store: ArangoStore, eu_client: EUClient | None = None) -> None:
        super().__init__(store)
        self.eu = eu_client or EUClient()

    def fetch(
        self,
        *args: object,
        celex_ids: Sequence[str],
        lang: str = "NL",
        **kwargs: object,
    ) -> Sequence[RetrieveRecord]:
        """Return raw HTML payloads for the requested CELEX identifiers."""
        logger.info("Fetching EUR-Lex CELEX ids: %s", celex_ids)
        records: list[RetrieveRecord] = []
        for celex in celex_ids:
            html = self.eu.fetch_celex_html(celex, lang=lang)
            records.append(
                RetrieveRecord(
                    source=SOURCE_EURLEx,
                    kind=RAW_KIND_EU_CELEX,
                    external_id=celex,
                    payload_text=html,
                    meta={"celex": celex, "lang": lang},
                )
            )
        logger.info("EUR-Lex retrieve created %d records.", len(records))
        return records
