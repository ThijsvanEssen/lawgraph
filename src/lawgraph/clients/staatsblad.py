"""Client for the Dutch Staatsblad via KOOP SRU and repository."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.clients._sru import (
    fetch_publication_xml,
    parse_sru_records,
    raise_on_diagnostic,
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

    def search_amvbs(
        self, *, since: str | None = None, max_records: int = 20000
    ) -> list[dict[str, Any]]:
        """Search for AMvB publications via the KOOP SRU endpoint.

        Returns a list of dicts with keys: identifier, year, number, title, content_url.
        """
        query = "dt.type=AMvB"
        if since:
            query = f"dt.type=AMvB AND dt.modified>={since}"

        results: list[dict[str, Any]] = []
        page_size = 100
        start_record = 1

        while start_record <= max_records:
            params = {
                "operation": "searchRetrieve",
                "version": "1.2",
                "x-connection": "ob",
                "query": query,
                "maximumRecords": str(page_size),
                "startRecord": str(start_record),
                "recordSchema": "gzd",
            }
            resp = self._get_raw_absolute_with_retry(
                STAATSBLAD_SRU_ENDPOINT, params=params, timeout=60
            )
            root = ET.fromstring(resp.text)
            raise_on_diagnostic(root, context=f"Staatsblad startRecord={start_record}")

            records_found = self._parse_sru_records(root)
            results.extend(records_found)

            if len(records_found) < page_size:
                break
            start_record += page_size

        logger.info("Staatsblad SRU search returned %d AMvB records.", len(results))
        return results

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
