"""Client voor de OData API van het Gegevensmagazijn van de Tweede Kamer."""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import TK_BASE_URL
from lawgraph.logging import get_logger

logger = get_logger(__name__)


def _build_contains_filter(fields: list[str], keywords: list[str]) -> str:
    """Build an OData OR expression: (contains(tolower(F),'kw') or ...)."""
    clauses = [
        f"contains(tolower({field}),'{kw.lower()}')"
        for field in fields
        for kw in keywords
    ]
    return "(" + " or ".join(clauses) + ")"


class TKClient(BaseClient):
    """
    Client voor de OData API van het Gegevensmagazijn van de Tweede Kamer.

    Docs: https://opendata.tweedekamer.nl/documentatie/odata-api
    """

    def __init__(self, session=None) -> None:
        super().__init__(
            env_var="TK_API_BASE",
            default_base_url=TK_BASE_URL,
            session=session,
        )

    @staticmethod
    def _format_odata_datetime(value: dt.datetime) -> str:
        """Format a datetime for TK's OData filter: YYYY-MM-DDTHH:MM:SSZ."""
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc)
        value = value.replace(microsecond=0, tzinfo=None)
        return value.isoformat() + "Z"

    def _paged_get(
        self, path: str, params: dict | None = None
    ) -> Iterable[dict[str, Any]]:
        return super()._paged_get(
            path,
            params=params,
            result_key="value",
            next_link_key="@odata.nextLink",
        )

    def _skip_paged_get(
        self,
        path: str,
        params: dict | None = None,
        page_size: int = 250,
    ) -> Iterable[dict[str, Any]]:
        """OData skip-based pagination for endpoints that don't return nextLink.

        The TK API returns no @odata.nextLink even when more records exist.
        We iterate using $skip until a page returns fewer records than page_size.
        """
        base_params = dict(params or {})
        base_params["$top"] = page_size
        skip = 0
        while True:
            page_params = dict(base_params)
            page_params["$skip"] = skip
            page = self._get_json(path, params=page_params)
            entries = page.get("value", []) if isinstance(page, dict) else []
            yield from entries
            if len(entries) < page_size:
                break
            skip += page_size

    # ── Existing entity fetchers ───────────────────────────────────────────────

    def zaken_modified_since(
        self,
        since: dt.datetime,
        top: int = 100,
        keyword_fields: list[str] | None = None,
        keywords: list[str] | None = None,
    ) -> list[dict]:
        """Return TK Zaak records modified since *since*."""
        since_string = self._format_odata_datetime(since)
        odata_filter = f"ApiGewijzigdOp ge {since_string}"
        if keywords and keyword_fields:
            odata_filter += " and " + _build_contains_filter(keyword_fields, keywords)
        params: dict[str, Any] = {"$filter": odata_filter}
        if top:
            params["$top"] = top
        logger.info("Fetching Zaak modified since %s", since_string)
        return list(self._paged_get("Zaak", params=params))

    def documents_modified_since(
        self,
        since: dt.datetime,
        top: int = 100,
        keyword_fields: list[str] | None = None,
        keywords: list[str] | None = None,
    ) -> list[dict]:
        """Return TK Document records modified since *since*, with Zaak expanded."""
        since_string = self._format_odata_datetime(since)
        odata_filter = f"ApiGewijzigdOp ge {since_string}"
        if keywords and keyword_fields:
            odata_filter += " and " + _build_contains_filter(keyword_fields, keywords)
        params: dict[str, Any] = {"$filter": odata_filter, "$expand": "Zaak"}
        if top:
            params["$top"] = top
        logger.info("Fetching Document modified since %s", since_string)
        return list(self._paged_get("Document", params=params))

    def raw_entity(self, entity: str, params: dict | None = None) -> list[dict]:
        """Fetch an arbitrary TK entity via paged OData listing."""
        return list(self._paged_get(entity, params=params))

    def fetch_document_bytes(self, document_id: str, *, timeout: int = 60) -> bytes:
        """Fetch the raw binary content of a TK document by its UUID."""
        path = f"Document({document_id})/resource"
        return self._get_raw(path, timeout=timeout).content

    # ── New parliamentary entity fetchers ─────────────────────────────────────

    def fetch_dossiers(
        self,
        since: dt.datetime | None = None,
        top: int = 250,
    ) -> list[dict]:
        """Fetch Kamerstukdossier records, optionally filtered by modification date.

        Uses skip-based pagination because the TK API does not emit nextLink.
        """
        params: dict[str, Any] = {}
        if since is not None:
            since_string = self._format_odata_datetime(since)
            params["$filter"] = f"ApiGewijzigdOp ge {since_string}"
            logger.info("Fetching Kamerstukdossier modified since %s", since_string)
        else:
            logger.info("Fetching all Kamerstukdossier records")
        return list(
            self._skip_paged_get("Kamerstukdossier", params=params, page_size=top)
        )

    def fetch_activiteiten(
        self,
        since: dt.datetime | None = None,
        top: int = 250,
    ) -> list[dict]:
        """Fetch Activiteit (debate/hearing) records.

        Uses a 3-level nested expand to resolve dossier links via the chain
        Agendapunt → Zaak → Kamerstukdossier. Skip-based pagination is used
        because the TK API does not emit nextLink.
        """
        params: dict[str, Any] = {
            "$expand": "Agendapunt($expand=Zaak($expand=Kamerstukdossier($select=Id,Nummer,Toevoeging,Titel)))",  # noqa: E501
        }
        if since is not None:
            since_string = self._format_odata_datetime(since)
            params["$filter"] = f"ApiGewijzigdOp ge {since_string}"
            logger.info("Fetching Activiteit modified since %s", since_string)
        else:
            logger.info("Fetching all Activiteit records")
        return list(self._skip_paged_get("Activiteit", params=params, page_size=top))

    def fetch_stemmingen(
        self,
        since: dt.datetime | None = None,
        top: int = 250,
    ) -> list[dict]:
        """Fetch Stemming (vote) records with the parent Besluit expanded.

        Each Stemming record is one fractie's vote on one Besluit. Caller must
        group by Besluit_Id to reconstruct the full vote breakdown per decision.
        Relevant fields: ActorFractie (party), Soort (Voor/Tegen/Onthouden),
        FractieGrootte (seats), Vergissing (mistaken vote).
        """
        params: dict[str, Any] = {"$expand": "Besluit"}
        if since is not None:
            since_string = self._format_odata_datetime(since)
            params["$filter"] = f"ApiGewijzigdOp ge {since_string}"
            logger.info("Fetching Stemming modified since %s", since_string)
        else:
            logger.info("Fetching all Stemming records")
        return list(self._skip_paged_get("Stemming", params=params, page_size=top))

    def fetch_toezeggingen(
        self,
        since: dt.datetime | None = None,
        top: int = 250,
    ) -> list[dict]:
        """Fetch Toezegging (ministerial commitment) records."""
        params: dict[str, Any] = {}
        if since is not None:
            since_string = self._format_odata_datetime(since)
            params["$filter"] = f"ApiGewijzigdOp ge {since_string}"
            logger.info("Fetching Toezegging modified since %s", since_string)
        else:
            logger.info("Fetching all Toezegging records")
        return list(self._skip_paged_get("Toezegging", params=params, page_size=top))

    def fetch_commissies(self, top: int = 250) -> list[dict]:
        """Fetch Commissie (committee) records with CommissieZetel members expanded."""
        params: dict[str, Any] = {
            "$expand": "CommissieZetel($expand=CommissieZetelVastPersoon)",
        }
        logger.info("Fetching Commissie records")
        return list(self._skip_paged_get("Commissie", params=params, page_size=top))

    def fetch_personen(self, top: int = 250) -> list[dict]:
        """Fetch Persoon (parliamentary member) records.

        The Fractielabel field contains the party label directly — no expand needed.
        """
        params: dict[str, Any] = {}
        logger.info("Fetching Persoon records")
        return list(self._skip_paged_get("Persoon", params=params, page_size=top))
