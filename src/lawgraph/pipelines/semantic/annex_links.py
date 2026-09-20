"""Semantic pipeline that makes annexes first-class nodes and links articles to them.

Two passes:

1. **XML pass** — parse ``<bijlage>`` elements from the raw BWB XML into
   ``annexes`` nodes (title, description, structured entries) plus
   PART_OF edges (annex → owning instrument).
2. **Text pass** — detect annex references in article texts and write
   SCOPED_BY edges (article → annex) carrying the detected scope_type
   (fixed vs. discretionary). References to annexes the XML pass did not
   produce get a stub node so the graph stays connected.
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_BWB_REGELING,
    RAW_KIND_BWB_TOESTAND,
    RELATION_PART_OF,
    RELATION_SCOPED_BY,
    SOURCE_BWB,
)
from lawgraph.core.annex_xml import extract_description, extract_entries, extract_kop
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.xml import iter_named
from lawgraph.pipelines.semantic.annex_detect import detect_annex_references
from lawgraph.pipelines.semantic.base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "bwb-annex-links"


class AnnexLinksSemanticPipeline(SemanticPipelineBase):
    """Extract annex nodes from BWB XML and link referencing articles."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        known_keys = self._extract_annexes_from_xml(result)
        self._link_articles(result, known_keys)
        logger.info("Annex links: %s.", result.summary())
        return result

    # ── pass 1: XML extraction ─────────────────────────────────────────────

    def _extract_annexes_from_xml(self, result: PipelineResult) -> set[str]:
        """Parse ``<bijlage>`` elements from raw BWB XML into annex nodes."""
        known_keys: set[str] = set()
        node_docs: list[dict[str, Any]] = []
        edge_docs: list[dict[str, Any]] = []

        for record in self._load_raw_bwb_records():
            bwb_id = self._record_bwb_id(record)
            payload = record.get("payload_text")
            if not bwb_id or not payload:
                continue
            try:
                root = ET.fromstring(payload)
            except ET.ParseError as exc:
                logger.debug("Annex XML parse failed for %s: %s", bwb_id, exc)
                continue

            for element in iter_named(root, "bijlage"):
                node = self._build_annex_node(bwb_id, element)
                if node is None or not node.key or node.key in known_keys:
                    continue
                known_keys.add(node.key)
                node_docs.append(node.to_document())
                edge = self._instrument_edge(bwb_id, node)
                if edge:
                    edge_docs.append(edge)

        if node_docs:
            created, updated = self.store.bulk_insert_or_update_nodes(
                COLLECTION_ANNEXES, node_docs
            )
            result.created += created
            result.updated += updated
        if edge_docs:
            self._flush_edge_batch(edge_docs, result)
        logger.info("Extracted %d annexes from BWB XML.", len(known_keys))
        return known_keys

    def _load_raw_bwb_records(self) -> Iterable[dict[str, Any]]:
        aql = """
        FOR raw IN raw_sources
            FILTER raw.source == @source
            FILTER raw.kind IN @kinds
            FILTER raw.payload_text != null
            RETURN { payload_text: raw.payload_text, meta: raw.meta,
                     external_id: raw.external_id }
        """
        return self.store.query(
            aql,
            {
                "source": SOURCE_BWB,
                "kinds": [RAW_KIND_BWB_REGELING, RAW_KIND_BWB_TOESTAND],
            },
            batch_size=20,  # payloads are full XML documents — keep batches small
        )

    @staticmethod
    def _record_bwb_id(record: dict[str, Any]) -> str | None:
        meta = record.get("meta") or {}
        return meta.get("bwb_id") or record.get("external_id")

    def _build_annex_node(self, bwb_id: str, element: ET.Element) -> Node | None:
        label, title = extract_kop(element)
        entries = extract_entries(element)
        description = extract_description(element)
        display = title or (f"Annex {label}" if label else "Annex")
        props: dict[str, Any] = {
            "source": SOURCE_BWB,
            "bwb_id": bwb_id,
            "label": label,
            "title": title,
            "display_name": display,
            "description": description,
            "entries": entries or None,
            "instrument_id": f"{COLLECTION_INSTRUMENTS}/{make_node_key(bwb_id)}",
        }
        return Node(
            collection=COLLECTION_ANNEXES,
            type=NodeType.ANNEX,
            key=annex_node_key(bwb_id, label),
            labels=["BWB", "Annex"],
            props=props,
        )

    def _instrument_edge(self, bwb_id: str, annex: Node) -> dict[str, Any] | None:
        instrument = Node(
            collection=COLLECTION_INSTRUMENTS,
            type=NodeType.INSTRUMENT,
            key=make_node_key(bwb_id),
            props={},
            _skip_validation=True,
        )
        return self._make_edge_doc(
            from_node=annex,
            to_node=instrument,
            relation=RELATION_PART_OF,
            source=SEMANTIC_SOURCE,
            confidence=1.0,
        )

    # ── pass 2: article text linking ───────────────────────────────────────

    def _link_articles(self, result: PipelineResult, known_keys: set[str]) -> None:
        edge_batch: list[dict[str, Any]] = []
        for doc in self._load_articles_mentioning_annex():
            article = Node.from_document(COLLECTION_ARTICLES, doc)
            text = article.props.get("text") or ""
            bwb_id = str(article.props.get("bwb_id") or "")
            if not text or not bwb_id:
                result.skipped += 1
                continue
            for hit in detect_annex_references(text):
                annex = self._ensure_annex(bwb_id, hit.label, known_keys)
                if annex is None:
                    continue
                edge = self._make_edge_doc(
                    from_node=article,
                    to_node=annex,
                    relation=RELATION_SCOPED_BY,
                    source=SEMANTIC_SOURCE,
                    confidence=0.9 if hit.label else 0.7,
                    meta={
                        "start": hit.start,
                        "end": hit.end,
                        "text": hit.text,
                        "scope_type": hit.scope_type,
                    },
                )
                if edge:
                    edge_batch.append(edge)
                    if len(edge_batch) >= self._EDGE_BATCH_SIZE:
                        created, updated = self._flush_edge_batch(edge_batch, result)
                        result.created += created
                        result.updated += updated
                        edge_batch = []
        if edge_batch:
            created, updated = self._flush_edge_batch(edge_batch, result)
            result.created += created
            result.updated += updated

    def _load_articles_mentioning_annex(self) -> Iterable[dict[str, Any]]:
        aql = f"""
        FOR doc IN {COLLECTION_ARTICLES}
            FILTER doc.props.text != null
            FILTER CONTAINS(LOWER(doc.props.text), 'bijlage')
            RETURN doc
        """
        return self.store.query(aql)

    def _ensure_annex(
        self, bwb_id: str, label: str | None, known_keys: set[str]
    ) -> Node | None:
        """Return the annex node for (bwb_id, label), creating a stub if needed."""
        key = annex_node_key(bwb_id, label)
        if key in known_keys:
            return Node(
                collection=COLLECTION_ANNEXES,
                type=NodeType.ANNEX,
                key=key,
                props={},
                _skip_validation=True,
            )
        node = self.store.ensure_stub_node(
            COLLECTION_ANNEXES,
            key,
            NodeType.ANNEX,
            {
                "bwb_id": bwb_id,
                "label": label,
                "display_name": f"Annex {label}".strip() if label else "Annex",
                "source": SOURCE_BWB,
            },
        )
        if node is not None:
            known_keys.add(key)
        return node


def annex_node_key(bwb_id: str, label: str | None) -> str:
    """Deterministic annex key: ``<bwb_id>_annex[_<label>]``."""
    return make_node_key(bwb_id, "annex", label)
