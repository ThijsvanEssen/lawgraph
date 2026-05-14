"""Normalize pipeline for Dutch Staatsblad AMvB publications."""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.settings import (
    COLLECTION_PUBLICATIONS,
    RAW_KIND_STB_AMVB,
    SOURCE_STAATSBLAD,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)

_NS_STRIP = re.compile(r"\{[^}]+\}")
_STB_ID_PATTERN = re.compile(r"stb-(\d{4})-(\d+)", re.IGNORECASE)


def _strip_ns(tag: str) -> str:
    return _NS_STRIP.sub("", tag)


def _find_text(elem: ET.Element, *local_names: str) -> str | None:
    """Find the first element whose local name matches any of local_names, return its text."""
    for child in elem.iter():
        if _strip_ns(child.tag) in local_names:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return None


def _extract_section_text(elem: ET.Element, *section_names: str) -> str | None:
    """Find a section element by local name and return all its itertext."""
    for child in elem.iter():
        if _strip_ns(child.tag) in section_names:
            text = " ".join(child.itertext()).strip()
            return text if text else None
    return None


class StaatsbladNormalizePipeline(NormalizePipeline):
    """Normalize Staatsblad AMvB XML into Publication nodes."""

    def __init__(self, *, store: Any) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> list[dict[str, Any]]:
        rows = self._query_raw_sources(
            source=SOURCE_STAATSBLAD,
            kinds=[RAW_KIND_STB_AMVB],
            since=since,
        )
        logger.info("Loaded %d Staatsblad raw_sources.", len(rows))
        return rows

    def normalize_nodes(self, raw: list[dict[str, Any]]) -> dict[str, Node]:
        """Parse Staatsblad XML into Publication nodes."""
        nodes: dict[str, Node] = {}

        for record in raw:
            identifier = record.get("external_id") or ""
            payload_text = self._payload_text(record)
            if not payload_text:
                logger.warning(
                    "Staatsblad record %s has no text payload; skipping.", identifier
                )
                self._result.skipped += 1
                continue

            node = self._parse_publication(identifier, payload_text)
            if node is None:
                self._result.skipped += 1
                continue

            node = self.store.insert_or_update(node)
            nodes[identifier] = node
            self._result.created += 1

        logger.info("Staatsblad normalize: %d publications processed.", len(nodes))
        return nodes

    def _parse_publication(self, identifier: str, xml_text: str) -> Node | None:
        """Parse a Staatsblad XML document into a Publication Node."""
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.warning("Failed to parse Staatsblad XML for %s: %s", identifier, exc)
            return None

        # Extract year and number from identifier or XML
        m = _STB_ID_PATTERN.search(identifier)
        if m:
            year = m.group(1)
            number = m.group(2)
        else:
            year_text = _find_text(root, "publicatiejaar")
            number_text = _find_text(root, "publicatienummer")
            year = year_text or ""
            number = number_text or ""

        # Extract title
        title = (
            _find_text(root, "citeertitel")
            or _find_text(root, "officiele-titel", "officieletitel")
            or _find_text(root, "titel")
            or f"Staatsblad {year}/{number}"
        )

        # Extract NvT text from nota-van-toelichting section
        nvt_text = _extract_section_text(
            root, "nota-van-toelichting", "nota_van_toelichting"
        )
        if not nvt_text:
            nvt_text = _extract_section_text(root, "toelichting")

        # Try to extract BWB ID from grondslagen or other references
        bwb_id = _extract_bwb_id(root)

        props: dict[str, Any] = {
            "source": SOURCE_STAATSBLAD,
            "identifier": identifier,
            "soort": "Nota van toelichting",
            "title": title,
            "text": nvt_text or "",
            "year": year,
            "number": number,
            "display_name": f"Nota van toelichting {identifier}",
        }
        if bwb_id:
            props["bwb_id"] = bwb_id

        key = make_node_key("stb", identifier)
        return Node(
            collection=COLLECTION_PUBLICATIONS,
            type=NodeType.PUBLICATION,
            key=key,
            labels=["Staatsblad", "NvT"],
            props=props,
        )

    def build_edges(
        self, raw: list[dict[str, Any]], normalized: dict[str, Node]
    ) -> int:
        """No structural edges created here — the semantic pipeline creates EXPLAINS_INSTRUMENT."""
        return 0


def _extract_bwb_id(root: ET.Element) -> str | None:
    """Try to extract a BWB ID from the Staatsblad XML."""
    bwb_pattern = re.compile(r"\b(BWBR0\d{6})\b", re.IGNORECASE)

    # Check all text content for BWBR references
    xml_text = ET.tostring(root, encoding="unicode")
    m = bwb_pattern.search(xml_text)
    if m:
        return m.group(1).upper()

    return None
