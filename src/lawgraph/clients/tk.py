# src/lawgraph/clients/tk.py
from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import TK_BASE_URL
from lawgraph.logging import get_logger

# Structural changes:
# - TK API base URL now sourced from lawgraph.config.settings and helpers carry docstrings.


logger = get_logger(__name__)


class TKClient(BaseClient):
    """
    Client voor de OData API van het Gegevensmagazijn van de Tweede Kamer.

    Docs:
      - https://opendata.tweedekamer.nl/documentatie/odata-api
    """

    def __init__(self, session=None) -> None:
        """Initialize the Tweede Kamer OData client."""
        super().__init__(
            env_var="TK_API_BASE",
            default_base_url=TK_BASE_URL,
            session=session,
        )

    @staticmethod
    def _format_odata_datetime(value: dt.datetime) -> str:
        """
        Format a datetime for TK's OData filter.

        We always send UTC in the form: YYYY-MM-DDTHH:MM:SSZ
        (no offset like +00:00, and no microseconds).
        """
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc)
        # strip tzinfo and microseconds, then add 'Z'
        value = value.replace(microsecond=0, tzinfo=None)
        return value.isoformat() + "Z"

    def _paged_get(
        self, path: str, params: dict | None = None
    ) -> Iterable[dict[str, Any]]:
        """Yields paged TK OData entries via the shared BaseClient helper."""
        return super()._paged_get(
            path,
            params=params,
            result_key="value",
            next_link_key="@odata.nextLink",
        )

    def zaken_modified_since(self, since: dt.datetime, top: int = 100) -> list[dict]:
        """Return TK zaak records that were modified since the supplied datetime."""
        since_string = TKClient._format_odata_datetime(since)
        params = {
            "$top": top,
            "$filter": f"ApiGewijzigdOp ge {since_string}",
        }
        logger.info("Fetching Zaak modified since %s", since_string)
        return list(self._paged_get("Zaak", params=params))

    def documentversies_modified_since(
        self, since: dt.datetime, top: int = 100
    ) -> list[dict]:
        """Return TK documentversie records that were modified since the supplied datetime."""
        since_string = TKClient._format_odata_datetime(since)
        params = {
            "$top": top,
            "$filter": f"ApiGewijzigdOp ge {since_string}",
        }
        logger.info("Fetching DocumentVersie modified since %s", since_string)
        return list(self._paged_get("DocumentVersie", params=params))

    def raw_entity(self, entity: str, params: dict | None = None) -> list[dict]:
        """Fetch an arbitrary TK entity via paged OData listing."""
        return list(self._paged_get(entity, params=params))
