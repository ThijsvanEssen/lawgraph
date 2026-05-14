"""Normalize pipeline for Dutch Staatscourant ministeriele regelingen."""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.settings import (
    COLLECTION_PUBLICATIONS,
    RAW_KIND_STCRT_REGELING,
    SOURCE_STAATSCOURANT,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)

_NS_STRIP = re.compile(r"\{[^}]+\}")
_STCRT_ID_PATTERN = re.compile(r"stcrt-(\d{4})-(\d+)", re.IGNORECASE)
_BWBR_PATTERN = re.compile(r"\b(BWBR0\d{6})\b", re.IGNORECASE)


def _strip_ns(tag: str) -> str:
    return _NS_STRIP.sub("", tag)


def _find_text(elem: ET.Element, *local_names: str) -> str | None:
    for child in elem.iter():
        if _strip_ns(child.tag) in local_names:
            text = "".join(child.itertext()).strip()
            if text:
                return text
    return None


class StaatscourantNormalizePipeline(NormalizePipeline):
    """Normalize Staatscourant ministeriele regelingen XML into Publication nodes."""

    def __init__(self, *, store: Any) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> list[dict[str, Any]]:
        rows = self._query_raw_sources(
            source=SOURCE_STAATSCOURANT,
            kinds=[RAW_KIND_STCRT_REGELING],
            since=since,
        )
        logger.info("Loaded %d Staatscourant raw_sources.", len(rows))
        return rows

    def normalize_nodes(self, raw: list[dict[str, Any]]) -> dict[str, Node]:
        nodes: dict[str, Node] = {}

        for record in raw:
            identifier = record.get("external_id") or record.get("identifier") or ""
            payload_text = self._payload_text(record)
            if not payload_text:
                logger.warning(
                    "Staatscourant record %s has no text payload; skipping.", identifier
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

        logger.info("Staatscourant normalize: %d publications processed.", len(nodes))
        return nodes

    def _parse_publication(self, identifier: str, xml_text: str) -> Node | None:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.warning(
                "Failed to parse Staatscourant XML for %s: %s", identifier, exc
            )
            return None

        m = _STCRT_ID_PATTERN.search(identifier)
        year = m.group(1) if m else ""
        number = m.group(2) if m else ""

        title = (
            _find_text(root, "citeertitel")
            or _find_text(root, "officiele-titel", "officieletitel")
            or _find_text(root, "titel")
            or f"Staatscourant {year}/{number}"
        )

        # Extract the full text of the regulation
        tekst = _find_text(root, "tekst", "body", "inhoud")
        if not tekst:
            tekst = " ".join(root.itertext()).strip()[:100000]

        bwb_id: str | None = None
        bwb_m = _BWBR_PATTERN.search(ET.tostring(root, encoding="unicode"))
        if bwb_m:
            bwb_id = bwb_m.group(1).upper()

        date_text = _find_text(root, "publicatiedatum", "datum")

        props: dict[str, Any] = {
            "source": SOURCE_STAATSCOURANT,
            "identifier": identifier,
            "soort": "Ministeriële regeling",
            "title": title,
            "text": tekst or "",
            "year": year,
            "number": number,
            "display_name": (
                f"Stcrt. {year}/{number}: {title[:100]}" if title else identifier
            ),
        }
        if bwb_id:
            props["bwb_id"] = bwb_id
        if date_text:
            props["datum"] = date_text[:10]

        key = make_node_key("stcrt", identifier)
        return Node(
            collection=COLLECTION_PUBLICATIONS,
            type=NodeType.PUBLICATION,
            key=key,
            labels=["Staatscourant", "Regeling"],
            props=props,
        )

    def build_edges(
        self, raw: list[dict[str, Any]], normalized: dict[str, Node]
    ) -> int:
        return 0
