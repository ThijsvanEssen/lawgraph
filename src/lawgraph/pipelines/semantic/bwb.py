"""Semantic pipeline that links BWB articles referenced inside other articles.

The BWB XML states every reference explicitly: articles normalized from it carry
``props.references`` (from ``<extref>``/``<intref>``), and those structured
references are the only source. An article without them produces no edges.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_RAW_SOURCES,
    RELATION_REFERS_TO,
    SOURCE_BWB,
)
from lawgraph.core.batching import chunked
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import iso_timestamp
from lawgraph.db import EdgeWriter
from lawgraph.pipelines.semantic._bwb_references import (
    ArticleReferenceHit,
    hits_from_references,
)

from .base import SemanticPipelineBase, slim

logger = get_logger(__name__)
SEMANTIC_SOURCE = "bwb-article-references"


class BWBSemanticPipeline(SemanticPipelineBase):
    """Link article-to-article references recorded in the BWB XML."""

    _ARTICLE_CHUNK = 500

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
        bwb_ids = self._load_bwb_ids_from_graph()
        if not bwb_ids:
            logger.warning(
                "No BWB IDs found in graph for semantic linking; skipping detection."
            )
            return result

        since_iso = iso_timestamp(since) if since is not None else None

        hits_detected = 0
        articles_seen = 0
        edges = EdgeWriter(self.store, what=None)
        # Stream articles (they carry full text) and process them in chunks so
        # that all reference targets of a chunk are resolved with ONE lookup.
        articles = self._track(
            self._load_articles(bwb_ids, since_iso=since_iso), "articles"
        )
        for chunk in chunked(articles, self._ARTICLE_CHUNK):
            scanned: list[tuple[Node, list[ArticleReferenceHit]]] = []
            for doc in chunk:
                articles_seen += 1
                article = Node.from_document(COLLECTION_ARTICLES, doc)
                bwb_id = str(article.props.get("bwb_id") or "")
                if not bwb_id:
                    result.skipped += 1
                    continue
                hits = self._hits_for(article, bwb_id)
                hits_detected += len(hits)
                scanned.append((article, hits))

            self._store_article_citations(scanned)
            self._prefetch_nodes(
                COLLECTION_ARTICLES,
                {
                    make_node_key(hit.bwb_id, hit.article_number)
                    for _, hits in scanned
                    for hit in hits
                    if hit.bwb_id and hit.article_number
                },
                NodeType.ARTICLE,
            )
            for article, hits in scanned:
                for hit in hits:
                    target = self._resolve_article(hit)
                    if not target:
                        logger.debug(
                            "Unable to resolve referenced article %s %s.",
                            hit.bwb_id,
                            hit.article_number,
                        )
                        continue
                    edges.add_doc(
                        self._make_edge_doc(
                            from_node=article,
                            to_node=target,
                            relation=RELATION_REFERS_TO,
                            source=SEMANTIC_SOURCE,
                            confidence=hit.confidence,
                            meta=self._edge_meta(hit),
                        )
                    )

        edges.flush_into(result)
        if not articles_seen:
            logger.info("No BWB articles found for semantic linking.")

        logger.info("%d references read.", hits_detected)
        return result

    @staticmethod
    def _hits_for(article: Node, bwb_id: str) -> list[ArticleReferenceHit]:
        """The structured references the BWB XML recorded on this article."""
        references = article.props.get("references")
        if not isinstance(references, list):
            return []
        return hits_from_references(
            references, bwb_id, article.props.get("article_number")
        )

    @staticmethod
    def _edge_meta(hit: ArticleReferenceHit) -> dict[str, Any]:
        meta: dict[str, Any] = {"start": hit.start, "end": hit.end, "text": hit.text}
        if hit.reason:
            meta["reason"] = hit.reason
        return meta

    def _load_bwb_ids_from_graph(self) -> list[str]:
        """Return all distinct BWB IDs that have article nodes in the graph."""
        aql = f"""
        FOR doc IN {COLLECTION_ARTICLES}
            FILTER doc.props.bwb_id != null
            RETURN DISTINCT doc.props.bwb_id
        """
        return [str(row) for row in self.store.query(aql) if row]

    def _load_articles(
        self,
        bwb_ids: list[str],
        *,
        since_iso: str | None = None,
    ) -> Iterable[dict[str, Any]]:
        """Articles carrying structured references, optionally only recent ones."""
        if since_iso is not None:
            recent = self._recent_bwb_ids(
                since_iso
            )  # one query, not one per regulation
            bwb_ids = [bid for bid in bwb_ids if bid in recent]
        if not bwb_ids:
            return []
        aql = f"""
        FOR doc IN {COLLECTION_ARTICLES}
            FILTER doc.props.bwb_id IN @bwb_ids
            FILTER doc.props.references != null
        RETURN {slim("doc", "bwb_id", "article_number", "references")}
        """
        return self.store.query(aql, bind_vars={"bwb_ids": bwb_ids})

    def _recent_bwb_ids(self, since_iso: str) -> set[str]:
        """BWB IDs whose raw record was fetched at or after *since_iso*."""
        aql = f"""
        FOR raw IN {COLLECTION_RAW_SOURCES}
            FILTER raw.source == @source
            FILTER raw.fetched_at >= @since
            FILTER raw.meta.bwb_id != null
        RETURN DISTINCT raw.meta.bwb_id
        """
        rows = self.store.query(
            aql, bind_vars={"source": SOURCE_BWB, "since": since_iso}
        )
        return {row for row in rows if isinstance(row, str)}

    def _resolve_article(self, hit: ArticleReferenceHit) -> Node | None:
        if not hit.bwb_id or not hit.article_number:
            return None
        key = make_node_key(hit.bwb_id, hit.article_number)
        return self._lookup_node(COLLECTION_ARTICLES, key)

    def _store_article_citations(
        self, scanned: list[tuple[Node, list[ArticleReferenceHit]]]
    ) -> None:
        """Persist the references as ``props.citations`` (``--store-citations``).

        One bulk upsert per chunk that sends only the changed prop; the upsert
        merges props, so the rest of each article (incl. its text) is untouched.
        """
        if not self._store_citations:
            return
        docs: list[dict[str, Any]] = [
            {
                "_key": article.key,
                "type": article.type.value,
                "labels": [],
                "props": {
                    "citations": [
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
                },
            }
            for article, hits in scanned
            if article.key
        ]
        if docs:
            self.store.bulk_insert_or_update_nodes(COLLECTION_ARTICLES, docs)
