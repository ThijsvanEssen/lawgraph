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
    uses, sometimes with an addition: ``35925 VII``); a paper on more than one dossier names
    each (``dossier_numbers``, the first also as ``dossier_number``)
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from typing import Any

import requests

from lawgraph.clients._sru import iter_publications, record_dicts
from lawgraph.clients.base import BaseClient
from lawgraph.config.sources import KOOP_SRU
from lawgraph.core.xml import own_texts

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

    def __init__(self, session: requests.Session | None = None) -> None:
        super().__init__(base_url=KOOP_SRU, session=session)

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


def _parse_papers(root: ET.Element) -> list[dict[str, Any]]:
    return record_dicts(
        root, _FIELDS, dossier_numbers=lambda record: own_texts(record, "dossiernummer")
    )
