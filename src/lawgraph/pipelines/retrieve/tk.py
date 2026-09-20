from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator
from typing import Any

from lawgraph.clients.tk import TKClient
from lawgraph.config.constants import RAW_KIND_TK_DOCUMENT, RAW_KIND_TK_ZAAK, SOURCE_TK
from lawgraph.core.logging import get_logger
from lawgraph.core.values import first_str
from lawgraph.db import ArangoStore

from .base import RetrievePipelineBase, RetrieveRecord

logger = get_logger(__name__)


class TKRetrievePipeline(RetrievePipelineBase):
    """Retrieve pipeline for TK Zaak and Document raw sources."""

    def __init__(self, store: ArangoStore, tk_client: TKClient | None = None) -> None:
        super().__init__(store)
        self.tk = tk_client or TKClient()

    def fetch(  # type: ignore[override]
        self,
        *,
        since: dt.datetime,
        limit: int = 0,
        case_filter: Callable[[dict[str, Any]], bool] | None = None,
        document_filter: Callable[[dict[str, Any]], bool] | None = None,
        keywords: list[str] | None = None,
        **kwargs: object,
    ) -> Iterator[RetrieveRecord]:
        """Yield records for TK Zaak and Document that match the filters.

        If *keywords* is provided, keyword matching is pushed into the OData
        query so the API only returns relevant records (avoids fetching 30k+
        records and discarding most of them client-side).

        ``limit`` caps the in-memory result list per entity after fetching
        (useful for smoke-test / development runs); it is not an OData ``$top``,
        which would silently drop records beyond the cap.
        """
        logger.info(
            "Fetching TK Zaak and Document since %s%s",
            since.isoformat(),
            f" (dev cap: {limit})" if limit else "",
        )

        # Always pass top=0 (no $top) so _paged_get follows @odata.nextLink
        # across all pages.
        cases = self.tk.zaken_modified_since(
            since,
            top=0,
            keyword_fields=["Onderwerp", "Titel"] if keywords else None,
            keywords=keywords,
        )
        case_count = 0
        for case in cases:
            if case_filter and not case_filter(case):
                continue
            candidates = [
                case.get("Id"),
                case.get("ZaakId"),
                case.get("ZaakNummer"),
            ]
            external_id = first_str(candidates)
            yield RetrieveRecord(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_ZAAK,
                external_id=external_id,
                payload_json=case,
                meta={
                    "endpoint": "Zaak",
                    "since": since.isoformat(),
                },
            )
            case_count += 1
            if limit and case_count >= limit:
                logger.warning(
                    "Dev cap of %d records reached for Zaak — stopping.", limit
                )
                break

        documents = self.tk.fetch_documents(
            since=since,
            keyword_fields=["Titel", "Onderwerp"] if keywords else None,
            keywords=keywords,
        )
        document_count = 0
        for document in documents:
            if document_filter and not document_filter(document):
                continue
            external_id = first_str([document.get("Id")])
            yield RetrieveRecord(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_DOCUMENT,
                external_id=external_id,
                payload_json=document,
                meta={
                    "endpoint": "Document",
                    "since": since.isoformat(),
                },
            )
            document_count += 1
            if limit and document_count >= limit:
                logger.warning(
                    "Dev cap of %d records reached for Document — stopping.",
                    limit,
                )
                break

        logger.info(
            "TK retrieve complete: %d cases, %d documents.",
            case_count,
            document_count,
        )
