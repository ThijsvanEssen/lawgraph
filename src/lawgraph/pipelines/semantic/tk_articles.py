"""Semantic linkage pipeline that connects TK documents to the articles they cite."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable, Iterable

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_RAW_SOURCES,
    MAX_SEMANTIC_TEXT_LENGTH,
    RAW_KIND_TK_DOCUMENT,
    RELATION_REFERS_TO,
    SOURCE_TK,
)
from lawgraph.core.aliases import InstrumentAliasMap
from lawgraph.core.citations import (
    CitationHit,
    DutchCitationExtractor,
    coerce_text,
    hit_reason,
    make_snippet,
)
from lawgraph.core.eu_citations import (
    ARTICLE_NUMBER_ANY_LETTERS,
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

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "tk-article-linker"

# ---------------------------------------------------------------------------
# Instrument-level patterns (not driven by registry — EU/BWBR literal forms)
# ---------------------------------------------------------------------------

_CONFIDENCE = EUCitationConfidence(
    article_with_instrument=0.88,  # "artikel X van Richtlijn/Besluit/... YYYY/N"
    celex_literal=0.90,  # CELEX ID literal in text
    instrument_year_number=0.65,  # directive/regulation via year + number only
    bwb_id=0.75,  # bare BWB id in text
)

# TK text: any letters on the article number, "de"/"het" allowed before the
# instrument name, and decisions and framework decisions as well.
_EU_ARTICLE_PATTERNS = build_article_patterns(
    ARTICLE_NUMBER_ANY_LETTERS,
    kinds=("directive", "regulation", "decision", "framework_decision"),
    allow_determiner=True,
)

# ---------------------------------------------------------------------------
# Instrument-level hit collectors
# ---------------------------------------------------------------------------


def _build_named_act_patterns(
    aliases: InstrumentAliasMap,
) -> list[tuple[str, re.Pattern[str], str | None, str | None]]:
    patterns: list[tuple[str, re.Pattern[str], str | None, str | None]] = []
    for label, (bwb_id, celex) in aliases.items():
        if not (bwb_id or celex):
            continue
        escaped = re.escape(label)
        pattern = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
        patterns.append((label, pattern, bwb_id, celex))
    return patterns


def _collect_named_act_hits(
    text: str,
    patterns: list[tuple[str, re.Pattern[str], str | None, str | None]],
    record: Callable[[CitationHit], None],
) -> None:
    for _, pattern, bwb_id, celex in patterns:
        for match in pattern.finditer(text):
            record(
                CitationHit(
                    kind="instrument",
                    bwb_id=bwb_id,
                    celex=celex,
                    confidence=0.6,
                    raw_match=match.group(0),
                    snippet=make_snippet(text, match.span()),
                )
            )


def detect_tk_citations(
    text: str,
    code_aliases: dict[str, str],
    instrument_aliases: InstrumentAliasMap,
) -> list[CitationHit]:
    """Detect article and instrument citations in the text of a TK document."""
    if not text:
        return []

    return _collect_tk_hits(
        text,
        _extractor(code_aliases, instrument_aliases),
        _build_named_act_patterns(instrument_aliases),
    )


def _extractor(
    code_aliases: dict[str, str], instrument_aliases: InstrumentAliasMap
) -> DutchCitationExtractor:
    """Extractor that resolves law codes and full law names ("artikel 5 van de Wegenwet")."""
    name_aliases = {
        name: bwb_id or celex
        for name, (bwb_id, celex) in instrument_aliases.items()
        if bwb_id or celex
    }
    return DutchCitationExtractor(code_aliases=code_aliases, name_aliases=name_aliases)


def _collect_tk_hits(
    text: str,
    extractor: DutchCitationExtractor,
    named_act_patterns: list[tuple[str, re.Pattern[str], str | None, str | None]],
) -> list[CitationHit]:
    """Registry-driven article hits plus every instrument-level TK pattern."""
    hits = extractor.extract(text)

    def _identity(hit: CitationHit) -> tuple[str, str | None, str | None, str | None]:
        return (hit.kind, hit.bwb_id, hit.celex, hit.article_number)

    seen = {_identity(h) for h in hits}

    def _record(hit: CitationHit) -> None:
        if _identity(hit) in seen:
            return
        seen.add(_identity(hit))
        hits.append(hit)

    _collect_named_act_hits(text, named_act_patterns, _record)
    collect_bwb_id_hits(text, _CONFIDENCE.bwb_id, _record)
    collect_celex_literal_hits(text, _CONFIDENCE.celex_literal, _record)
    collect_year_number_hits(text, _CONFIDENCE.instrument_year_number, _record)
    collect_article_hits(
        text, _EU_ARTICLE_PATTERNS, _CONFIDENCE.article_with_instrument, _record
    )

    return hits


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TKArticlesSemanticPipeline(SemanticPipelineBase):
    """Pipeline connecting TK documents to the articles and instruments they cite."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)

        code_aliases = self._load_code_aliases()
        instrument_aliases = self._load_instrument_aliases()
        if not code_aliases and not instrument_aliases:
            logger.warning(
                "No instrument or code aliases configured for TK semantic linking."
            )

        extractor = _extractor(code_aliases, instrument_aliases)
        named_act_patterns = _build_named_act_patterns(instrument_aliases)

        logger.info(
            "Processing TK documents for semantic linking (since=%s).",
            describe_since(since),
        )

        edge_batch: list[dict[str, Any]] = []
        doc_count = 0

        for document in self._load_tk_documents(since_iso=since_iso):
            doc_count += 1
            text = self._extract_document_text(document)
            if not text:
                result.skipped += 1
                continue

            hits = _collect_tk_hits(text, extractor, named_act_patterns)
            if not hits:
                continue

            for hit in hits:
                target_node = self._resolve_target_node(hit)
                if not target_node:
                    continue
                meta = {
                    k: v
                    for k, v in {
                        "raw_match": hit.raw_match,
                        "snippet": hit.snippet,
                        "reason": hit_reason(hit),
                        "qualifier": hit.qualifier,
                    }.items()
                    if v
                }
                edge_doc = self._make_edge_doc(
                    from_node=document,
                    to_node=target_node,
                    relation=RELATION_REFERS_TO,
                    source=SEMANTIC_SOURCE,
                    confidence=hit.confidence,
                    meta=meta,
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
            "TK semantic article linker: processed %d documents, %s.",
            doc_count,
            result.summary(),
        )
        return result

    def _load_tk_documents(self, *, since_iso: str | None = None) -> Iterable[Node]:
        """TK documents; only a Document may be the source of a REFERS_TO edge."""
        bind_vars: dict[str, Any] | None = None
        id_filter = ""
        if since_iso is not None:
            recent_ids = self._recent_external_ids(since_iso)
            if not recent_ids:
                return
            id_filter = "    FILTER doc.props.external_id IN @ids\n"
            bind_vars = {"ids": sorted(recent_ids)}

        aql = (
            f"FOR doc IN {COLLECTION_DOCUMENTS}\n"
            '    FILTER "TK" IN doc.labels\n'
            f"{id_filter}"
            "    RETURN doc"
        )
        for doc in self.store.query(aql, bind_vars=bind_vars):
            yield Node.from_document(COLLECTION_DOCUMENTS, doc)

    def _recent_external_ids(self, since_iso: str) -> set[str]:
        """External ids of TK documents fetched at or after *since_iso*."""
        aql = f"""
        FOR raw IN {COLLECTION_RAW_SOURCES}
            FILTER raw.source == @source AND raw.kind == @kind
            FILTER raw.fetched_at >= @since
            FILTER raw.external_id != null
        RETURN raw.external_id
        """
        rows = self.store.query(
            aql,
            bind_vars={
                "source": SOURCE_TK,
                "kind": RAW_KIND_TK_DOCUMENT,
                "since": since_iso,
            },
        )
        return {str(row) for row in rows if isinstance(row, str)}

    def _resolve_target_node(self, hit: CitationHit) -> Node | None:
        if hit.kind == "article" and hit.bwb_id and hit.article_number:
            key = make_node_key(hit.bwb_id, hit.article_number)
            node = self._lookup_node(COLLECTION_ARTICLES, key)
            if node is None and hit.confidence >= 0.85:
                stub = Node(
                    collection=COLLECTION_ARTICLES,
                    key=key,
                    type=NodeType.ARTICLE,
                    props={
                        "bwb_id": hit.bwb_id,
                        "article_number": hit.article_number,
                        "stub": True,
                        "display_name": f"Artikel {hit.article_number} ({hit.bwb_id})",
                    },
                )
                node, _ = self.store.insert_or_update(stub)
                self._remember_node(node)
            if node is None:
                logger.debug(
                    "TK semantic: no node found for %s %s (confidence=%.2f)",
                    hit.kind,
                    hit.bwb_id or hit.celex,
                    hit.confidence,
                )
            return node

        if hit.kind == "article" and hit.celex and hit.article_number:
            key = make_node_key(hit.celex, hit.article_number)
            node = self._lookup_node(COLLECTION_ARTICLES, key)
            if node is None and hit.confidence >= 0.85:
                stub = Node(
                    collection=COLLECTION_ARTICLES,
                    key=key,
                    type=NodeType.ARTICLE,
                    props={
                        "celex": hit.celex,
                        "article_number": hit.article_number,
                        "stub": True,
                        "display_name": f"Artikel {hit.article_number} ({hit.celex})",
                    },
                )
                node, _ = self.store.insert_or_update(stub)
                self._remember_node(node)
            if node is None:
                logger.debug(
                    "TK semantic: no node found for %s %s (confidence=%.2f)",
                    hit.kind,
                    hit.bwb_id or hit.celex,
                    hit.confidence,
                )
            return node

        if hit.celex:
            key = make_node_key(hit.celex)
            node = self._lookup_node(COLLECTION_INSTRUMENTS, key)
            if node is None:
                logger.debug("TK semantic: no instrument node for CELEX %s", hit.celex)
            return node

        if hit.bwb_id:
            key = make_node_key(hit.bwb_id)
            node = self._lookup_node(COLLECTION_INSTRUMENTS, key)
            if node is None:
                logger.debug("TK semantic: no instrument node for BWB %s", hit.bwb_id)
            return node

        return None

    def _extract_document_text(self, document: Node) -> str | None:
        fragments: list[str] = []
        total_length = 0
        for key in ("title", "summary", "body", "text"):
            candidate = document.props.get(key)
            text_value = coerce_text(candidate)
            if not text_value:
                continue
            fragments.append(text_value)
            total_length += len(text_value)

        total_length = self._collect_raw_text(
            document.props.get("raw"), fragments, total_length
        )
        if not fragments:
            return None
        text = "\n".join(fragments)
        if len(text) >= MAX_SEMANTIC_TEXT_LENGTH:
            logger.debug(
                "TK semantic: document text reached collection limit of %d chars (node %s).",
                MAX_SEMANTIC_TEXT_LENGTH,
                document.key,
            )
        return text

    def _collect_raw_text(
        self,
        value: Any,
        fragments: list[str],
        current_length: int,
    ) -> int:
        if current_length >= MAX_SEMANTIC_TEXT_LENGTH:
            return current_length
        if isinstance(value, str):
            snippet = value.strip()
            if snippet:
                fragments.append(snippet)
                current_length += len(snippet)
        elif isinstance(value, dict):
            current_length = self._collect_from_dict(value, fragments, current_length)
        elif isinstance(value, list):
            current_length = self._collect_from_list(value, fragments, current_length)
        return current_length

    def _collect_from_dict(
        self,
        value: dict[str, Any],
        fragments: list[str],
        current_length: int,
    ) -> int:
        for child in value.values():
            current_length = self._collect_raw_text(child, fragments, current_length)
            if current_length >= MAX_SEMANTIC_TEXT_LENGTH:
                break
        return current_length

    def _collect_from_list(
        self,
        value: list[Any],
        fragments: list[str],
        current_length: int,
    ) -> int:
        for item in value:
            current_length = self._collect_raw_text(item, fragments, current_length)
            if current_length >= MAX_SEMANTIC_TEXT_LENGTH:
                break
        return current_length
