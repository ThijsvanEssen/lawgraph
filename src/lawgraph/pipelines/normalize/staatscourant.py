"""Normalize pipeline for Dutch Staatscourant ministeriele regelingen."""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    RAW_KIND_STCRT_REGELING,
    SOURCE_STAATSCOURANT,
)
from lawgraph.core.identifiers import STCRT_ID_PATTERN, find_bwb_id
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.publication_xml import publication_title
from lawgraph.core.time import iso_date
from lawgraph.core.xml import find_text, text_of
from lawgraph.db import NodeWriter
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)


class StaatscourantNormalizePipeline(NormalizePipelineBase):
    """Normalize Staatscourant ministeriele regelingen XML into Publication nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_STAATSCOURANT,
            kinds=[RAW_KIND_STCRT_REGELING],
            since=since,
            batch_size=20,
        )

    def normalize_nodes(
        self, raw: Iterable[dict[str, Any]], result: PipelineResult
    ) -> int:
        count = 0
        writer = NodeWriter(self.store)

        for record in raw:
            identifier = record.get("external_id") or record.get("identifier") or ""
            payload_text = self._payload_text(record)
            if not payload_text:
                logger.warning(
                    "Staatscourant record %s has no text payload; skipping.", identifier
                )
                result.skipped += 1
                continue

            node = self._parse_publication(identifier, payload_text)
            if node is None:
                result.skipped += 1
                continue

            writer.add(node)
            count += 1

        writer.flush()

        logger.info("Staatscourant normalize: %d publications processed.", count)
        return count

    def _parse_publication(self, identifier: str, xml_text: str) -> Node | None:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.warning(
                "Failed to parse Staatscourant XML for %s: %s", identifier, exc
            )
            return None

        m = STCRT_ID_PATTERN.search(identifier)
        year = m.group(1) if m else ""
        number = m.group(2) if m else ""

        title = publication_title(root, f"Staatscourant {year}/{number}")

        # Extract the full text of the regulation
        text = find_text(root, "tekst", "body", "inhoud")
        if not text:
            text = text_of(root, " ")[:100000]

        bwb_id = find_bwb_id(xml_text)
        date = iso_date(find_text(root, "publicatiedatum", "datum"))

        props: dict[str, Any] = {
            "source": SOURCE_STAATSCOURANT,
            "identifier": identifier,
            "kind": "Ministeriële regeling",
            "title": title,
            "text": text or "",
            "year": year,
            "number": number,
            "display_name": (
                f"Stcrt. {year}/{number}: {title[:100]}" if title else identifier
            ),
        }
        if bwb_id:
            props["bwb_id"] = bwb_id
        if date:
            props["date"] = date

        key = make_node_key("stcrt", identifier)
        return Node(
            collection=COLLECTION_DOCUMENTS,
            type=NodeType.DOCUMENT,
            key=key,
            labels=["Staatscourant", "Regeling"],
            props=props,
        )

    def build_edges(self, raw: Iterable[dict[str, Any]], normalized: int) -> None:
        """No structural edges here — the semantic pipeline writes EXPLAINS."""
