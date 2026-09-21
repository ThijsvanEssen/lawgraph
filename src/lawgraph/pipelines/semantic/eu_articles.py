"""Semantic pipeline that links EU instruments to national and EU articles."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable, Iterable

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_RAW_SOURCES,
    MAX_SEMANTIC_TEXT_LENGTH,
    RELATION_REFERS_TO,
    SOURCE_EURLEX,
)
from lawgraph.core.citations import (
    ArticleKind,
    CitationHit,
    coerce_text,
    hit_reason,
    make_snippet,
    normalize_code_aliases,
)
from lawgraph.core.eu_citations import (
    ARTICLE_NUMBER_ONE_LETTER,
    EUCitationConfidence,
    build_article_patterns,
    collect_article_hits,
    collect_bwb_id_hits,
    collect_celex_literal_hits,
    collect_year_number_hits,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import describe_since, iso_timestamp

from .base import CodeMapping, SemanticPipelineBase, slim

logger = get_logger(__name__)

SEMANTIC_SOURCE = "eu-article-linker"

# Confidences for the shared EU/BWB citation collectors (core.eu_citations).
_CONFIDENCE = EUCitationConfidence(
    article_with_instrument=0.85,  # "artikel X van Richtlijn/Verordening YYYY/N"
    celex_literal=0.90,  # CELEX ID literal in text
    instrument_year_number=0.70,  # directive/regulation via year + number only
    bwb_id=0.70,  # bare BWB id in text
)
_CONFIDENCE_BWB_ALIAS = 0.95  # "artikel X Sr/Sv/BW" via known short alias

# EU text: one optional letter on the article number, no "de" before the
# instrument name, and only directives and regulations.
_ARTICLE_PATTERNS = build_article_patterns(
    ARTICLE_NUMBER_ONE_LETTER,
    kinds=("directive", "regulation"),
    allow_determiner=False,
)
_ARTICLE_BWB_ALIAS_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]?)\s*(Sr|Sv|BW)\b", re.IGNORECASE
)


def detect_eu_citations(text: str, code_aliases: CodeMapping) -> list[CitationHit]:
    """Return references to EU or BWBR documents in the provided text."""
    if not text:
        return []

    normalized_codes = normalize_code_aliases(code_aliases)
    hits: list[CitationHit] = []
    seen: set[tuple[ArticleKind, str | None, str | None, str | None]] = set()

    def _record(hit: CitationHit) -> None:
        key = (hit.kind, hit.celex, hit.bwb_id, hit.article_number)
        if key in seen:
            return
        seen.add(key)
        hits.append(hit)

    collect_article_hits(
        text, _ARTICLE_PATTERNS, _CONFIDENCE.article_with_instrument, _record
    )
    collect_celex_literal_hits(text, _CONFIDENCE.celex_literal, _record)
    collect_year_number_hits(text, _CONFIDENCE.instrument_year_number, _record)
    _collect_bwb_alias_hits(text, normalized_codes, _record)
    collect_bwb_id_hits(text, _CONFIDENCE.bwb_id, _record)

    return hits


def _collect_bwb_alias_hits(
    text: str,
    normalized_codes: dict[str, str],
    record: Callable[[CitationHit], None],
) -> None:
    for match in _ARTICLE_BWB_ALIAS_PATTERN.finditer(text):
        article_number = match.group(1)
        alias = match.group(2)
        if not alias:
            continue
        bwb_id = normalized_codes.get(alias.strip().upper())
        if not bwb_id or not article_number:
            continue
        record(
            CitationHit(
                kind="article",
                bwb_id=bwb_id,
                article_number=article_number.strip(),
                confidence=_CONFIDENCE_BWB_ALIAS,
                raw_match=match.group(0),
                snippet=make_snippet(text, match.span()),
            )
        )


class EUArticlesSemanticPipeline(SemanticPipelineBase):
    """Pipeline linking EU instruments to BWB/EU articles via semantic edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        """Inspect EU instruments for referenced articles and persist semantic edges."""
        result = PipelineResult()
        since_iso = iso_timestamp(since)
        code_aliases = self._load_code_aliases()
        logger.info(
            "Processing EU articles for semantic article linking (since=%s).",
            describe_since(since),
        )
        # Streamed, not a list of every EU article with its text.
        documents = self._track(
            self._load_eu_documents(since_iso=since_iso), "EU articles"
        )

        edge_batch: list[dict[str, Any]] = []
        for document in documents:
            text = self._extract_document_text(document)
            if not text:
                result.skipped += 1
                continue

            hits = detect_eu_citations(text, code_aliases)
            if not hits:
                continue

            for hit in hits:
                target = self._resolve_target(hit)
                if not target:
                    continue
                self._queue_edge(
                    edge_batch,
                    self._make_edge_doc(
                        from_node=document,
                        to_node=target,
                        relation=RELATION_REFERS_TO,
                        source=SEMANTIC_SOURCE,
                        confidence=hit.confidence,
                        meta={
                            k: v
                            for k, v in {
                                "raw_match": hit.raw_match,
                                "snippet": hit.snippet,
                                "reason": hit_reason(hit),
                            }.items()
                            if v
                        },
                    ),
                    result,
                )

        self._write_batch(edge_batch, result)
        logger.info("EU article linker: %s.", result.summary())
        return result

    def _load_eu_documents(self, *, since_iso: str | None = None) -> Iterable[Node]:
        # Scan EU instrument *articles* — their props.text contains the actual
        # directive body, which is where cross-references to other articles live.
        if since_iso is not None:
            recent_celex: set[str] = set()
            aql = f"""
            FOR raw IN {COLLECTION_RAW_SOURCES}
                FILTER raw.source == @source
                FILTER raw.fetched_at >= @since
                FILTER raw.meta.celex != null
            RETURN raw.meta.celex
            """
            for row in self.store.query(
                aql, bind_vars={"source": SOURCE_EURLEX, "since": since_iso}
            ):
                if isinstance(row, str):
                    recent_celex.add(row)
                elif isinstance(row, dict):
                    c = row.get("meta", {}).get("celex")
                    if c:
                        recent_celex.add(str(c))
            if not recent_celex:
                return
            celex_list = list(recent_celex)
            aql = f"""
            FOR doc IN {COLLECTION_ARTICLES}
                FILTER doc.props.celex IN @celex_list
                RETURN {slim("doc", "celex", "article_number", "text", "display_name")}
            """
            for doc in self.store.query(aql, bind_vars={"celex_list": celex_list}):
                yield Node.from_document(COLLECTION_ARTICLES, doc)
        else:
            aql = f"""
            FOR doc IN {COLLECTION_ARTICLES}
                FILTER doc.props.celex != null
                RETURN {slim("doc", "celex", "article_number", "text", "display_name")}
            """
            for doc in self.store.query(aql):
                yield Node.from_document(COLLECTION_ARTICLES, doc)

    def _extract_document_text(self, document: Node) -> str | None:
        # EU instrument_articles store their text directly in props.text.
        text = coerce_text(document.props.get("text"))
        if text:
            return text[:MAX_SEMANTIC_TEXT_LENGTH]
        # Fallback: title only (gives minimal signal but avoids skipping entirely)
        return coerce_text(document.props.get("display_name"))

    def _resolve_article_node(
        self, hit: CitationHit, identifier: str, id_prop: str
    ) -> Node | None:
        key = make_node_key(identifier, hit.article_number)
        node = self._lookup_node(COLLECTION_ARTICLES, key)
        if node is None and hit.confidence >= 0.85:
            stub = Node(
                collection=COLLECTION_ARTICLES,
                key=key,
                type=NodeType.ARTICLE,
                props={
                    id_prop: identifier,
                    "article_number": hit.article_number,
                    "stub": True,
                    "display_name": f"Artikel {hit.article_number} ({identifier})",
                },
            )
            node, _ = self.store.insert_or_update(stub)
            self._remember_node(node)
        if node is None:
            logger.debug(
                "EU semantic: no node found for %s %s (confidence=%.2f)",
                hit.kind,
                identifier,
                hit.confidence,
            )
        return node

    def _resolve_target(self, hit: CitationHit) -> Node | None:
        # Dutch article: BWB id + article number.
        if hit.kind == "article" and hit.bwb_id and hit.article_number:
            return self._resolve_article_node(hit, hit.bwb_id, "bwb_id")
        # EU article: CELEX + article number (cross-reference within or between directives).
        if hit.kind == "article" and hit.celex and hit.article_number:
            return self._resolve_article_node(hit, hit.celex, "celex")
        # Whole-instrument reference.
        if hit.celex:
            key = make_node_key(hit.celex)
            node = self._lookup_node(COLLECTION_INSTRUMENTS, key)
            if node is None:
                logger.debug(
                    "EU semantic: no node found for %s %s (confidence=%.2f)",
                    hit.kind,
                    hit.bwb_id or hit.celex,
                    hit.confidence,
                )
            return node
        if hit.bwb_id:
            key = make_node_key(hit.bwb_id)
            node = self._lookup_node(COLLECTION_INSTRUMENTS, key)
            if node is None:
                logger.debug(
                    "EU semantic: no node found for %s %s (confidence=%.2f)",
                    hit.kind,
                    hit.bwb_id or hit.celex,
                    hit.confidence,
                )
            return node
        return None
