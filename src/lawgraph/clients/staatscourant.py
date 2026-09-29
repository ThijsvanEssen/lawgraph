"""Client for the Dutch Staatscourant via KOOP SRU.

Fetches ministeriele regelingen from the official publication platform.
SRU endpoint: https://repository.overheid.nl/sru
Repository: https://repository.overheid.nl

query: dt.type=Ministeriele-regeling
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any

from lawgraph.clients._sru import (
    fetch_publication_xml,
    iter_publications,
    parse_sru_records,
    search_publications,
)
from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import STAATSCOURANT_REPO_BASE, STAATSCOURANT_SRU_ENDPOINT
from lawgraph.core.identifiers import STCRT_ID_PATTERN
from lawgraph.core.logging import get_logger
from lawgraph.core.xml import local_name

logger = get_logger(__name__)


class StaatscourantClient(BaseClient):
    """Client for fetching Staatscourant ministeriele regelingen publications."""

    def __init__(self, session=None) -> None:
        super().__init__(
            base_url=STAATSCOURANT_REPO_BASE,
            session=session,
        )

    def search_ministeriele_regelingen(
        self, *, since: str | None = None
    ) -> list[dict[str, Any]]:
        """Search the KOOP SRU for Ministeriele-regeling publications, ``since`` on ``dt.modified``.

        Returns dicts with keys: identifier, year, number, title, content_url.
        """
        query = "dt.type=Ministeriele-regeling"
        if since:
            query += f" AND dt.modified>={since}"
        records = search_publications(
            self,
            STAATSCOURANT_SRU_ENDPOINT,
            query=query,
            parse=self._parse_sru_records,
            context="Staatscourant",
        )
        logger.info("Staatscourant SRU search returned %d records.", len(records))
        return records

    def creators(self, phrase: str, date_from: str, date_to: str) -> Counter[str]:
        """How many of the publications in the Staatscourant and the Staatsblad between the
        two days that name *phrase* each creator issued (``dcterms:creator``,
        ``Ministerie van Financiën``)."""
        query = (
            "c.product-area=officielepublicaties AND (w.publicatienaam=Staatscourant OR "
            f"w.publicatienaam=Staatsblad) AND dt.date>={date_from} AND "
            f'dt.date<={date_to} AND cql.textAndIndexes="{phrase}"'
        )
        found: Counter[str] = Counter()
        for record in iter_publications(
            self,
            STAATSCOURANT_SRU_ENDPOINT,
            query=query,
            parse=_record_creators,
            context=f"Staatscourant {phrase!r}",
        ):
            found.update(record["creators"])
        return found

    def _parse_sru_records(self, root: ET.Element) -> list[dict[str, Any]]:
        """Parse SRU response XML into record dicts."""
        return parse_sru_records(
            root,
            id_pattern=STCRT_ID_PATTERN,
            extra_fields=("date",),
            default_title_prefix="Staatscourant",
        )

    def fetch_publication_xml(self, identifier: str) -> str | None:
        """The XML of a Staatscourant publication, or ``None`` when the repository has none."""
        return fetch_publication_xml(self, "stcrt", STCRT_ID_PATTERN, identifier)


def _record_creators(root: ET.Element) -> list[dict[str, Any]]:
    """``{creators}`` of every record of an SRU page."""
    return [
        {
            "creators": sorted(
                {
                    (e.text or "").strip()
                    for e in record.iter()
                    if local_name(e.tag) == "creator" and (e.text or "").strip()
                }
            )
        }
        for record in root.iter()
        if local_name(record.tag) == "record"
    ]
