"""Semantic linkage pipeline for Rechtspraak judgments and BWB articles."""

from __future__ import annotations

import datetime as dt

from lawgraph.config.constants import (
    RELATION_REFERS_TO,
)
from lawgraph.core.citations import CitationHit
from lawgraph.core.logging import get_logger
from lawgraph.core.mentions import ArticleMentions, find_mentions
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.db import EdgeWriter

from ._detection import build_extractor, detect_in_text
from .base import SemanticPipelineBase

logger = get_logger(__name__)


SEMANTIC_SOURCE = "rechtspraak-article-linker"
# A citation surer than this may make a stub of an article that is not loaded.
STUB_CONFIDENCE = 0.9


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
        law_id = cited.bwb_id or cited.celex
        if not law_id or not cited.article_number:
            return None
        return self._cited_article(
            law_id,
            cited.article_number,
            celex=cited.bwb_id is None,
            confidence=cited.confidence,
            min_confidence=STUB_CONFIDENCE,
        )
