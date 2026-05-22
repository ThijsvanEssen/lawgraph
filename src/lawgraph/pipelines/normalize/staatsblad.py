"""Normalize pipeline for Dutch Staatsblad AMvB publications."""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_PUBLICATIONS,
    RAW_KIND_STB_AMVB,
    SOURCE_STAATSBLAD,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize._xml import extract_section_text, find_text
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)

_STB_ID_PATTERN = re.compile(r"stb-(\d{4})-(\d+)", re.IGNORECASE)


class StaatsbladNormalizePipeline(NormalizePipeline):
    """Normalize Staatsblad AMvB XML into Publication nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> list[dict[str, Any]]:
        rows = self._query_raw_sources(
            source=SOURCE_STAATSBLAD,
            kinds=[RAW_KIND_STB_AMVB],
            since=since,
        )
        logger.info("Loaded %d Staatsblad raw_sources.", len(rows))
        return rows

    def normalize_nodes(
        self, raw: list[dict[str, Any]], result: PipelineResult
    ) -> dict[str, Node]:
        """Parse Staatsblad XML into Publication nodes."""
        nodes: dict[str, Node] = {}

        for record in raw:
            identifier = record.get("external_id") or ""
            payload_text = self._payload_text(record)
            if not payload_text:
                logger.warning(
                    "Staatsblad record %s has no text payload; skipping.", identifier
                )
                result.skipped += 1
                continue

            node = self._parse_publication(identifier, payload_text)
            if node is None:
                result.skipped += 1
                continue

            node = self.store.insert_or_update(node)
            nodes[identifier] = node
            result.created += 1

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
            year_text = find_text(root, "publicatiejaar")
            number_text = find_text(root, "publicatienummer")
            year = year_text or ""
            number = number_text or ""

        # Extract title
        title = (
            find_text(root, "citeertitel")
            or find_text(root, "officiele-titel", "officieletitel")
            or find_text(root, "titel")
            or f"Staatsblad {year}/{number}"
        )

        # Extract NvT text from nota-van-toelichting section
        nvt_text = extract_section_text(
            root, "nota-van-toelichting", "nota_van_toelichting"
        )
        if not nvt_text:
            nvt_text = extract_section_text(root, "toelichting")

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
