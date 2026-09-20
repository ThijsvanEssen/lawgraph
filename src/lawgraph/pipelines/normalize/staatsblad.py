"""Normalize pipeline for Dutch Staatsblad AMvB publications."""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    RAW_KIND_STB_AMVB,
    SOURCE_STAATSBLAD,
)
from lawgraph.core.identifiers import STB_ID_PATTERN
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.publication_xml import bwb_id_in_xml, publication_title
from lawgraph.core.xml import extract_section_text, find_text
from lawgraph.db import NodeWriter
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)


class StaatsbladNormalizePipeline(NormalizePipelineBase):
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
        writer = NodeWriter(self.store)

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

            writer.add(node)
            nodes[identifier] = node

        writer.flush()

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
        m = STB_ID_PATTERN.search(identifier)
        if m:
            year = m.group(1)
            number = m.group(2)
        else:
            year_text = find_text(root, "publicatiejaar")
            number_text = find_text(root, "publicatienummer")
            year = year_text or ""
            number = number_text or ""

        # Extract title
        title = publication_title(root, f"Staatsblad {year}/{number}")

        # Extract NvT text from nota-van-toelichting section
        nvt_text = extract_section_text(
            root, "nota-van-toelichting", "nota_van_toelichting"
        )
        if not nvt_text:
            nvt_text = extract_section_text(root, "toelichting")

        # Try to extract BWB ID from grondslagen or other references
        bwb_id = bwb_id_in_xml(root)

        props: dict[str, Any] = {
            "source": SOURCE_STAATSBLAD,
            "identifier": identifier,
            "kind": "Nota van toelichting",
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
            collection=COLLECTION_DOCUMENTS,
            type=NodeType.DOCUMENT,
            key=key,
            labels=["Staatsblad", "NvT"],
            props=props,
        )

    def build_edges(
        self, raw: list[dict[str, Any]], normalized: dict[str, Node]
    ) -> None:
        """No structural edges here — the semantic pipeline writes EXPLAINS."""
