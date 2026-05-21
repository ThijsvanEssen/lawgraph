"""Client for the Dutch Staatsblad via KOOP SRU and repository."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.clients._sru import parse_sru_records
from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import STAATSBLAD_REPO_BASE, STAATSBLAD_SRU_ENDPOINT
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

_STB_ID_PATTERN = re.compile(r"stb-(\d{4})-(\d+)", re.IGNORECASE)


class StaatsbladClient(BaseClient):
    """Client for fetching Staatsblad AMvB publications."""

    def __init__(self, session=None) -> None:
        super().__init__(
            env_var="STAATSBLAD_REPO_BASE",
            default_base_url=STAATSBLAD_REPO_BASE,
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
            query = f"dt.type=AMvB AND dcterms.modified>={since}"

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
                    STAATSBLAD_SRU_ENDPOINT, params=params, timeout=60
                )
                resp.raise_for_status()
                xml_text = resp.text
            except Exception as exc:
                logger.warning(
                    "Staatsblad SRU search failed (startRecord=%d): %s",
                    start_record,
                    exc,
                )
                break

            try:
                root = ET.fromstring(xml_text)
            except ET.ParseError as exc:
                logger.warning("Failed to parse SRU response XML: %s", exc)
                break

            # Strip namespaces for simpler traversal
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
            id_pattern=_STB_ID_PATTERN,
            default_title_prefix="Staatsblad",
        )

    def fetch_publication_xml(self, identifier: str) -> str | None:
        """Fetch the XML for a Staatsblad publication by identifier.

        Tries the direct repository URL first; falls back to SRU lookup on 404.
        Returns the XML text or None if not found.
        """
        m = _STB_ID_PATTERN.search(identifier)
        if not m:
            logger.warning("Cannot parse Staatsblad identifier: %s", identifier)
            return None

        year = m.group(1)
        num = m.group(2).zfill(4)
        clean_id = f"stb-{year}-{num}"

        # Direct URL pattern
        path = f"/frbr/officielepublicaties/stb/{year}/{num}/{clean_id}/xml"
        try:
            resp = self.session.get(
                self.base_url.rstrip("/") + path, timeout=60, allow_redirects=True
            )
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 404:
                logger.debug("Staatsblad XML not found at %s (404)", path)
            else:
                logger.warning(
                    "Unexpected HTTP %d for Staatsblad %s", resp.status_code, identifier
                )
        except Exception as exc:
            logger.warning("Error fetching Staatsblad XML for %s: %s", identifier, exc)

        # Fallback: try alternate URL without zero-padding
        path2 = f"/frbr/officielepublicaties/stb/{year}/{m.group(2)}/{clean_id}/xml"
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

    @staticmethod
    def extract_staatsblad_ref_from_bwb_xml(bwb_xml: str) -> tuple[str, str] | None:
        """Parse BWB toestand XML to find the Staatsblad year and number.

        Returns (year, number) tuple or None if not found.
        Robust to namespace variations.
        """
        ns_strip = re.compile(r"\{[^}]+\}")

        def strip_ns(tag: str) -> str:
            return ns_strip.sub("", tag)

        try:
            root = ET.fromstring(bwb_xml)
        except ET.ParseError as exc:
            logger.debug("Could not parse BWB XML for Staatsblad ref: %s", exc)
            return None

        # Walk the tree looking for publicatieblad-like structures
        found_jaar: str | None = None
        found_nummer: str | None = None
        for elem in root.iter():
            local = strip_ns(elem.tag)
            if local == "publicatiejaar":
                val = (elem.text or "").strip()
                if val.isdigit():
                    found_jaar = val

            if local == "publicatienummer":
                val = (elem.text or "").strip()
                if val:
                    found_nummer = val

        # Also check for stb references in attributes
        if not (found_jaar and found_nummer):
            for elem in root.iter():
                for attr_val in elem.attrib.values():
                    m = _STB_ID_PATTERN.search(attr_val)
                    if m:
                        return m.group(1), m.group(2)

        if found_jaar and found_nummer:
            return found_jaar, found_nummer

        # Try searching text content for stb references
        xml_text = bwb_xml
        m = _STB_ID_PATTERN.search(xml_text)
        if m:
            return m.group(1), m.group(2)

        return None
