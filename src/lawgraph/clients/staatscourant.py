"""Client for the Dutch Staatscourant via KOOP SRU.

Fetches ministeriele regelingen from the official publication platform.
SRU endpoint: https://repository.overheid.nl/sru
Repository: https://repository.overheid.nl

query: dt.type=Ministeriele-regeling
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.clients._sru import (
    count_records,
    fetch_publication_xml,
    parse_sru_records,
    raise_on_diagnostic,
)
from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import STAATSCOURANT_REPO_BASE, STAATSCOURANT_SRU_ENDPOINT
from lawgraph.core.identifiers import STCRT_ID_PATTERN
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)


class StaatscourantClient(BaseClient):
    """Client for fetching Staatscourant ministeriele regelingen publications."""

    def __init__(self, session=None) -> None:
        super().__init__(
            base_url=STAATSCOURANT_REPO_BASE,
            session=session,
        )

    def search_ministeriele_regelingen(
        self, *, since: str | None = None, max_records: int = 20000
    ) -> list[dict[str, Any]]:
        """Search for ministeriele regelingen via the KOOP SRU endpoint."""
        query = "dt.type=Ministeriele-regeling"
        if since:
            query = f"dt.type=Ministeriele-regeling AND dt.modified>={since}"

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
                STAATSCOURANT_SRU_ENDPOINT, params=params, timeout=60
            )
            root = ET.fromstring(resp.text)
            raise_on_diagnostic(
                root, context=f"Staatscourant startRecord={start_record}"
            )

            records_found = self._parse_sru_records(root)
            results.extend(records_found)

            if count_records(root) < page_size:
                break
            start_record += page_size

        logger.info(
            "Staatscourant SRU search returned %d regeling records.", len(results)
        )
        return results

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
