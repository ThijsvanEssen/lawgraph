"""Client for the Eerste Kamer OData v4 API.

Endpoint: https://gegevensmagazijn.eerstekamer.nl/OData/v4/2.0/
Docs: https://www.eerstekamer.nl/begrip/open_data

Fetches legislative documents (Kamerstukken), vergaderingen, and stemmingen
from the Senate's data magazine.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import requests

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import EERSTEKAMER_BASE_URL
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

_PAGE_SIZE = 100


class EerstekamerClient(BaseClient):
    """Client for the Eerste Kamer OData v4 data API."""

    def __init__(self, session=None) -> None:
        super().__init__(
            base_url=EERSTEKAMER_BASE_URL,
            session=session,
        )
        self.session.headers.update({"Accept": "application/json"})

    def _get_paged(
        self,
        entity: str,
        *,
        params: dict[str, Any] | None = None,
        max_records: int = 50000,
    ) -> Iterator[dict[str, Any]]:
        """Yield all records from an OData entity with server-side paging."""
        url = self.base_url + entity
        extra = dict(params or {})
        extra.setdefault("$top", str(_PAGE_SIZE))
        extra.setdefault("$count", "false")

        total = 0
        while url and total < max_records:
            try:
                resp = self._get_raw_absolute_with_retry(url, params=extra, timeout=60)
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("EK API error fetching %s: %s", entity, exc)
                break

            items = data.get("value", [])
            if not items:
                break

            for item in items:
                yield item
                total += 1
                if total >= max_records:
                    break

            # OData nextLink for pagination
            url = data.get("@odata.nextLink")
            extra = {}  # nextLink already has query params

    def list_kamerstukken(
        self,
        *,
        since: str | None = None,
        max_records: int = 50000,
    ) -> list[dict[str, Any]]:
        """List EK Kamerstukken (legislative documents).

        Args:
            since: ISO date string (YYYY-MM-DD) for incremental fetching.
        """
        params: dict[str, Any] = {
            "$select": (
                "Id,Nummer,Soort,Titel,Datum,Vergaderjaar,Volgnummer,"
                "DossierNummer,Modified"
            ),
            "$orderby": "Modified desc",
        }
        if since:
            params["$filter"] = f"Modified ge {since}T00:00:00Z"

        records = list(
            self._get_paged("Kamerstuk", params=params, max_records=max_records)
        )
        logger.info("EK: fetched %d kamerstukken.", len(records))
        return records

    def list_stemmingen(
        self,
        *,
        since: str | None = None,
        max_records: int = 50000,
    ) -> list[dict[str, Any]]:
        """List EK stemmingen (votes) with outcome."""
        params: dict[str, Any] = {
            "$select": "Id,KamerstukId,VergaderingId,Soort,Aangenomen,Modified",
            "$orderby": "Modified desc",
        }
        if since:
            params["$filter"] = f"Modified ge {since}T00:00:00Z"

        records = list(
            self._get_paged("Stemming", params=params, max_records=max_records)
        )
        logger.info("EK: fetched %d stemmingen.", len(records))
        return records
