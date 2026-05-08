"""Semantic linkage pipeline for Rechtspraak judgments and BWB articles."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable, Iterable

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    RELATION_CITES_ARTICLE,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.utils.time import describe_since, iso_timestamp

from .base import SemanticPipelineBase
from .citation_detect import CitationHit, make_snippet, strip_xml

logger = get_logger(__name__)

CodeMapping = dict[str, str]  # re-exported for backwards compatibility
SEMANTIC_SOURCE = "rechtspraak-article-linker"

_ALIAS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bart\.\s*(\d+[a-z]?)\s*(Sr|Sv|WVW|EVRM|BW)\b", re.IGNORECASE),
    re.compile(r"\bartikel\s+(\d+[a-z]?)\s*(Sr|Sv|WVW|EVRM|BW)\b", re.IGNORECASE),
)

_NUMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bartikel\s+(\d+[a-z]?)\b", re.IGNORECASE),
    re.compile(r"\bart\.\s*(\d+[a-z]?)\b", re.IGNORECASE),
)


def detect_article_references(
    text: str | None,
    mapping: dict[str, str],
) -> list[CitationHit]:
    """Return article hints detected in the text together with confidence values."""
    if not text:
        return []

    normalized_mapping: dict[str, str] = {
        alias.upper(): bwb_id for alias, bwb_id in mapping.items() if alias and bwb_id
    }

    hits: list[CitationHit] = []
    seen_pairs: set[tuple[str, str]] = set()
    alias_spans: list[tuple[int, int]] = []

    def _record_alias(match: re.Match[str], identifier: str) -> None:
        article_number = match.group(1)
        if not article_number:
            return
        pair = (identifier, article_number)
        if pair in seen_pairs:
            return
        seen_pairs.add(pair)
        alias_spans.append(match.span())
        is_bwb = identifier.upper().startswith("BWBR")
        hits.append(
            CitationHit(
                kind="article",
                bwb_id=identifier if is_bwb else None,
                celex=None if is_bwb else identifier,
                article_number=article_number,
                confidence=0.95,
                raw_match=match.group(0),
                snippet=make_snippet(text, match.span()),
            )
        )

    def _record_number(match: re.Match[str]) -> None:
        span = match.span()
        if any(
            not (span[1] <= span_start or span[0] >= span_end)
            for span_start, span_end in alias_spans
        ):
            return
        article_number = match.group(1)
        if not article_number:
            return
        pair = ("", article_number)
        if pair in seen_pairs:
            return
        seen_pairs.add(pair)
        hits.append(
            CitationHit(
                kind="article",
                bwb_id=None,
                article_number=article_number,
                confidence=0.35,
                raw_match=match.group(0),
                snippet=make_snippet(text, span),
            )
        )

    _collect_alias_patterns(text, normalized_mapping, _record_alias)
    _collect_number_patterns(text, alias_spans, _record_number)

    return hits


def _collect_alias_patterns(
    text: str,
    normalized_mapping: dict[str, str],
    record: Callable[[re.Match[str], str], None],
) -> None:
    for pattern in _ALIAS_PATTERNS:
        for match in pattern.finditer(text):
            alias = match.group(2)
            if not alias:
                continue
            identifier = normalized_mapping.get(alias.upper())
            if not identifier:
                continue
            record(match, identifier)


def _collect_number_patterns(
    text: str,
    alias_spans: list[tuple[int, int]],
    record: Callable[[re.Match[str]], None],
) -> None:
    for pattern in _NUMBER_PATTERNS:
        for match in pattern.finditer(text):
            span = match.span()
            if any(
                not (span[1] <= span_start or span[0] >= span_end)
                for span_start, span_end in alias_spans
            ):
                continue
            record(match)


class RechtspraakArticleSemanticPipeline(SemanticPipelineBase):
    """Link Rechtspraak judgments to BWB articles via semantic edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        """Create semantic edges for Rechtspraak judgments referencing BWB articles."""
        result = PipelineResult()
        since_iso = iso_timestamp(since)
        eclis = self._recent_rechtspraak_eclis(since_iso)
        judgments = list(self._load_judgments(eclis))

        mapping = self._load_code_aliases()
        if not mapping:
            logger.warning("No code_aliases configured; skipping semantic linkage.")
            return result

        logger.info(
            "Processing %d Rechtspraak judgments for article references (since=%s).",
            len(judgments),
            describe_since(since),
        )

        for doc in judgments:
            judgment = Node.from_document(COLLECTION_JUDGMENTS, doc)
            raw_text = self._extract_judgment_text(judgment)
            # Strip XML/HTML tags before running regex patterns — a reference split
            # across a tag boundary would be missed; content inside attributes matched.
            text = strip_xml(raw_text) if raw_text else None
            hits = detect_article_references(text, mapping)
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
        """Resolve a citation hit to an article node, creating a stub if needed.

        Only stubs are created for high-confidence (≥ 0.9) hits so that
        low-quality bare-number matches don't litter the graph with noise.
        """
        # Dutch article: BWB id + article number.
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
            return node
        # EU/treaty article: CELEX + article number (e.g. EVRM).
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
                FILTER doc.props.meta.ecli IN @eclis
            RETURN doc
            """
        else:
            bind_vars = {}
            aql = f"FOR doc IN {collection} RETURN doc"

        return self.store.query(aql, bind_vars=bind_vars)

    def _extract_judgment_text(self, judgment: Node) -> str | None:
        props = judgment.props
        text = props.get("raw_xml")
        if isinstance(text, str) and text.strip():
            return text
        alternative = props.get("text")
        if isinstance(alternative, str) and alternative.strip():
            return alternative
        return None
