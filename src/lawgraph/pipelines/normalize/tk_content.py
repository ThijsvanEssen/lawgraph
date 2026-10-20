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
    RAW_BATCH_SIZE,
    RAW_KIND_TK_KAMERSTUK_XML,
    SOURCE_TK,
)
from lawgraph.core.amendment_explanation import read_explanation
from lawgraph.core.batching import chunked
from lawgraph.core.document_xml import TEXT_SOURCE, ParsedDocument, parse_document_xml
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.motion_dictum import read_dictum
from lawgraph.core.raw_records import meta, payload_text
from lawgraph.core.tk_records.kinds import is_amendment, is_motion
from lawgraph.db import NodeWriter
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.db.store import GraphStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)

# Documents read before their nodes are looked up (the XML of one is up to 2 MB): a batch.
_BATCH = RAW_BATCH_SIZE[RAW_KIND_TK_KAMERSTUK_XML]


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
            after=self.after,
            limit=self.limit,
        ):
            self.last_record_read = record.get("key") or self.last_record_read
            yield record

    def write(self, raw: Records, result: PipelineResult) -> None:
        """Parse the XML records and update the Document node of each. No structural
        edges: the sections are props of the Document."""
        count = 0
        with NodeWriter(self.store) as writer:
            for records in chunked(raw, _BATCH):
                read = [d for r in records if (d := self._parsed(r)) is not None]
                kinds = normalize_tk.document_kinds(
                    self.store, [key for key, _ in read]
                )
                for key, parsed in read:
                    if key in kinds:
                        props = document_props(parsed, kind=kinds[key])
                        writer.add(
                            Node(collection=COLLECTION_DOCUMENTS, key=key, props=props)
                        )
                        count += 1
                    else:
                        self.progress.skip("no Document node yet", key)
        logger.info("Kamerstuk XML normalize: %d papers processed.", count)

    def _parsed(self, record: dict[str, Any]) -> tuple[str, ParsedDocument] | None:
        """The key of the Document a record is the XML of, and that XML read; None for a
        record without either or whose XML has no text."""
        identifier = record.get("external_id") or record.get("key")
        key = meta(record).get("document")
        xml = payload_text(record)
        if not key or not xml:
            self.progress.skip("no document or XML", identifier)
            return None
        try:
            parsed = parse_document_xml(xml)
        except ValueError as exc:  # the Document keeps what it has
            self.progress.note(
                "Kamerstuk XML that does not read", f"{identifier}: {exc}"
            )
            self.progress.skip("XML that does not read", identifier)
            return None
        if parsed.unstructured:
            self.progress.note(
                "Kamerstuk XML without sections (its text only)",
                f"{identifier}: {parsed.unstructured}",
            )
        if not parsed.text:
            self.progress.skip("no text in the XML", identifier)
            return None
        return str(key), parsed


def document_props(parsed: ParsedDocument, *, kind: str | None) -> dict[str, Any]:
    """The props of a Document of *kind* that a parsed Kamerstuk XML fills (see
    docs/data-model.md)."""
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
        # what a motion asks or says ("verzoekt de regering …"); null for any other document,
        # also a letter or a report that quotes a motion whole
        "dictum": read_dictum(parsed.text) if is_motion(kind) else None,
        # what an amendment is for, as its Toelichting opens; null for any other document
        "explanation": (
            read_explanation(parsed.text, sections) if is_amendment(kind) else None
        ),
    }
