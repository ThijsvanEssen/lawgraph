"""Semantic pipeline that links BWB articles referenced inside other articles."""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLES,
    RELATION_REFERS_TO_ARTICLE,
    SOURCE_BWB,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.time import iso_timestamp
from lawgraph.pipelines.semantic.bwb_detect import (
    ArticleCitationHit,
    detect_bwb_article_citations,
)

from .base import SemanticPipelineBase

logger = get_logger(__name__)
SEMANTIC_SOURCE = "bwb-article-text"


class BwbArticlesSemanticPipeline(SemanticPipelineBase):
    """Detect article-to-article references inside BWB article texts."""

    def __init__(
        self,
        *,
        store: Any,
        store_citations: bool = False,
    ) -> None:
        super().__init__(store=store)
        self._store_citations = store_citations

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        """Create semantic edges for article references detected inside BWB articles."""
        result = PipelineResult()
        code_aliases = self._load_code_aliases()
        instrument_aliases = self._load_instrument_aliases()
        bwb_ids = self._load_bwb_ids_from_graph()
        if not bwb_ids:
            logger.warning(
                "No BWB IDs found in graph for semantic linking; skipping detection."
            )
            return result

        since_iso = iso_timestamp(since) if since is not None else None
        articles = list(self._load_articles(bwb_ids, since_iso=since_iso))
        if not articles:
            logger.info("No BWB articles found for semantic linking.")
            return result

        logger.info(
            "Scanning %d BWB articles for internal references.",
            len(articles),
        )

        hits_detected = 0
        edge_batch: list[dict] = []
        detect_config = {
            "code_aliases": code_aliases,
            "instrument_aliases": instrument_aliases,
        }
        for doc in articles:
            article = Node.from_document(COLLECTION_INSTRUMENT_ARTICLES, doc)
            text = self._extract_article_text(article)
            if not text:
                result.skipped += 1
                continue

            bwb_id = str(article.props.get("bwb_id") or "")
            if not bwb_id:
                result.skipped += 1
                continue

            hits = detect_bwb_article_citations(text, bwb_id, detect_config)
            hits_detected += len(hits)
            self._store_article_citations(article, hits)

            for hit in hits:
                target = self._resolve_article(hit)
                if not target:
                    logger.debug(
                        "Unable to resolve article %s %s for citation.",
                        hit.bwb_id,
                        hit.article_number,
                    )
                    continue

                edge_doc = self._make_edge_doc(
                    from_node=article,
                    to_node=target,
                    relation=RELATION_REFERS_TO_ARTICLE,
                    source=SEMANTIC_SOURCE,
                    confidence=hit.confidence,
                    meta={"start": hit.start, "end": hit.end, "text": hit.text},
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
            "BWB article linker: %d citations detected, %s.",
            hits_detected,
            result.summary(),
        )
        return result

    def _load_bwb_ids_from_graph(self) -> list[str]:
        """Return all distinct BWB IDs that have article nodes in the graph."""
        aql = f"""
        FOR doc IN {COLLECTION_INSTRUMENT_ARTICLES}
            FILTER doc.props.bwb_id != null
            RETURN DISTINCT doc.props.bwb_id
        """
        try:
            return [str(row) for row in self.store.query(aql) if row]
        except Exception as exc:
            logger.debug("Could not load BWB IDs from graph: %s", exc)
            return []

    def _load_articles(
        self,
        bwb_ids: list[str],
        *,
        since_iso: str | None = None,
    ) -> Iterable[dict[str, Any]]:
        if not bwb_ids:
            return
        if since_iso is not None:
            # Get recently fetched BWB IDs from raw_sources
            recent_bwb_ids_aql = """
            FOR raw IN raw_sources
                FILTER raw.source == @source
                FILTER raw.fetched_at >= @since
                FILTER raw.meta.bwb_id != null
            RETURN DISTINCT raw.meta.bwb_id
            """
            recent_ids: set[str] = set()
            for row in self.store.query(
                recent_bwb_ids_aql,
                bind_vars={"source": SOURCE_BWB, "since": since_iso},
            ):
                if isinstance(row, str):
                    recent_ids.add(row)
            # Intersect with known bwb_ids
            filtered_ids = [bid for bid in bwb_ids if bid in recent_ids]
            if not filtered_ids:
                return
            # Load articles for those BWB IDs only
            aql = f"""
            FOR doc IN {COLLECTION_INSTRUMENT_ARTICLES}
                FILTER doc.props.bwb_id IN @bwb_ids
                FILTER doc.props.text != null
            RETURN doc
            """
            yield from self.store.query(aql, bind_vars={"bwb_ids": filtered_ids})
        else:
            aql = f"""
            FOR doc IN {COLLECTION_INSTRUMENT_ARTICLES}
                FILTER doc.props.bwb_id IN @bwb_ids
                FILTER doc.props.text != null
            RETURN doc
            """
            yield from self.store.query(aql, bind_vars={"bwb_ids": bwb_ids})

    def _resolve_article(self, hit: ArticleCitationHit) -> Node | None:
        if not hit.bwb_id or not hit.article_number:
            return None
        key = make_node_key(hit.bwb_id, hit.article_number)
        return self.store.get_node(COLLECTION_INSTRUMENT_ARTICLES, key)

    def _extract_article_text(self, article: Node) -> str | None:
        text = article.props.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return None

    def _store_article_citations(
        self,
        article: Node,
        hits: list[ArticleCitationHit],
    ) -> None:
        if not self._store_citations or not article.key:
            return

        citations = [
            {
                "start": hit.start,
                "end": hit.end,
                "text": hit.text,
                "target_bwb_id": hit.bwb_id,
                "target_article_number": hit.article_number,
                "confidence": hit.confidence,
            }
            for hit in hits
        ]

        article.props["citations"] = citations
        self.store.insert_or_update(article)
