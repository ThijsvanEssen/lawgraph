"""Client for the papers of the Eerste Kamer, via the KOOP SRU.

The Eerste Kamer has no API of its own. Its Kamerstukken are published in the official
publications (https://zoek.officielebekendmakingen.nl/) and searchable through the SRU at
https://repository.overheid.nl/sru: records with creator ``Eerste Kamer der
Staten-Generaal`` and publication name ``Kamerstuk``. Attachments (``blg-*``) are left out.

Each paper provides:
  - the identifier (``kst-<dossier>-<letter>``, some ``kst-<number>``)
  - its own title (``documenttitel``, e.g. "Verslag") and the title of the dossier
  - the kind (``subrubriek``), the number within the dossier (``ondernummer``: A, B, C)
  - the date, the session year and the dossier number (the same number the Tweede Kamer
    uses, sometimes with an addition: ``35925 VII``)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import Any

from lawgraph.clients._sru import (
    iter_publications,
    parse_record_fields,
    record_identifier,
)
from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import EERSTEKAMER_SRU_ENDPOINT
from lawgraph.core.logging import get_logger
from lawgraph.core.xml import local_name

logger = get_logger(__name__)

_QUERY = (
    'dt.creator=="Eerste Kamer der Staten-Generaal" '
    "AND w.publicatienaam==Kamerstuk AND dt.type==Kamerstuk"
)
_FIELDS = {
    "title": "title",
    "document_title": "documenttitel",
    "dossier_title": "dossiertitel",
    "kind": "subrubriek",
    "number": "ondernummer",
    "session_year": "vergaderjaar",
    "dossier_number": "dossiernummer",
    "date": "date",
    "modified": "modified",
    "url": "preferredUrl",
}


class EerstekamerClient(BaseClient):
    """Client for fetching Eerste Kamer Kamerstukken from the KOOP SRU."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=EERSTEKAMER_SRU_ENDPOINT, session=session)

    def iter_kamerstukken(
        self, *, since: str | None = None, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield the Kamerstukken page by page, ``since`` on ``dt.modified``.

        *limit* stops early. A failing request or an SRU error raises, after the papers of
        the earlier pages were yielded.
        """
        query = _QUERY if not since else f"{_QUERY} AND dt.modified>={since}"
        return iter_publications(
            self,
            self.base_url,
            query=query,
            parse=_parse_papers,
            context="Eerste Kamer",
            connection=None,
            limit=limit,
        )

    def search_kamerstukken(
        self, *, since: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """The Kamerstukken as a list; see ``iter_kamerstukken``."""
        papers = list(self.iter_kamerstukken(since=since, limit=limit))
        logger.info("Eerste Kamer SRU search returned %d Kamerstukken.", len(papers))
        return papers


def _parse_papers(root: ET.Element) -> list[dict[str, Any]]:
    papers = []
    for record in root.iter():
        if local_name(record.tag) != "record":
            continue
        identifier = record_identifier(record)
        if identifier:
            papers.append(
                {"identifier": identifier, **parse_record_fields(record, _FIELDS)}
            )
    return papers
