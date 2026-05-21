"""Client for the Eerste Kamer OData v4 API.

Endpoint: https://gegevensmagazijn.eerstekamer.nl/OData/v4/2.0/
Docs: https://www.eerstekamer.nl/begrip/open_data

Fetches legislative documents (Kamerstukken), vergaderingen, and stemmingen
from the Senate's data magazine.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import EERSTEKAMER_BASE_URL
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

_PAGE_SIZE = 100


class EerstekamerClient(BaseClient):
    """Client for the Eerste Kamer OData v4 data API."""

    def __init__(self, session=None) -> None:
        super().__init__(
            env_var="EERSTEKAMER_BASE",
            default_base_url=EERSTEKAMER_BASE_URL,
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
                resp = self.session.get(url, params=extra, timeout=60)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
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

    def list_vergaderingen(
        self,
        *,
        since: str | None = None,
        max_records: int = 10000,
    ) -> list[dict[str, Any]]:
        """List EK vergaderingen (plenary sessions)."""
        params: dict[str, Any] = {
            "$select": "Id,Titel,Datum,Soort,Modified",
            "$orderby": "Modified desc",
        }
        if since:
            params["$filter"] = f"Modified ge {since}T00:00:00Z"

        records = list(
            self._get_paged("Vergadering", params=params, max_records=max_records)
        )
        logger.info("EK: fetched %d vergaderingen.", len(records))
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

    def fetch_kamerstuk_content(self, item_id: str) -> dict[str, Any] | None:
        """Fetch the full record including text content for a single kamerstuk."""
        url = self.base_url + f"Kamerstuk(guid'{item_id}')"
        params = {"$expand": "Inhoud"}
        try:
            resp = self.session.get(url, params=params, timeout=60)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("EK: failed to fetch kamerstuk %s: %s", item_id, exc)
            return None
