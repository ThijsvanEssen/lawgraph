"""Semantic linkage pipeline that connects TK publications to legal articles."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable, Iterable

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_PROCEDURES,
    COLLECTION_PUBLICATIONS,
    RELATION_EXPLAINS_ARTICLE,
    RELATION_MENTIONS_ARTICLE,
    RELATION_MENTIONS_INSTRUMENT,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node, PipelineResult, make_node_key
from lawgraph.utils.time import describe_since

from .base import InstrumentAliasMap, SemanticPipelineBase, _parse_instrument_aliases
from .citation_detect import (
    ArticleKind,
    CitationHit,
    coerce_text,
    format_celex,
    make_snippet,
    normalize_code_aliases,
)

logger = get_logger(__name__)

CodeMapping = dict[str, str]
SEMANTIC_SOURCE = "tk-article-linker"

_MAX_TEXT_LENGTH = 200_000

# Soort values that indicate an explanatory (MvT) document.
# Matching is case-insensitive on the substring "toelichting".
_MVT_SOORT_MARKER = "toelichting"


def _pick_tk_relation(document: Node, hit_kind: ArticleKind) -> str:
    """Return the semantically correct relation type for a TK → article edge.

    - EXPLAINS_ARTICLE: the source document is a Memorie/Nota van Toelichting
      explicitly explaining an article (most valuable signal for the reader view).
    - MENTIONS_ARTICLE: any other TK publication that references an article.
    - MENTIONS_INSTRUMENT: the hit refers to a whole instrument, not a specific article.
    """
    if hit_kind == "instrument":
        return RELATION_MENTIONS_INSTRUMENT
    # Distinguish MvT documents from other TK publications.
    soort = str(document.props.get("soort") or "").lower()
    if _MVT_SOORT_MARKER in soort:
        return RELATION_EXPLAINS_ARTICLE
    return RELATION_MENTIONS_ARTICLE


_BWBR_PATTERN = re.compile(r"\b(BWBR0\d{6})\b", re.IGNORECASE)
_ARTICLE_ALIAS_PATTERNS = (
    re.compile(r"\bartikel\s+(\d+[a-z]*)\s*(Sr|Sv|BW|EVRM)\b", re.IGNORECASE),
    re.compile(r"\bart\.\s*(\d+[a-z]*)\s*(Sr|Sv|BW)\b", re.IGNORECASE),
)
_CELEX_DIRECT_PATTERN = re.compile(r"\bCELEX:([0-9A-Z()\\/\.\-]+)\b", re.IGNORECASE)
_RICHTLIJN_PATTERN = re.compile(
    r"\bRichtlijn\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE
)
_VERORDENING_PATTERN = re.compile(
    r"\bVerordening\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE
)
# Article-level references to EU directives and regulations, e.g.
# "artikel 3 van Richtlijn 2010/64/EU" or "artikel 4 van Verordening 2016/679".
_ARTICLE_RICHTLIJN_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]*)\s+van\s+(?:de\s+)?[Rr]ichtlijn\s+(\d{4})/(\d+)(?:/EU|/EG)?\b",
    re.IGNORECASE,
)
_ARTICLE_VERORDENING_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]*)\s+van\s+(?:de\s+)?[Vv]erordening\s+(\d{4})/(\d+)(?:/EU|/EG)?\b",
    re.IGNORECASE,
)


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


def detect_tk_citations(
    text: str,
    code_aliases: dict[str, str],
    instrument_aliases: InstrumentAliasMap | dict[str, Any],
) -> list[CitationHit]:
    """Return articles/instruments referenced in the provided TK text.

    instrument_aliases may be a raw config dict (string values) or a parsed
    InstrumentAliasMap (tuple values); both are accepted.
    """
    if not text:
        return []

    normalized_codes = normalize_code_aliases(code_aliases)
    parsed_aliases: InstrumentAliasMap = _parse_instrument_aliases(instrument_aliases)
    named_act_patterns = _build_named_act_patterns(parsed_aliases)

    hits: list[CitationHit] = []
    seen: set[tuple[ArticleKind, str | None, str | None, str | None]] = set()

    def _record(hit: CitationHit) -> None:
        key = (hit.kind, hit.bwb_id, hit.article_number, hit.celex)
        if key in seen:
            return
        seen.add(key)
        hits.append(hit)

    _collect_named_act_hits(text, named_act_patterns, _record)
    _collect_bwbr_hits(text, _record)
    _collect_article_alias_hits(text, normalized_codes, _record)
    # EU article-level patterns must run before the whole-instrument patterns
    # so that "artikel 3 van Richtlijn 2010/64" is de-duplicated as an article
    # hit rather than being overshadowed by a plain "Richtlijn 2010/64" hit.
    _collect_eu_article_hits(text, _record)
    _collect_celex_hits(text, _record)
    _collect_eu_hits(text, _record)

    return hits


def _make_hit_snippet(
    text: str,
    match: re.Match[str],
    *,
    kind: ArticleKind,
    bwb_id: str | None = None,
    article_number: str | None = None,
    celex: str | None = None,
    confidence: float = 0.0,
) -> CitationHit:
    return CitationHit(
        kind=kind,
        bwb_id=bwb_id,
        article_number=article_number,
        celex=celex,
        confidence=confidence,
        raw_match=match.group(0),
        snippet=make_snippet(text, match.span()),
    )


def _collect_named_act_hits(
    text: str,
    patterns: list[tuple[str, re.Pattern[str], str | None, str | None]],
    record: Callable[[CitationHit], None],
) -> None:
    for _, pattern, bwb_id, celex in patterns:
        for match in pattern.finditer(text):
            record(
                _make_hit_snippet(
                    text,
                    match,
                    kind="instrument",
                    bwb_id=bwb_id,
                    celex=celex,
                    confidence=0.6,
                )
            )


def _collect_bwbr_hits(
    text: str,
    record: Callable[[CitationHit], None],
) -> None:
    for match in _BWBR_PATTERN.finditer(text):
        identifier = match.group(1)
        if not identifier:
            continue
        record(
            _make_hit_snippet(
                text,
                match,
                kind="instrument",
                bwb_id=identifier.upper(),
                confidence=0.75,
            )
        )


def _collect_article_alias_hits(
    text: str,
    normalized_codes: dict[str, str],
    record: Callable[[CitationHit], None],
) -> None:
    for pattern in _ARTICLE_ALIAS_PATTERNS:
        for match in pattern.finditer(text):
            article_number = match.group(1)
            alias = match.group(2)
            if not alias or not article_number:
                continue
            identifier = normalized_codes.get(alias.strip().upper())
            if not identifier:
                continue
            # Distinguish BWB identifiers (start with "BWBR") from CELEX values
            # (e.g. EVRM → "21970A0718(02)").  Both map to an article node but
            # via different key fields.
            is_bwb = identifier.upper().startswith("BWBR")
            record(
                _make_hit_snippet(
                    text,
                    match,
                    kind="article",
                    bwb_id=identifier if is_bwb else None,
                    celex=None if is_bwb else identifier,
                    article_number=article_number.strip(),
                    confidence=0.95,
                )
            )


def _collect_eu_article_hits(
    text: str,
    record: Callable[[CitationHit], None],
) -> None:
    """Collect article-level references to EU directives and regulations."""
    for pattern, kind in (
        (_ARTICLE_RICHTLIJN_PATTERN, "directive"),
        (_ARTICLE_VERORDENING_PATTERN, "regulation"),
    ):
        for match in pattern.finditer(text):
            article_number = match.group(1)
            year = match.group(2)
            number_value = match.group(3)
            letter = "L" if kind == "directive" else "R"
            try:
                padded = int(number_value)
            except ValueError:
                padded = 0
            celex = f"3{year}{letter}{padded:04d}"
            record(
                _make_hit_snippet(
                    text,
                    match,
                    kind="article",
                    celex=celex,
                    article_number=article_number.strip(),
                    confidence=0.88,
                )
            )


def _collect_celex_hits(
    text: str,
    record: Callable[[CitationHit], None],
) -> None:
    for match in _CELEX_DIRECT_PATTERN.finditer(text):
        celex_value = match.group(1)
        if not celex_value:
            continue
        record(
            _make_hit_snippet(
                text,
                match,
                kind="instrument",
                celex=celex_value.upper(),
                confidence=0.9,
            )
        )


def _collect_eu_hits(
    text: str,
    record: Callable[[CitationHit], None],
) -> None:
    for pattern, kind in (
        (_RICHTLIJN_PATTERN, "directive"),
        (_VERORDENING_PATTERN, "regulation"),
    ):
        for match in pattern.finditer(text):
            celex_value = format_celex(kind, match.group(1), match.group(2))
            record(
                _make_hit_snippet(
                    text,
                    match,
                    kind="instrument",
                    celex=celex_value,
                    confidence=0.65,
                )
            )


class TKArticleSemanticPipeline(SemanticPipelineBase):
    """Pipeline connecting TK publications and procedures to legal articles."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        """Scan stored TK documents and create semantic edges for referenced articles."""
        result = PipelineResult()
        documents = list(self._load_tk_documents())
        if not documents:
            logger.debug("No TK documents found for semantic linking.")
            return result

        code_aliases = self._load_code_aliases()
        instrument_aliases = self._load_instrument_aliases()
        if not code_aliases and not instrument_aliases:
            logger.warning(
                "No instrument or code aliases configured for TK semantic linking."
            )
            return result

        logger.info(
            "Processing %d TK documents for semantic linking (since=%s).",
            len(documents),
            describe_since(since),
        )

        for document in documents:
            text = self._extract_document_text(document)
            if not text:
                result.skipped += 1
                continue

            hits = detect_tk_citations(text, code_aliases, instrument_aliases)
            if not hits:
                continue

            for hit in hits:
                target_node = self._resolve_target_node(hit)
                if not target_node:
                    continue
                relation = _pick_tk_relation(document, hit.kind)
                created = self._create_semantic_edge(
                    from_node=document,
                    to_node=target_node,
                    relation=relation,
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

        logger.info("TK semantic article linker: %s.", result.summary())
        return result

    def _load_tk_documents(self) -> Iterable[Node]:
        for collection in (COLLECTION_PUBLICATIONS, COLLECTION_PROCEDURES):
            aql = (
                f"FOR doc IN {collection}\n"
                '    FILTER "TK" IN doc.labels\n'
                "    RETURN doc"
            )
            for doc in self.store.query(aql):
                yield Node.from_document(collection, doc)

    def _resolve_target_node(self, hit: CitationHit) -> Node | None:
        # Dutch article: BWB id + article number.
        if hit.kind == "article" and hit.bwb_id and hit.article_number:
            key = make_node_key(hit.bwb_id, hit.article_number)
            return self.store.get_node(COLLECTION_INSTRUMENT_ARTICLES, key)
        # EU / EVRM article: CELEX + article number (no BWB id).
        if hit.kind == "article" and hit.celex and hit.article_number:
            key = make_node_key(hit.celex, hit.article_number)
            return self.store.get_node(COLLECTION_INSTRUMENT_ARTICLES, key)
        # Whole-instrument reference (directive / regulation / verdrag).
        if hit.celex:
            key = make_node_key(hit.celex)
            return self.store.get_node(COLLECTION_INSTRUMENTS, key)
        if hit.bwb_id:
            key = make_node_key(hit.bwb_id)
            return self.store.get_node(COLLECTION_INSTRUMENTS, key)
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
        return "\n".join(fragments)

    def _collect_raw_text(
        self,
        value: Any,
        fragments: list[str],
        current_length: int,
    ) -> int:
        if current_length >= _MAX_TEXT_LENGTH:
            return current_length
        if isinstance(value, str):
            snippet = value.strip()
            if snippet:
                fragments.append(snippet)
                current_length += len(snippet)
        elif isinstance(value, dict):
            for child in value.values():
                current_length = self._collect_raw_text(
                    child, fragments, current_length
                )
                if current_length >= _MAX_TEXT_LENGTH:
                    break
        elif isinstance(value, list):
            for item in value:
                current_length = self._collect_raw_text(item, fragments, current_length)
                if current_length >= _MAX_TEXT_LENGTH:
                    break
        return current_length
