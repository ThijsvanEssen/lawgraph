"""Client for the Dutch Staatsblad via KOOP SRU and repository."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.clients._sru import (
    fetch_publication_xml,
    parse_sru_records,
    search_publications,
)
from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import STAATSBLAD_REPO_BASE, STAATSBLAD_SRU_ENDPOINT
from lawgraph.core.identifiers import STB_ID_PATTERN
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)


class StaatsbladClient(BaseClient):
    """Client for fetching Staatsblad AMvB publications."""

    def __init__(self, session=None) -> None:
        super().__init__(
            base_url=STAATSBLAD_REPO_BASE,
            session=session,
        )

    def search_amvbs(self, *, since: str | None = None) -> list[dict[str, Any]]:
        """Search the KOOP SRU for AMvB publications, ``since`` on ``dt.modified``.

        Returns dicts with keys: identifier, year, number, title, content_url.
        """
        query = "dt.type=AMvB"
        if since:
            query += f" AND dt.modified>={since}"
        records = search_publications(
            self,
            STAATSBLAD_SRU_ENDPOINT,
            query=query,
            parse=self._parse_sru_records,
            context="Staatsblad",
        )
        logger.info("Staatsblad SRU search returned %d records.", len(records))
        return records

    def _parse_sru_records(self, root: ET.Element) -> list[dict[str, Any]]:
        """Parse SRU response XML into a list of record dicts."""
        return parse_sru_records(
            root,
            id_pattern=STB_ID_PATTERN,
            default_title_prefix="Staatsblad",
        )

    def fetch_publication_xml(self, identifier: str) -> str | None:
        """The XML of a Staatsblad publication, or ``None`` when the repository has none."""
        return fetch_publication_xml(self, "stb", STB_ID_PATTERN, identifier)
