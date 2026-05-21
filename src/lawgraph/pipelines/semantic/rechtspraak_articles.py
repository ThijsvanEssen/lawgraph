"""Semantic linkage pipeline for Rechtspraak judgments and BWB articles."""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    RELATION_CITES_ARTICLE,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import describe_since, iso_timestamp

from .base import SemanticPipelineBase
from .citation_detect import CitationHit, DutchCitationExtractor, _hit_reason, strip_xml

logger = get_logger(__name__)

# Exported for backward compatibility with existing tests and callers.
CodeMapping = dict[str, str]

SEMANTIC_SOURCE = "rechtspraak-article-linker"


# ---------------------------------------------------------------------------
# Backward-compat public function
# ---------------------------------------------------------------------------


def detect_article_references(
    text: str | None,
    mapping: dict[str, str],
) -> list[CitationHit]:
    """Return article citations detected in *text*.

    Thin wrapper around ``DutchCitationExtractor`` kept for backward compat.
    Also appends bare ``artikel X`` hits (no law code, confidence 0.35) so
    that callers which depend on low-confidence bare detection still work.
    """
    if not text:
        return []
    extractor = DutchCitationExtractor(code_aliases=mapping)
    hits = extractor.extract(text)
    coded_nums = {h.article_number for h in hits if h.article_number}
    bare = extractor.extract_bare(text, confidence=0.35)
    hits.extend(b for b in bare if b.article_number not in coded_nums)
    return hits


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class RechtspraakArticleSemanticPipeline(SemanticPipelineBase):
    """Link Rechtspraak judgments to BWB articles via semantic edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)
        eclis = self._recent_rechtspraak_eclis(since_iso)
        judgments = list(self._load_judgments(eclis))

        mapping = self._load_code_aliases()
        if not mapping:
            logger.warning("No code_aliases configured; skipping semantic linkage.")
            return result

        extractor = DutchCitationExtractor(code_aliases=mapping)

        logger.info(
            "Processing %d Rechtspraak judgments for article references (since=%s).",
            len(judgments),
            describe_since(since),
        )

        for doc in judgments:
            judgment = Node.from_document(COLLECTION_JUDGMENTS, doc)
            raw_text = self._extract_judgment_text(judgment)
            text = strip_xml(raw_text) if raw_text else None
            hits = extractor.extract(text or "")
            if not hits:
                continue

            for hit in hits:
                if not hit.bwb_id and not hit.celex:
                    continue

                article = self._resolve_article(hit)
                if article is None:
                    continue

                created = self._create_semantic_edge(
                    from_node=judgment,
                    to_node=article,
                    relation=RELATION_CITES_ARTICLE,
                    source=SEMANTIC_SOURCE,
                    confidence=hit.confidence,
                    meta={
                        k: v
                        for k, v in {
                            "raw_match": hit.raw_match,
                            "snippet": hit.snippet,
                            "reason": _hit_reason(hit),
                            "qualifier": hit.qualifier,
                        }.items()
                        if v
                    },
                    result=result,
                )
                if created:
                    result.created += 1
                else:
                    result.updated += 1

        logger.info("Rechtspraak article linker: %s.", result.summary())
        return result

    def _resolve_article(self, hit: CitationHit) -> Node | None:
        if hit.bwb_id and hit.article_number:
            article_key = make_node_key(hit.bwb_id, hit.article_number)
            node = self.store.get_node(COLLECTION_INSTRUMENT_ARTICLES, article_key)
            if node is None and hit.confidence >= 0.9:
                node = self.store.ensure_stub_node(
                    COLLECTION_INSTRUMENT_ARTICLES,
                    article_key,
                    NodeType.ARTICLE,
                    props={"bwb_id": hit.bwb_id, "article_number": hit.article_number},
                )
            if node is None:
                logger.debug(
                    "Rechtspraak semantic: no node for article %s %s (conf=%.2f)",
                    hit.bwb_id,
                    hit.article_number,
                    hit.confidence,
                )
            return node

        if hit.celex and hit.article_number:
            article_key = make_node_key(hit.celex, hit.article_number)
            node = self.store.get_node(COLLECTION_INSTRUMENT_ARTICLES, article_key)
            if node is None and hit.confidence >= 0.9:
                node = self.store.ensure_stub_node(
                    COLLECTION_INSTRUMENT_ARTICLES,
                    article_key,
                    NodeType.ARTICLE,
                    props={"celex": hit.celex, "article_number": hit.article_number},
                )
            if node is None:
                logger.debug(
                    "Rechtspraak semantic: no node for article %s %s (conf=%.2f)",
                    hit.celex,
                    hit.article_number,
                    hit.confidence,
                )
            return node

        return None

    def _recent_rechtspraak_eclis(self, since_iso: str | None) -> set[str]:
        if since_iso is None:
            return set()

        bind_vars = {
            "source": SOURCE_RECHTSPRAAK,
            "kind": RAW_KIND_RS_CONTENT,
            "since": since_iso,
        }
        aql = """
        FOR raw IN raw_sources
            FILTER raw.source == @source
            FILTER raw.kind == @kind
            FILTER raw.fetched_at >= @since
            FILTER raw.meta.ecli != null
        RETURN raw.meta.ecli
        """
        eclis: set[str] = set()
        for raw in self.store.query(aql, bind_vars=bind_vars):
            ecli_value = raw.get("meta", {}).get("ecli")
            if isinstance(ecli_value, str):
                eclis.add(ecli_value)
        return eclis

    def _load_judgments(self, eclis: Iterable[str]) -> Iterable[dict[str, Any]]:
        collection = COLLECTION_JUDGMENTS
        if eclis:
            bind_vars = {"eclis": list(eclis)}
            aql = f"""
            FOR doc IN {collection}
                FILTER doc.props.meta != null
                FILTER doc.props.meta.ecli IN @eclis
            RETURN doc
            """
        else:
            bind_vars = {}
            aql = f"FOR doc IN {collection} RETURN doc"
        return self.store.query(aql, bind_vars=bind_vars)

    def _extract_judgment_text(self, judgment: Node) -> str | None:
        props = judgment.props
        fragments: list[str] = []
        for key in ("raw_xml", "text", "summary"):
            value = props.get(key)
            if isinstance(value, str) and value.strip():
                fragments.append(value.strip())
        return "\n\n".join(fragments) if fragments else None
