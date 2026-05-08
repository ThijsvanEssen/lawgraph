"""Semantic pipeline that links BWB articles referenced inside other articles."""

from __future__ import annotations

from typing import Any, Iterable

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENT_ARTICLES,
    RELATION_REFERS_TO_ARTICLE,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node, PipelineResult, make_node_key
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
        domain_profile: str | None = None,
        domain_config: dict[str, Any] | None = None,
        store_citations: bool = False,
    ) -> None:
        super().__init__(
            store=store, domain_profile=domain_profile, domain_config=domain_config
        )
        self._store_citations = store_citations

    def run(self, *, since: Any = None) -> PipelineResult:
        """Create semantic edges for article references detected inside BWB articles."""
        result = PipelineResult()
        config = self._load_domain_config()
        bwb_ids = self._load_bwb_ids(config)
        if not bwb_ids:
            logger.warning(
                "No BWB IDs configured for semantic linking; skipping detection."
            )
            return result

        articles = list(self._load_articles(bwb_ids))
        if not articles:
            logger.info("No BWB articles found for semantic linking.")
            return result

        logger.info(
            "Scanning %d BWB articles for internal references (profile=%s).",
            len(articles),
            self._domain_profile_name or "default",
        )

        hits_detected = 0
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

            detect_config = {
                **(config or {}),
                "code_aliases": config.get("code_aliases") or {},
                "instrument_aliases": config.get("instrument_aliases") or {},
            }
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

                created = self._create_semantic_edge(
                    from_node=article,
                    to_node=target,
                    relation=RELATION_REFERS_TO_ARTICLE,
                    source=SEMANTIC_SOURCE,
                    confidence=hit.confidence,
                    meta={"start": hit.start, "end": hit.end, "text": hit.text},
                    result=result,
                )
                if created:
                    result.created += 1
                else:
                    result.updated += 1

        logger.info(
            "BWB article linker: %d citations detected, %s.",
            hits_detected,
            result.summary(),
        )
        return result

    def _load_articles(self, bwb_ids: list[str]) -> Iterable[dict[str, Any]]:
        bind_vars = {"bwb_ids": bwb_ids}
        aql = f"""
        FOR doc IN {COLLECTION_INSTRUMENT_ARTICLES}
            FILTER doc.props.bwb_id IN @bwb_ids
            FILTER doc.props.text != null
        RETURN doc
        """
        return self.store.query(aql, bind_vars=bind_vars)

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

    def _load_bwb_ids(self, config: dict[str, Any]) -> list[str]:
        bwb_section = config.get("bwb")
        if not isinstance(bwb_section, dict):
            return []

        ids = bwb_section.get("ids", [])
        return [str(value).strip() for value in ids if value]
