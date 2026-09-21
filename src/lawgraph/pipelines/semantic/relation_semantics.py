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

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    RELATION_REFERS_TO,
    SEMANTIC_SOURCE_STRUCTURED,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.pipelines.semantic.base import SemanticPipelineBase
from lawgraph.pipelines.semantic.semantic_classify import classify_citation_context

logger = get_logger(__name__)


class RelationSemanticsSemanticPipeline(SemanticPipelineBase):
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

        logger.info(
            "Relation semantics: %d edges classified, %s.",
            classified,
            result.summary(),
        )
        return result

    def _load_articles_with_edges(self) -> Any:
        """Stream articles with their classifiable outgoing reference edges.

        Grouped per article so each article text crosses the wire once.
        Excludes expert/community-curated edges.
        """
        aql = f"""
        FOR art IN {COLLECTION_ARTICLES}
            FILTER art.props.text != null
            LET es = (
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._from == art._id
                    FILTER e.relation == @relation
                    FILTER e.semantic_source == null
                        OR e.semantic_source == @structured
                    RETURN {{ key: e._key, start: e.meta.start, end: e.meta.end }}
            )
            FILTER LENGTH(es) > 0
            RETURN {{ text: art.props.text, edges: es }}
        """
        return self.store.query(
            aql,
            {
                "relation": RELATION_REFERS_TO,
                "structured": SEMANTIC_SOURCE_STRUCTURED,
            },
        )

    def _flush_updates(
        self,
        batch: list[dict[str, Any]],
        result: PipelineResult,
    ) -> int:
        """Apply one batch of semantic-type updates. Returns updated count."""
        now = iso_timestamp(dt.datetime.now(dt.timezone.utc).replace(microsecond=0))
        aql = f"""
        FOR u IN @updates
            UPDATE u.key WITH {{
                semantic_type: u.semantic_type,
                semantic_source: @structured,
                explanation: u.explanation,
                expert_badge: false,
                updated_at: @now,
                meta: {{
                    semantic_pattern: u.pattern,
                    semantic_confidence: u.semantic_confidence
                }}
            }} IN {COLLECTION_EDGES} OPTIONS {{ mergeObjects: true }}
            RETURN 1
        """
        bind = {
            "updates": batch,
            "structured": SEMANTIC_SOURCE_STRUCTURED,
            "now": now,
        }
        return len(list(self.store.query(aql, bind)))
