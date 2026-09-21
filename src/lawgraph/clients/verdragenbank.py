"""Client for the Dutch Verdragenbank (treaty register), via the KOOP SRU.

The treaties are the records with ``c.product-area==vd`` of the SRU at
https://repository.overheid.nl/sru (the source behind https://verdragenbank.overheid.nl/).
A treaty is a record of ``w.documenttype==verdrag``; the Dutch and the English title are
separate records with the same identifier, so both languages are read and joined.

Each treaty provides:
  - title (Dutch and English)
  - date of signature (``datumTotstandkoming``) and of entry into force
  - type (Bilateraal, Multilateraal, Plurilateraal)
  - status (Inwerkinggetreden, Buitenwerkinggetreden, Totstandgekomen, ...)
  - the Verdragenbank id (six digits), which is the treaty number of these records
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.clients._sru import (
    parse_record_fields,
    record_identifier,
    search_publications,
)
from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import VERDRAGENBANK_SRU_ENDPOINT
from lawgraph.core.logging import get_logger
from lawgraph.core.xml import local_name

logger = get_logger(__name__)

_PAGE_SIZE = 250  # records are large: about 7 MB per 1000
_PAGE_URL = "https://verdragenbank.overheid.nl/nl/Verdrag/Details/{identifier}"
_QUERY = "c.product-area==vd AND w.documenttype==verdrag AND dt.language=={language}"
_FIELDS = {
    "title": "title",
    "date_signed": "datumTotstandkoming",
    "date_in_force": "inwerkingtredingsdatum",
    "treaty_type": "typeVerdrag",
    "status": "statusVerdrag",
    "url": "preferredUrl",
}


class VerdragenbankClient(BaseClient):
    """Client for fetching treaties from the Dutch Verdragenbank via SRU."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=VERDRAGENBANK_SRU_ENDPOINT, session=session)

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
                    "uri": nl["url"] or _PAGE_URL.format(identifier=identifier),
                    "title": nl["title"] or en.get("title"),
                    "title_nl": nl["title"],
                    "title_en": en.get("title"),
                    "date_signed": nl["date_signed"],
                    "date_in_force": nl["date_in_force"],
                    "treaty_type": nl["treaty_type"],
                    "status": nl["status"],
                    "verdragsnummer": identifier,
                }
            )
        logger.info("Verdragenbank: %d treaties.", len(treaties))
        return treaties

    def _search(self, language: str, limit: int | None) -> list[dict[str, Any]]:
        return search_publications(
            self,
            self.base_url,
            query=_QUERY.format(language=language),
            parse=_parse_treaties,
            context=f"Verdragenbank {language}",
            page_size=_PAGE_SIZE,
            connection=None,
            limit=limit,
        )


def _parse_treaties(root: ET.Element) -> list[dict[str, Any]]:
    treaties = []
    for record in root.iter():
        if local_name(record.tag) != "record":
            continue
        identifier = record_identifier(record)
        if identifier:
            treaties.append(
                {"identifier": identifier, **parse_record_fields(record, _FIELDS)}
            )
    return treaties
