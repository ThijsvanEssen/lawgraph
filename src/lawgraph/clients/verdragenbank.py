"""Client for the Dutch Verdragenbank (treaty register), via the KOOP SRU.

The treaties are the records with ``c.product-area==vd`` of the SRU at
https://repository.overheid.nl/sru (the source behind https://verdragenbank.overheid.nl/).
A treaty is a record of ``w.documenttype==verdrag``; the Dutch and the English title are
separate records with the same identifier, so both languages are read and joined.

Each treaty provides:
  - title (Dutch and English)
  - the url of its item XML (``gzd:url``) and when it was last modified
  - date of signature (``datumTotstandkoming``) and of entry into force
  - type (Bilateraal, Multilateraal, Plurilateraal)
  - status (Inwerkinggetreden, Buitenwerkinggetreden, Totstandgekomen, ...)
  - the Verdragenbank id (six digits), which is the treaty number of these records
"""

from __future__ import annotations

from typing import Any

from lawgraph.clients._sru import iter_publications, record_dicts
from lawgraph.clients.base import PAGE_TIMEOUT, BaseClient
from lawgraph.config.sources import KOOP_SRU
from lawgraph.core.logging import get_logger
from lawgraph.core.official_urls import VERDRAGENBANK

logger = get_logger(__name__)

_PAGE_SIZE = 250  # records are large: about 7 MB per 1000
_QUERY = "c.product-area==vd AND w.documenttype==verdrag AND dt.language=={language}"
_FIELDS = {
    "title": "title",
    "date_signed": "datumTotstandkoming",
    "date_in_force": "inwerkingtredingsdatum",
    "treaty_type": "typeVerdrag",
    "status": "statusVerdrag",
    "url": "preferredUrl",
    # the item XML of the treaty: its parties, Tractatenbladen, dossiers (``gzd:url``)
    "item_url": "url",
    "modified": "modified",
}


class VerdragenbankClient(BaseClient):
    """Client for fetching treaties from the Dutch Verdragenbank via SRU."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=KOOP_SRU, session=session)

    def enumerate_treaties(
        self, max_records: int | None = None
    ) -> list[dict[str, Any]]:
        """Every treaty, with normalized field names; *max_records* stops early.

        Raises when a request fails, and when there are no treaties at all: the endpoint or
        its data model has then changed.
        """
        dutch = self._search("nl", max_records)
        english = {t["identifier"]: t for t in self._search("en", max_records)}
        if not dutch:
            raise RuntimeError(
                f"Verdragenbank SRU returned no treaties at all: the endpoint "
                f"{self.base_url} or its data model has changed."
            )

        treaties: list[dict[str, Any]] = []
        for nl in dutch:
            identifier = nl["identifier"]
            en = english.get(identifier, {})
            treaties.append(
                {
                    "uri": nl["url"] or VERDRAGENBANK.format(identifier=identifier),
                    "title": nl["title"] or en.get("title"),
                    "title_nl": nl["title"],
                    "title_en": en.get("title"),
                    "date_signed": nl["date_signed"],
                    "date_in_force": nl["date_in_force"],
                    "treaty_type": nl["treaty_type"],
                    "status": nl["status"],
                    "verdragsnummer": identifier,
                    "item_url": nl["item_url"],
                    "modified": nl["modified"],
                }
            )
        logger.info("Verdragenbank: %d treaties.", len(treaties))
        return treaties

    def fetch_treaty_xml(self, item_url: str) -> str:
        """The item XML of a treaty (its record's ``gzd:url``). A failed request raises,
        after the retries (404 when the repository has none), and so does a page that is
        not XML (``UnexpectedAnswer``)."""
        return self.get_xml(item_url, timeout=PAGE_TIMEOUT)

    def _search(self, language: str, limit: int | None) -> list[dict[str, Any]]:
        return list(
            iter_publications(
                self,
                self.base_url,
                query=_QUERY.format(language=language),
                parse=lambda root: record_dicts(root, _FIELDS),
                context=f"Verdragenbank {language}",
                page_size=_PAGE_SIZE,
                connection=None,
                limit=limit,
            )
        )
