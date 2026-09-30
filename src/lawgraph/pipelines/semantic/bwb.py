"""Semantic pipeline that links BWB articles referenced inside other articles.

The BWB XML states every reference explicitly: articles normalized from it carry
``props.references`` (from ``<extref>``/``<intref>``), and those structured
references are the only source. An article without them produces no edges.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    RELATION_REFERS_TO,
)
from lawgraph.core.batching import chunked
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import iso_timestamp
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.store import edge_key
from lawgraph.pipelines.semantic._bwb_references import (
    ArticleReferenceHit,
    hits_from_references,
)

from .base import SemanticPipelineBase

logger = get_logger(__name__)
SEMANTIC_SOURCE = "bwb-article-references"


def _target_keys(hit: ArticleReferenceHit) -> list[str]:
    """The keys of the article a reference names and of the one its link points at."""
    targets = [(hit.bwb_id, hit.article_number), *([hit.linked] if hit.linked else [])]
    return [make_node_key(law, number) for law, number in targets if law and number]


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
        # the articles read and the edges written from them: the edges of an article are
        # derived in full, so one its references no longer support goes
        read: list[str] = []
        kept: dict[str, set[str]] = {}
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
                if article.arango_id:
                    read.append(article.arango_id)
                scanned.append((article, hits))

            self._store_article_citations(scanned)
            self._prefetch_nodes(
                COLLECTION_ARTICLES,
                {
                    key
                    for _, hits in scanned
                    for hit in hits
                    for key in _target_keys(hit)
                },
                NodeType.ARTICLE,
            )
            for article, hits in scanned:
                self._link(article, hits, edges, kept)

        edges.flush_into(result)
        if not articles_seen:
            logger.info("No BWB articles found for semantic linking.")

        removed = semantic_edges.remove_edges_from(
            self.store, RELATION_REFERS_TO, SEMANTIC_SOURCE, read, kept
        )
        logger.info(
            "%d references read; %d edges the references no longer support removed.",
            hits_detected,
            removed,
        )
        return result

    def _link(
        self,
        article: Node,
        hits: list[ArticleReferenceHit],
        edges: EdgeWriter,
        kept: dict[str, set[str]],
    ) -> None:
        """Queue the edges of one article; the keys go into *kept*."""
        for hit in hits:
            target, hit = self._resolve_article(hit)
            if not target or not article.arango_id or not target.arango_id:
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
            kept.setdefault(article.arango_id, set()).add(
                edge_key(article.arango_id, RELATION_REFERS_TO, target.arango_id)
            )

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
        meta: dict[str, Any] = {
            "start": hit.start,
            "end": hit.end,
            "text": hit.text,
            "reference_kind": hit.kind,
            **hit.qualifier.to_dict(),
        }
        if hit.reason:
            meta["reason"] = hit.reason
        if hit.linked:
            meta["linked_article"] = make_node_key(*hit.linked)
        return meta

    def _load_bwb_ids_from_graph(self) -> list[str]:
        """Return all distinct BWB IDs that have article nodes in the graph."""
        rows = semantic_bwb.article_bwb_ids(self.store)
        return [str(row) for row in rows if row]

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
        return semantic_bwb.articles_with_references(self.store, bwb_ids)

    def _recent_bwb_ids(self, since_iso: str) -> set[str]:
        """BWB IDs whose raw record was fetched at or after *since_iso*."""
        rows = raw_queries.bwb_ids_fetched_since(self.store, since_iso)
        return {row for row in rows if isinstance(row, str)}

    def _resolve_article(
        self, hit: ArticleReferenceHit
    ) -> tuple[Node | None, ArticleReferenceHit]:
        """The article the text of a reference names; else the one its link points at
        (the hit then is the link's, without ``linked``)."""
        if not hit.bwb_id or not hit.article_number:
            return None, hit
        node = self._lookup_node(
            COLLECTION_ARTICLES, make_node_key(hit.bwb_id, hit.article_number)
        )
        if node is not None or hit.linked is None:
            return node, hit
        bwb_id, number = hit.linked
        fallback = replace(hit, bwb_id=bwb_id, article_number=number, linked=None)
        return self._lookup_node(
            COLLECTION_ARTICLES, make_node_key(bwb_id, number)
        ), fallback

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
