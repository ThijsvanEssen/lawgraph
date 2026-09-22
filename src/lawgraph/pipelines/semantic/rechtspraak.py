"""Semantic linkage pipeline for Rechtspraak judgments and BWB articles."""

from __future__ import annotations

import datetime as dt

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    RELATION_REFERS_TO,
)
from lawgraph.core.citations import CitationHit
from lawgraph.core.logging import get_logger
from lawgraph.core.mentions import ArticleMentions, find_mentions
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
    """Link Rechtspraak judgments to BWB articles via semantic edges.

    One edge per judgment and article; ``meta.mentions`` has every place in the judgment that
    cites the article (``core.mentions``): the paragraph, the span in its text, the lid or
    onderdeel it names.
    """

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)

        mapping = self._load_code_aliases()
        instrument_aliases = self._load_instrument_aliases()
        if not mapping and not instrument_aliases:
            logger.warning("No code or name aliases configured; skipping linkage.")
            return result

        extractor = build_extractor(mapping, instrument_aliases)

        def detect(text: str) -> list[CitationHit]:
            hits = detect_in_text(text, extractor, every_occurrence=True)
            return [hit for hit in hits if hit.kind == "article"]

        logger.info(
            "Processing Rechtspraak judgments for article references (since=%s).",
            describe_since(since),
        )

        edges = EdgeWriter(self.store, what=None)

        for judgment, paragraphs in self._judgment_paragraphs(since_iso):
            for cited in find_mentions(paragraphs, detect).values():
                article = self._resolve_article(cited)
                if article is None:
                    continue
                edges.add_doc(
                    self._make_edge_doc(
                        from_node=judgment,
                        to_node=article,
                        relation=RELATION_REFERS_TO,
                        source=SEMANTIC_SOURCE,
                        confidence=cited.confidence,
                        meta=cited.meta(),
                    )
                )

        edges.flush_into(result)

        return result

    def _resolve_article(self, cited: ArticleMentions) -> Node | None:
        if cited.bwb_id and cited.article_number:
            article_key = make_node_key(cited.bwb_id, cited.article_number)
            node = self._lookup_node(COLLECTION_ARTICLES, article_key)
            if node is None and cited.confidence >= 0.9:
                node = self.store.ensure_stub_node(
                    COLLECTION_ARTICLES,
                    article_key,
                    NodeType.ARTICLE,
                    props={
                        "bwb_id": cited.bwb_id,
                        "article_number": cited.article_number,
                    },
                )
                self._remember_node(node)
            if node is None:
                logger.debug(
                    "Rechtspraak semantic: no node for article %s %s (conf=%.2f)",
                    cited.bwb_id,
                    cited.article_number,
                    cited.confidence,
                )
            return node

        if cited.celex and cited.article_number:
            article_key = make_node_key(cited.celex, cited.article_number)
            node = self._lookup_node(COLLECTION_ARTICLES, article_key)
            if node is None and cited.confidence >= 0.9:
                node = self.store.ensure_stub_node(
                    COLLECTION_ARTICLES,
                    article_key,
                    NodeType.ARTICLE,
                    props={
                        "celex": cited.celex,
                        "article_number": cited.article_number,
                    },
                )
                self._remember_node(node)
            if node is None:
                logger.debug(
                    "Rechtspraak semantic: no node for article %s %s (conf=%.2f)",
                    cited.celex,
                    cited.article_number,
                    cited.confidence,
                )
            return node

        return None
