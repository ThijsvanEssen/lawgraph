from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from typing import Any

from lawgraph.clients.tk import TKClient
from lawgraph.config.settings import (
    RAW_KIND_TK_DOCUMENTVERSIE,
    RAW_KIND_TK_ZAAK,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger

from .base import RetrieveRecord, RetrievePipelineBase

logger = get_logger(__name__)


class TKRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for TK Zaak and DocumentVersie raw sources."""
    def __init__(self, store: ArangoStore, tk_client: TKClient | None = None) -> None:
        super().__init__(store)
        self.tk = tk_client or TKClient()

    def fetch(
        self,
        *args: object,
        since: dt.datetime,
        limit: int = 100,
        zaak_filter: Callable[[dict[str, Any]], bool] | None = None,
        documentversie_filter: Callable[[dict[str, Any]], bool] | None = None,
        **kwargs: object,
    ) -> Sequence[RetrieveRecord]:
        """Return records for TK Zaak and DocumentVersie that match the filters."""
        logger.info(
            "Fetching TK Zaak and DocumentVersie since %s (limit %d)",
            since.isoformat(),
            limit,
        )

        records: list[RetrieveRecord] = []

        zaken = self.tk.zaken_modified_since(since, top=limit)
        for zaak in zaken:
            if zaak_filter and not zaak_filter(zaak):
                continue
            candidates = [
                zaak.get("Id"),
                zaak.get("ZaakId"),
                zaak.get("ZaakNummer"),
            ]
            external_id = self._first_non_none_str(candidates)
            records.append(
                RetrieveRecord(
                    source=SOURCE_TK,
                    kind=RAW_KIND_TK_ZAAK,
                    external_id=external_id,
                    payload_json=zaak,
                    meta={
                        "endpoint": "Zaak",
                        "since": since.isoformat(),
                        "limit": limit,
                    },
                )
            )

        documentversies = self.tk.documentversies_modified_since(since, top=limit)
        for documentversie in documentversies:
            if documentversie_filter and not documentversie_filter(documentversie):
                continue
            candidates = [
                documentversie.get("Id"),
                documentversie.get("DocumentVersieId"),
            ]
            external_id = self._first_non_none_str(candidates)
            records.append(
                RetrieveRecord(
                    source=SOURCE_TK,
                    kind=RAW_KIND_TK_DOCUMENTVERSIE,
                    external_id=external_id,
                    payload_json=documentversie,
                    meta={
                        "endpoint": "DocumentVersie",
                        "since": since.isoformat(),
                        "limit": limit,
                    },
                )
            )

        zaak_count = sum(1 for rec in records if rec.kind == RAW_KIND_TK_ZAAK)
        documentversie_count = sum(
            1 for rec in records if rec.kind == RAW_KIND_TK_DOCUMENTVERSIE
        )
        logger.info(
            "TK retrieve produced %d records (%d zaken, %d documentversies).",
            len(records),
            zaak_count,
            documentversie_count,
        )
        return records

    @staticmethod
    def _first_non_none_str(values: Sequence[str | None]) -> str | None:
        for value in values:
            if value is not None:
                return str(value)
        return None
