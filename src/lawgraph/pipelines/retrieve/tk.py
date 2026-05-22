from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from typing import Any

from lawgraph.clients.tk import TKClient
from lawgraph.config.constants import (
    RAW_KIND_TK_DOCUMENTVERSIE,
    RAW_KIND_TK_ZAAK,
    SOURCE_TK,
)
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class TKRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for TK Zaak and DocumentVersie raw sources."""

    def __init__(self, store: ArangoStore, tk_client: TKClient | None = None) -> None:
        super().__init__(store)
        self.tk = tk_client or TKClient()

    def fetch(  # type: ignore[override]
        self,
        *,
        since: dt.datetime,
        limit: int = 0,
        zaak_filter: Callable[[dict[str, Any]], bool] | None = None,
        documentversie_filter: Callable[[dict[str, Any]], bool] | None = None,
        keywords: list[str] | None = None,
        **kwargs: object,
    ) -> Sequence[RetrieveRecord]:
        """Return records for TK Zaak and DocumentVersie that match the filters.

        If *keywords* is provided, keyword matching is pushed into the OData
        query so the API only returns relevant records (avoids fetching 30k+
        records and discarding most of them client-side).

        ``limit`` is kept for backwards compatibility but is no longer used as
        an OData ``$top`` cap — doing so silently dropped records beyond the
        limit. All pages are now fetched via nextLink pagination. Pass
        ``limit > 0`` only to hard-cap the in-memory result list after fetching
        (useful for smoke-test / development runs).
        """
        logger.info(
            "Fetching TK Zaak and DocumentVersie since %s%s",
            since.isoformat(),
            f" (dev cap: {limit})" if limit else "",
        )

        records: list[RetrieveRecord] = []

        # Always pass top=0 (no $top) so _paged_get follows @odata.nextLink
        # across all pages. Previously passing top=limit capped the OData
        # result set at `limit` records total, silently dropping the rest.
        zaken = self.tk.zaken_modified_since(
            since,
            top=0,
            keyword_fields=["Onderwerp", "Titel"] if keywords else None,
            keywords=keywords,
        )
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
                    },
                )
            )
            if limit and len(records) >= limit:
                logger.warning(
                    "Dev cap of %d records reached for Zaak — stopping.", limit
                )
                break

        # Fetch Document (not DocumentVersie) because Document carries Titel,
        # Onderwerp, and Soort which are needed for content filtering. Each
        # Document record is expanded with its parent Zaak for procedure linking.
        documentversies = self.tk.documents_modified_since(
            since,
            top=0,
            keyword_fields=["Titel", "Onderwerp"] if keywords else None,
            keywords=keywords,
        )
        doc_count = 0
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
                    },
                )
            )
            doc_count += 1
            if limit and doc_count >= limit:
                logger.warning(
                    "Dev cap of %d records reached for DocumentVersie — stopping.",
                    limit,
                )
                break

        zaak_count = sum(1 for rec in records if rec.kind == RAW_KIND_TK_ZAAK)
        documentversie_count = sum(
            1 for rec in records if rec.kind == RAW_KIND_TK_DOCUMENTVERSIE
        )
        logger.info(
            "TK retrieve complete: %d records total (%d zaken, %d documentversies).",
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
