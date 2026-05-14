"""Client for the Dutch Staatscourant via KOOP SRU.

Fetches ministeriele regelingen from the official publication platform.
SRU endpoint: https://sru.officielebekendmakingen.nl/sru/Search
Repository: https://repository.overheid.nl

query: dt.type=Ministeriele-regeling
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import STAATSBLAD_REPO_BASE, STAATSCOURANT_SRU_ENDPOINT
from lawgraph.logging import get_logger

logger = get_logger(__name__)

_STCRT_ID_PATTERN = re.compile(r"stcrt-(\d{4})-(\d+)", re.IGNORECASE)
_NS_STRIP = re.compile(r"\{[^}]+\}")


def _strip_ns(tag: str) -> str:
    return _NS_STRIP.sub("", tag)


class StaatscourantClient(BaseClient):
    """Client for fetching Staatscourant ministeriele regelingen publications."""

    def __init__(self, session=None) -> None:
        super().__init__(
            env_var="STAATSBLAD_REPO_BASE",
            default_base_url=STAATSBLAD_REPO_BASE,
            session=session,
        )

    def search_ministeriele_regelingen(
        self, *, since: str | None = None, max_records: int = 20000
    ) -> list[dict[str, Any]]:
        """Search for ministeriele regelingen via the KOOP SRU endpoint."""
        query = "dt.type=Ministeriele-regeling"
        if since:
            query = f"dt.type=Ministeriele-regeling AND dcterms.modified>={since}"

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
            try:
                resp = self.session.get(
                    STAATSCOURANT_SRU_ENDPOINT, params=params, timeout=60
                )
                resp.raise_for_status()
                xml_text = resp.text
            except Exception as exc:
                logger.warning(
                    "Staatscourant SRU search failed (startRecord=%d): %s",
                    start_record,
                    exc,
                )
                break

            try:
                root = ET.fromstring(xml_text)
            except ET.ParseError as exc:
                logger.warning("Failed to parse SRU response XML: %s", exc)
                break

            records_found = self._parse_sru_records(root)
            results.extend(records_found)

            if len(records_found) < page_size:
                break
            start_record += page_size

        logger.info(
            "Staatscourant SRU search returned %d regeling records.", len(results)
        )
        return results

    def _parse_sru_records(self, root: ET.Element) -> list[dict[str, Any]]:
        """Parse SRU response XML into record dicts."""
        records: list[dict[str, Any]] = []

        def find_text(elem: ET.Element, local_name: str) -> str | None:
            for child in elem.iter():
                if _strip_ns(child.tag) == local_name:
                    return (child.text or "").strip() or None
            return None

        for record_elem in root.iter():
            if _strip_ns(record_elem.tag) != "record":
                continue

            identifier = find_text(record_elem, "identifier") or find_text(
                record_elem, "recordIdentifier"
            )
            if not identifier:
                continue

            m = _STCRT_ID_PATTERN.search(identifier)
            if not m:
                continue

            year = m.group(1)
            number = m.group(2)
            title = find_text(record_elem, "title") or f"Staatscourant {year}/{number}"
            content_url = find_text(record_elem, "contentURL")
            date = find_text(record_elem, "date")

            records.append(
                {
                    "identifier": identifier,
                    "year": year,
                    "number": number,
                    "title": title,
                    "content_url": content_url,
                    "date": date,
                }
            )

        return records

    def fetch_publication_xml(self, identifier: str) -> str | None:
        """Fetch the XML for a Staatscourant publication by identifier."""
        m = _STCRT_ID_PATTERN.search(identifier)
        if not m:
            logger.warning("Cannot parse Staatscourant identifier: %s", identifier)
            return None

        year = m.group(1)
        num = m.group(2).zfill(4)
        clean_id = f"stcrt-{year}-{m.group(2)}"

        path = f"/frbr/officielepublicaties/stcrt/{year}/{num}/{clean_id}/xml"
        try:
            resp = self.session.get(
                self.base_url.rstrip("/") + path, timeout=60, allow_redirects=True
            )
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 404:
                logger.debug("Staatscourant XML not found at %s (404)", path)
            else:
                logger.warning(
                    "Unexpected HTTP %d for Staatscourant %s",
                    resp.status_code,
                    identifier,
                )
        except Exception as exc:
            logger.warning(
                "Error fetching Staatscourant XML for %s: %s", identifier, exc
            )

        # Fallback: no zero-padding
        path2 = f"/frbr/officielepublicaties/stcrt/{year}/{m.group(2)}/{clean_id}/xml"
        if path2 != path:
            try:
                resp2 = self.session.get(
                    self.base_url.rstrip("/") + path2, timeout=60, allow_redirects=True
                )
                if resp2.status_code == 200:
                    return resp2.text
            except Exception as exc:
                logger.debug("Fallback fetch failed for %s: %s", identifier, exc)

        return None
