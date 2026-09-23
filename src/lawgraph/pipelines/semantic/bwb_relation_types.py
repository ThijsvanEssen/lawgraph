"""Semantic pipeline that classifies article-to-article REFERS_TO edges.

Runs after the citation-detection pipelines (bwb_articles etc.) and assigns a
``semantic_type`` to each article-to-article edge based on the Dutch legal
drafting patterns surrounding the citation span (stored in edge.meta).

Curation-aware: edges whose ``semantic_source`` is 'expert' or 'community'
are never overwritten — only unclassified edges and earlier 'structured'
classifications are (re)classified, so the extractor can be improved and
re-run safely.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db.queries import semantic as semantic_queries
from lawgraph.pipelines.semantic._relation_type_patterns import (
    classify_citation_context,
)
from lawgraph.pipelines.semantic.base import SemanticPipelineBase

logger = get_logger(__name__)


class BWBRelationTypesSemanticPipeline(SemanticPipelineBase):
    """Assign semantic_type to article-to-article reference edges."""

    _UPDATE_BATCH_SIZE = 500

    def run(self) -> PipelineResult:
        result = PipelineResult()
        batch: list[dict[str, Any]] = []
        classified = 0

        articles = self._load_articles_with_edges()
        for row in self._track(articles, "articles"):
            text = row.get("text") or ""
            for edge in row.get("edges") or []:
                classification = classify_citation_context(
                    text, edge.get("start"), edge.get("end")
                )
                if classification is None:
                    result.skipped += 1
                    continue
                batch.append(
                    {
                        "key": edge["key"],
                        "semantic_type": classification.semantic_type,
                        "explanation": classification.explanation,
                        "pattern": classification.pattern,
                        "semantic_confidence": classification.confidence,
                    }
                )
                classified += 1
                if len(batch) >= self._UPDATE_BATCH_SIZE:
                    result.updated += self._flush_updates(batch, result)
                    batch = []

        if batch:
            result.updated += self._flush_updates(batch, result)

        logger.info("%d edges classified.", classified)
        return result

    def _load_articles_with_edges(self) -> Any:
        """Stream articles with their classifiable outgoing reference edges."""
        return semantic_queries.articles_with_classifiable_edges(self.store)

    def _flush_updates(
        self,
        batch: list[dict[str, Any]],
        result: PipelineResult,
    ) -> int:
        """Write the classifications of *batch* that differ from the stored ones."""
        now = iso_timestamp(dt.datetime.now(dt.timezone.utc).replace(microsecond=0))
        updated = semantic_queries.update_edge_classifications(self.store, batch, now)
        result.unchanged += len(batch) - updated
        return updated
