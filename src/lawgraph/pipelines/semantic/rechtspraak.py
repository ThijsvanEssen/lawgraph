"""Semantic linkage pipeline for Rechtspraak judgments and BWB articles."""

from __future__ import annotations

import datetime as dt

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    RELATION_REFERS_TO,
)
from lawgraph.core.citations import CitationHit, hit_reason, strip_xml
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.db import EdgeWriter

from ._detection import build_extractor, detect_in_text
from .base import SemanticPipelineBase

logger = get_logger(__name__)


SEMANTIC_SOURCE = "rechtspraak-article-linker"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class RechtspraakSemanticPipeline(SemanticPipelineBase):
    """Link Rechtspraak judgments to BWB articles via semantic edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)

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

        edges = EdgeWriter(self.store, what=None)

        # The XML of each judgment streams from raw_sources, where retrieve stored it.
        for judgment, xml in self._judgment_texts(since_iso):
            hits = detect_in_text(strip_xml(xml), extractor)
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
                    edges.add_doc(edge_doc)

        edges.flush_into(result)

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
