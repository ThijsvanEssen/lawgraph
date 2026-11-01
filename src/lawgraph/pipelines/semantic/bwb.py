"""Semantic pipeline that links BWB articles referenced inside other articles.

The BWB XML states every reference explicitly: articles normalized from it carry
``props.references`` (from ``<extref>``/``<intref>``), and those structured
references are the only source. An article without them produces no edges.

The edges are derived in full: a full run removes every edge of the step it did not write
(also of an article whose references are gone, which it does not read); a run under
``--since`` those of the articles it read. A link to a whole law whose sentence leaves a matter
to that law (``core.delegations.leaves_to``) is an edge to the instrument, reason ``leaves_to``;
other links to a whole law are none. Each article read keeps how many of its references
name an article the graph does not hold (``lg_unlinked_references``): what
``completeness.references`` of the API says.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.core.batching import chunked
from lawgraph.core.delegations import leaves_to
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.provenance import REASON_LEAVES_TO
from lawgraph.core.time import iso_timestamp
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries import unlinked_references as unlinked_queries
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.pipelines.semantic._bwb_references import (
    ArticleReferenceHit,
    hits_from_references,
)

from .base import EXACT_CONFIDENCE, SemanticPipelineBase

logger = get_logger(__name__)
EDGE_SOURCE = "bwb-article-references"


def _target_keys(hit: ArticleReferenceHit) -> list[str]:
    """The keys of the article a reference names and of the one its link points at."""
    targets = [(hit.bwb_id, hit.article_number), *([hit.linked] if hit.linked else [])]
    return [make_node_key(law, number) for law, number in targets if law and number]


def _whole_law_links(article: Node) -> list[dict[str, Any]]:
    """The links in the text of *article* to another law as a whole."""
    references = article.props.get("references")
    own = article.props.get("bwb_id")
    return [
        ref
        for ref in (references if isinstance(references, list) else [])
        if ref.get("kind") == "extref"
        and ref.get("bwb_id") not in (None, own)
        and not ref.get("article")
        and ref.get("footnote") is None
    ]


class BWBSemanticPipeline(SemanticPipelineBase):
    """Link article-to-article references recorded in the BWB XML."""

    _ARTICLE_CHUNK = 500

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        """Create semantic edges for article references detected inside BWB articles."""
        result = PipelineResult()
        bwb_ids = self._load_bwb_ids_from_graph()
        if not bwb_ids:
            logger.warning(
                "No BWB IDs found in graph for semantic linking; skipping detection."
            )
            return result

        since_iso = iso_timestamp(since)

        hits_detected = 0
        articles_seen = 0
        # the articles read: under --since the edges of those go that their references no
        # longer support
        read: list[str] = []
        unlinked: dict[str, int] = {}
        edges = EdgeWriter(self.store, what=None, remembers=True)
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
                if article.node_id:
                    read.append(article.node_id)
                scanned.append((article, hits))

            self._prefetch_nodes(
                COLLECTION_ARTICLES,
                {
                    key
                    for _, hits in scanned
                    for hit in hits
                    for key in _target_keys(hit)
                },
            )
            leaving = self._leaving_in([article for article, _ in scanned])
            for article, hits in scanned:
                missed = self._link(article, hits, edges)
                self._link_leaving(article, leaving.get(article.key or "", []), edges)
                if article.node_id:
                    unlinked[article.node_id] = missed

        edges.flush_into(result)
        unlinked_queries.keep_unlinked(
            self.store, EDGE_SOURCE, unlinked, whole=since is None
        )
        if not articles_seen:
            logger.info("No BWB articles found for semantic linking.")

        if since is None:
            removed = edges.remove_stale_of_source(RELATION_REFERS_TO, EDGE_SOURCE)
        else:
            removed = edges.remove_stale(RELATION_REFERS_TO, EDGE_SOURCE, read)
        logger.info(
            "%d references read, %d not linked; %d edges the references no longer "
            "support removed.",
            hits_detected,
            sum(unlinked.values()),
            removed,
        )
        return result

    def _link(
        self,
        article: Node,
        hits: list[ArticleReferenceHit],
        edges: EdgeWriter,
    ) -> int:
        """Queue the edges of one article; how many of its references name an article the
        graph does not hold."""
        missed = 0
        for hit in hits:
            target, hit = self._resolve_article(hit)
            if not target:
                missed += 1
                continue
            edges.add_doc(
                self._make_edge_doc(
                    from_node=article,
                    to_node=target,
                    relation=RELATION_REFERS_TO,
                    source=EDGE_SOURCE,
                    confidence=hit.confidence,
                    meta=self._edge_meta(hit),
                )
            )
        return missed

    def _leaving_in(self, articles: list[Node]) -> dict[str, list[dict[str, Any]]]:
        """Per article the links to a whole law whose sentence leaves a matter to it, the
        laws looked up in bulk. The text is read only for an article with such a link."""
        links = {
            a.key: found for a in articles if a.key and (found := _whole_law_links(a))
        }
        if not links:
            return {}
        texts = {
            row["key"]: row["text"] or ""
            for row in semantic_bwb.article_texts(self.store, list(links))
        }
        leaving = {
            key: [
                ref
                for ref in refs
                if leaves_to(texts.get(key, ""), ref["start"], ref["end"])
            ]
            for key, refs in links.items()
        }
        laws = {str(r["bwb_id"]).lower() for refs in leaving.values() for r in refs}
        if laws:
            self._prefetch_nodes(COLLECTION_INSTRUMENTS, laws)
        return leaving

    def _link_leaving(
        self, article: Node, leaving: list[dict[str, Any]], edges: EdgeWriter
    ) -> None:
        """Queue the edges to the laws the text of *article* leaves a matter to."""
        for ref in leaving:
            target = self._lookup_node(
                COLLECTION_INSTRUMENTS, str(ref["bwb_id"]).lower()
            )
            if target is None:
                continue
            edges.add_doc(
                self._make_edge_doc(
                    from_node=article,
                    to_node=target,
                    relation=RELATION_REFERS_TO,
                    source=EDGE_SOURCE,
                    confidence=EXACT_CONFIDENCE,
                    meta={
                        "start": ref["start"],
                        "end": ref["end"],
                        "text": ref.get("text"),
                        "reason": REASON_LEAVES_TO,
                        "reference_kind": ref.get("kind"),
                    },
                )
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
        """Where the reference stands (``start``/``end`` in the text; ``footnote`` instead
        for one of a footnote, which is no span of the text), its words and its parts."""
        place = (
            {"start": hit.start, "end": hit.end}
            if hit.footnote is None
            else {"footnote": hit.footnote}
        )
        meta: dict[str, Any] = {
            **place,
            "text": hit.text,
            "reference_kind": hit.kind,
            **hit.qualifier.to_dict(),
        }

        if hit.reason:
            meta["reason"] = hit.reason
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
