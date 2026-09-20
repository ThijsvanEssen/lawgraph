"""Semantic linkage pipeline for Rechtspraak judgments and BWB articles."""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    RAW_KIND_RS_CONTENT,
    RELATION_REFERS_TO,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.citations import CitationHit, hit_reason, strip_xml
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import describe_since, iso_timestamp

from .base import JUDGMENT_BATCH_SIZE, JUDGMENT_TEXT, SemanticPipelineBase
from .detection import build_extractor, detect_in_text

logger = get_logger(__name__)


SEMANTIC_SOURCE = "rechtspraak-article-linker"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class RechtspraakArticlesSemanticPipeline(SemanticPipelineBase):
    """Link Rechtspraak judgments to BWB articles via semantic edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)
        eclis = self._recent_rechtspraak_eclis(since_iso)
        if eclis is not None and not eclis:
            logger.info(
                "No Rechtspraak judgments were fetched since %s; nothing to link.",
                describe_since(since),
            )
            return result

        mapping = self._load_code_aliases()
        instrument_aliases = self._load_instrument_aliases()
        if not mapping and not instrument_aliases:
            logger.warning("No code or name aliases configured; skipping linkage.")
            return result

        extractor = build_extractor(mapping, instrument_aliases)

        logger.info(
            "Processing Rechtspraak judgments for article references (since=%s).",
            describe_since(since),
        )

        edge_batch: list[dict[str, Any]] = []
        judgment_count = 0

        # The judgments stream from the cursor: each carries its whole XML.
        for doc in self._load_judgments(eclis):
            judgment_count += 1
            judgment = Node.from_document(COLLECTION_JUDGMENTS, doc)
            raw_text = self._extract_judgment_text(judgment)
            text = strip_xml(raw_text) if raw_text else None
            hits = detect_in_text(text or "", extractor)
            if not hits:
                continue

            for hit in hits:
                if hit.kind != "article":
                    continue

                article = self._resolve_article(hit)
                if article is None:
                    continue

                edge_doc = self._make_edge_doc(
                    from_node=judgment,
                    to_node=article,
                    relation=RELATION_REFERS_TO,
                    source=SEMANTIC_SOURCE,
                    confidence=hit.confidence,
                    meta={
                        k: v
                        for k, v in {
                            "raw_match": hit.raw_match,
                            "snippet": hit.snippet,
                            "reason": hit_reason(hit),
                            "qualifier": hit.qualifier,
                        }.items()
                        if v
                    },
                )
                if edge_doc:
                    edge_batch.append(edge_doc)
                    if len(edge_batch) >= self._EDGE_BATCH_SIZE:
                        created, updated = self._flush_edge_batch(edge_batch, result)
                        result.created += created
                        result.updated += updated
                        edge_batch = []

        if edge_batch:
            created, updated = self._flush_edge_batch(edge_batch, result)
            result.created += created
            result.updated += updated

        logger.info(
            "Rechtspraak article linker: %d judgments, %s.",
            judgment_count,
            result.summary(),
        )
        return result

    def _resolve_article(self, hit: CitationHit) -> Node | None:
        if hit.bwb_id and hit.article_number:
            article_key = make_node_key(hit.bwb_id, hit.article_number)
            node = self._lookup_node(COLLECTION_ARTICLES, article_key)
            if node is None and hit.confidence >= 0.9:
                node = self.store.ensure_stub_node(
                    COLLECTION_ARTICLES,
                    article_key,
                    NodeType.ARTICLE,
                    props={"bwb_id": hit.bwb_id, "article_number": hit.article_number},
                )
                self._remember_node(node)
            if node is None:
                logger.debug(
                    "Rechtspraak semantic: no node for article %s %s (conf=%.2f)",
                    hit.bwb_id,
                    hit.article_number,
                    hit.confidence,
                )
            return node

        if hit.celex and hit.article_number:
            article_key = make_node_key(hit.celex, hit.article_number)
            node = self._lookup_node(COLLECTION_ARTICLES, article_key)
            if node is None and hit.confidence >= 0.9:
                node = self.store.ensure_stub_node(
                    COLLECTION_ARTICLES,
                    article_key,
                    NodeType.ARTICLE,
                    props={"celex": hit.celex, "article_number": hit.article_number},
                )
                self._remember_node(node)
            if node is None:
                logger.debug(
                    "Rechtspraak semantic: no node for article %s %s (conf=%.2f)",
                    hit.celex,
                    hit.article_number,
                    hit.confidence,
                )
            return node

        return None

    def _recent_rechtspraak_eclis(self, since_iso: str | None) -> set[str] | None:
        """ECLIs fetched since *since_iso*; ``None`` without a date means: all judgments."""
        if since_iso is None:
            return None

        bind_vars = {
            "source": SOURCE_RECHTSPRAAK,
            "kind": RAW_KIND_RS_CONTENT,
            "since": since_iso,
        }
        aql = f"""
        FOR raw IN {COLLECTION_RAW_SOURCES}
            FILTER raw.source == @source
            FILTER raw.kind == @kind
            FILTER raw.fetched_at >= @since
            FILTER raw.meta.ecli != null
        RETURN raw.meta.ecli
        """
        eclis: set[str] = set()
        for row in self.store.query(aql, bind_vars=bind_vars):
            if row:
                eclis.add(row)
        return eclis

    def _load_judgments(self, eclis: Iterable[str] | None) -> Iterable[dict[str, Any]]:
        collection = COLLECTION_JUDGMENTS
        if eclis is not None:
            bind_vars = {"eclis": list(eclis)}
            aql = f"""
            FOR doc IN {collection}
                FILTER doc.props.ecli IN @eclis
            RETURN {JUDGMENT_TEXT}
            """
        else:
            bind_vars = {}
            aql = f"FOR doc IN {collection} RETURN {JUDGMENT_TEXT}"
        return self.store.query(
            aql, bind_vars=bind_vars, batch_size=JUDGMENT_BATCH_SIZE
        )

    def _extract_judgment_text(self, judgment: Node) -> str | None:
        props = judgment.props
        # ``raw_xml`` holds the summary and the body: reading all three would find every
        # citation three times. The plain fields are the fallback for a node without it.
        raw = props.get("raw_xml")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        fragments = [
            value.strip()
            for value in (props.get("text"), props.get("summary"))
            if isinstance(value, str) and value.strip()
        ]
        return "\n\n".join(fragments) if fragments else None
