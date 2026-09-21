"""Normalize pipeline for the text of Tweede Kamer papers, from their stored XML.

``retrieve tk-content`` keeps the XML of a paper in raw_sources; this reads it, turns it into
the text and the sections of ``core/kamerstuk_xml.py`` and writes both on the Document node
that ``normalize tk-dossiers`` made of the paper. A paper without a node is left for a run
after it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    RAW_KIND_TK_KAMERSTUK_XML,
    SOURCE_TK,
)
from lawgraph.core.batching import chunked
from lawgraph.core.kamerstuk_xml import TEXT_SOURCE, ParsedKamerstuk, parse_kamerstuk
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db import NodeWriter
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

# Papers read before their nodes are looked up: the XML of one is up to 2 MB.
_BATCH = 20


class TKContentNormalizePipeline(NormalizePipelineBase):
    """Write the text and the sections of Kamerstuk XML on the Document nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_TK,
            kinds=[RAW_KIND_TK_KAMERSTUK_XML],
            since=since,
            batch_size=_BATCH,
        )

    def normalize_nodes(
        self, raw: Iterable[dict[str, Any]], result: PipelineResult
    ) -> int:
        """Parse the XML records and update the Document node of each."""
        count = 0
        with NodeWriter(self.store) as writer:
            for records in chunked(raw, _BATCH):
                nodes = [n for r in records if (n := self._node(r, result)) is not None]
                known = self.store.existing_keys(
                    COLLECTION_DOCUMENTS, [n.key for n in nodes if n.key]
                )
                for node in nodes:
                    if node.key in known:
                        writer.add(node)
                        count += 1
                    else:
                        logger.debug("No Document node %s yet; skipping.", node.key)
                        result.skipped += 1
        logger.info("Kamerstuk XML normalize: %d papers processed.", count)
        return count

    def _node(self, record: dict[str, Any], result: PipelineResult) -> Node | None:
        identifier = record.get("external_id") or ""
        key = self._meta(record).get("document")
        xml = self._payload_text(record)
        if not key or not xml:
            logger.warning(
                "Kamerstuk record %s has no document or XML; skipping.", identifier
            )
            result.skipped += 1
            return None
        parsed = parse_kamerstuk(xml)
        if not parsed.text:
            logger.warning("Kamerstuk XML of %s has no text; skipping.", identifier)
            result.skipped += 1
            return None
        return Node(
            collection=COLLECTION_DOCUMENTS,
            type=NodeType.DOCUMENT,
            key=str(key),
            props=document_props(parsed),
        )

    def build_edges(self, raw: Iterable[dict[str, Any]], normalized: int) -> None:
        """No structural edges here: the sections are props of the Document."""


def document_props(parsed: ParsedKamerstuk) -> dict[str, Any]:
    """The props of a Document that a parsed Kamerstuk XML fills (see docs/data-model.md)."""
    return {
        "text": parsed.text,
        "text_source": TEXT_SOURCE,
        "text_truncated": parsed.truncated,
        "xml_dialect": parsed.dialect,
        "structure_quality": parsed.structure_quality,
        "budget": parsed.budget,
        "sections": [section.as_dict() for section in parsed.sections],
        "footnotes": parsed.footnotes,
    }
