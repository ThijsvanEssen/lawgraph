"""Normalize pipeline for the text of Tweede Kamer documents, from their stored XML.

``retrieve tk-content`` keeps the XML of a document in raw_sources; this reads it, turns it into
the text and the sections of ``core/document_xml.py`` and writes both on the Document node
that ``normalize tk-dossiers`` made of the document. A document without a node is left for a run
after it.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    RAW_KIND_TK_KAMERSTUK_XML,
    SOURCE_TK,
)
from lawgraph.core.amendment_explanation import read_explanation
from lawgraph.core.batching import chunked
from lawgraph.core.document_xml import TEXT_SOURCE, ParsedDocument, parse_document_xml
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.motion_dictum import read_dictum
from lawgraph.db import NodeWriter
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)

# Documents read before their nodes are looked up: the XML of one is up to 2 MB.
_BATCH = 20


class TKContentNormalizePipeline(NormalizePipelineBase[Records]):
    """Write the text and the sections of Kamerstuk XML on the Document nodes."""

    def __init__(
        self, *, store: GraphStore, after: str | None = None, limit: int | None = None
    ) -> None:
        """*after* and *limit*: a slice of a run over all, past that record key, so many
        documents; the log names the last one read."""
        super().__init__(store=store)
        self.after = after
        self.limit = limit
        self.last_record_read: str | None = None

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = super().run(since=since)
        if self.after or self.limit is not None:
            last = self.last_record_read
            logger.info("The last read was %s (go on with --after %s).", last, last)
        return result

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        for record in self._iter_raw_sources(
            source=SOURCE_TK,
            kinds=[RAW_KIND_TK_KAMERSTUK_XML],
            since=since,
            batch_size=_BATCH,
            after=self.after,
            limit=self.limit,
        ):
            self.last_record_read = record.get("_key") or self.last_record_read
            yield record

    def write(self, raw: Records, result: PipelineResult) -> None:
        """Parse the XML records and update the Document node of each. No structural
        edges: the sections are props of the Document."""
        count = 0
        with NodeWriter(self.store) as writer:
            for records in chunked(raw, _BATCH):
                nodes = [n for r in records if (n := self._node(r)) is not None]
                known = self.store.existing_keys(
                    COLLECTION_DOCUMENTS, [n.key for n in nodes if n.key]
                )
                for node in nodes:
                    if node.key in known:
                        writer.add(node)
                        count += 1
                    else:
                        self.progress.skip("no Document node yet", node.key)
        logger.info("Kamerstuk XML normalize: %d papers processed.", count)

    def _node(self, record: dict[str, Any]) -> Node | None:
        identifier = record.get("external_id") or record.get("_key")
        key = self._meta(record).get("document")
        xml = self._payload_text(record)
        if not key or not xml:
            self.progress.skip("no document or XML", identifier)
            return None
        parsed = parse_document_xml(xml)
        if not parsed.text:
            self.progress.skip("no text in the XML", identifier)
            return None
        return Node(
            collection=COLLECTION_DOCUMENTS,
            key=str(key),
            props=document_props(parsed),
        )


def document_props(parsed: ParsedDocument) -> dict[str, Any]:
    """The props of a Document that a parsed Kamerstuk XML fills (see docs/data-model.md)."""
    sections = [section.as_dict() for section in parsed.sections]
    return {
        "text": parsed.text,
        "text_source": TEXT_SOURCE,
        "text_truncated": parsed.truncated,
        "xml_dialect": parsed.dialect,
        "structure_quality": parsed.structure_quality,
        "budget": parsed.budget,
        "sections": sections,
        "footnotes": parsed.footnotes,
        # what a motion asks or says ("verzoekt de regering …"); null for any other document
        "dictum": read_dictum(parsed.text),
        # what an amendment is for, as its Toelichting opens; null for any other document
        "explanation": read_explanation(parsed.text, sections),
    }
