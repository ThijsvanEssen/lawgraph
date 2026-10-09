"""Semantic linkage pipeline for Rechtspraak judgments and BWB articles."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.core.citations import CitationHit
from lawgraph.core.logging import get_logger
from lawgraph.core.mentions import ArticleMentions, find_mentions
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries.semantic import edges as semantic_edges

from ._detection import build_extractor, detect_in_text
from .base import SemanticPipelineBase

logger = get_logger(__name__)


SEMANTIC_SOURCE = "rechtspraak-article-linker"
# A citation surer than this may make a stub of an article that is not loaded.
STUB_CONFIDENCE = 0.9
# The most citations of laws that are not in the graph a judgment keeps, in reading order.
MAX_UNRESOLVED_CITATIONS = 100


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class RechtspraakSemanticPipeline(SemanticPipelineBase):
    """Link Rechtspraak judgments to BWB articles via semantic edges.

    One edge per judgment and article; ``meta.mentions`` has every place in the judgment that
    cites the article (``core.mentions``): the paragraph, the span in its text, the lid or
    onderdeel it names. The edges of a judgment are derived in full each time it is read:
    one its text no longer makes (an earlier rule, an earlier text) goes. A citation of a law
    that is not in the graph (``artikel 392 Rv``) has no article to point at: the judgment
    keeps it in ``props.unresolved_citations``, written only when it changed.
    """

    def __init__(
        self, *, store: Any, after: str | None = None, limit: int | None = None
    ) -> None:
        """*after* and *limit*: a slice of a run over all, past that judgment key, so
        many judgments; the log names the last one read."""
        super().__init__(store=store)
        self.after = after
        self.limit = limit

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)

        mapping = self._load_code_aliases()
        instrument_aliases = self._load_instrument_aliases()
        # "EP" is the First Protocol in a judgment that also names the EVRM
        extractor = build_extractor(
            mapping, instrument_aliases, self._load_context_aliases(mapping)
        )

        def detect(text: str) -> list[CitationHit]:
            hits = detect_in_text(
                text, extractor, every_occurrence=True, unknown_laws=True
            )
            return [hit for hit in hits if hit.kind == "article"]

        logger.info(
            "Processing Rechtspraak judgments for article references (since=%s).",
            describe_since(since),
        )

        edges = EdgeWriter(self.store, what=None)
        read: list[str] = []
        kept: dict[str, set[str]] = {}
        with NodeWriter(self.store) as nodes:
            for judgment, paragraphs in self._judgment_paragraphs(
                since_iso, after=self.after, limit=self.limit
            ):
                read.append(str(judgment.node_id))
                unresolved: list[dict[str, Any]] = []
                for cited in find_mentions(paragraphs, detect).values():
                    if cited.unknown_law:
                        unresolved.append(cited.unresolved())
                        continue
                    article = self._resolve_article(cited)
                    if article is None:
                        continue
                    doc = self._make_edge_doc(
                        from_node=judgment,
                        to_node=article,
                        relation=RELATION_REFERS_TO,
                        source=SEMANTIC_SOURCE,
                        confidence=cited.confidence,
                        meta=cited.meta(),
                    )
                    if doc:
                        edges.add_doc(doc)
                        kept.setdefault(doc["_from"], set()).add(doc["_key"])
                self._keep_unresolved(judgment, unresolved, nodes, result)

        edges.flush_into(result)
        removed = semantic_edges.remove_edges_from(
            self.store, RELATION_REFERS_TO, SEMANTIC_SOURCE, read, kept
        )
        logger.info("Removed %d article citations the text no longer makes.", removed)
        if self.after or self.limit is not None:
            last = self.last_judgment_read
            logger.info("The last read was %s (go on with --after %s).", last, last)
        return result

    @staticmethod
    def _keep_unresolved(
        judgment: Node,
        unresolved: list[dict[str, Any]],
        nodes: NodeWriter,
        result: PipelineResult,
    ) -> None:
        """Write ``props.unresolved_citations`` of *judgment* when it changed; null when the
        judgment cites no law that is not in the graph."""
        kept = unresolved[:MAX_UNRESOLVED_CITATIONS] or None
        if kept == judgment.props.get("unresolved_citations"):
            return
        nodes.add(
            Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=judgment.key,
                props={"unresolved_citations": kept},
            )
        )
        result.updated += 1

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
