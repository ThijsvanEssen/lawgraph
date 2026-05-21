"""Semantic pipeline that links EU instruments to national and EU articles."""

from __future__ import annotations

import datetime as dt
import re
from typing import Callable, Iterable, Literal

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_MENTIONS_ARTICLE,
    RELATION_MENTIONS_INSTRUMENT,
    SOURCE_EURLEX,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import describe_since, iso_timestamp

from .base import CodeMapping, SemanticPipelineBase
from .citation_detect import (
    ArticleKind,
    CitationHit,
    coerce_text,
    format_celex,
    hit_reason,
    make_snippet,
    normalize_code_aliases,
)

logger = get_logger(__name__)

SEMANTIC_SOURCE = "eu-article-linker"

_MAX_TEXT_LENGTH = 200_000

_CONFIDENCE_ARTICLE_EXACT = (
    0.85  # article match via directive/regulation + year + number
)
_CONFIDENCE_CELEX_EXACT = 0.90  # CELEX ID literal in text
_CONFIDENCE_DIRECTIVE_YEAR = 0.70  # directive/regulation matched via year + number only
_CONFIDENCE_BWB_ALIAS = 0.95  # "artikel X Sr/Sv/BW" via known short alias
_CONFIDENCE_BWB_ID = 0.70  # bare BWBR number in text

_CELEX_PATTERN = re.compile(r"\bCELEX:([0-9A-Z()\\/\.\-]+)\b", re.IGNORECASE)
_RICHTLIJN_PATTERN = re.compile(
    r"\bRichtlijn\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE
)
_VERORDENING_PATTERN = re.compile(
    r"\bVerordening\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE
)
_ARTICLE_WITH_DIRECTIVE_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]?)\s+van\s+Richtlijn\s+(\d{4})/(\d+)(?:/EU|/EG)?\b",
    re.IGNORECASE,
)
_ARTICLE_WITH_REGULATION_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]?)\s+van\s+Verordening\s+(\d{4})/(\d+)(?:/EU|/EG)?\b",
    re.IGNORECASE,
)
_BWB_PATTERN = re.compile(r"\bbwb[rR]0\d{6}\b", re.IGNORECASE)
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

    _collect_article_matches(
        text,
        _ARTICLE_WITH_DIRECTIVE_PATTERN,
        "directive",
        _CONFIDENCE_ARTICLE_EXACT,
        _record,
    )
    _collect_article_matches(
        text,
        _ARTICLE_WITH_REGULATION_PATTERN,
        "regulation",
        _CONFIDENCE_ARTICLE_EXACT,
        _record,
    )
    _collect_celex_hits(
        text, _CELEX_PATTERN, "instrument", _CONFIDENCE_CELEX_EXACT, _record
    )
    _collect_celex_hits(
        text,
        _RICHTLIJN_PATTERN,
        "instrument",
        _CONFIDENCE_DIRECTIVE_YEAR,
        _record,
        directive_kind="directive",
    )
    _collect_celex_hits(
        text,
        _VERORDENING_PATTERN,
        "instrument",
        _CONFIDENCE_DIRECTIVE_YEAR,
        _record,
        directive_kind="regulation",
    )
    _collect_bwb_alias_hits(text, normalized_codes, _record)
    _collect_bwb_hits(text, _record)

    return hits


def _collect_article_matches(
    text: str,
    pattern: re.Pattern[str],
    kind_label: Literal["directive", "regulation"],
    confidence: float,
    record: Callable[[CitationHit], None],
) -> None:
    for match in pattern.finditer(text):
        article_number = match.group(1)
        year = match.group(2)
        number_value = match.group(3)
        celex = format_celex(kind_label, year, number_value)
        record(
            CitationHit(
                kind="article",
                celex=celex,
                article_number=article_number.strip(),
                confidence=confidence,
                raw_match=match.group(0),
                snippet=make_snippet(text, match.span()),
            )
        )


def _collect_celex_hits(
    text: str,
    pattern: re.Pattern[str],
    kind: ArticleKind,
    confidence: float,
    record: Callable[[CitationHit], None],
    *,
    directive_kind: Literal["directive", "regulation"] | None = None,
) -> None:
    for match in pattern.finditer(text):
        if directive_kind:
            celex_value = format_celex(directive_kind, match.group(1), match.group(2))
        else:
            celex_value = match.group(1)
        if not celex_value:
            continue
        record(
            CitationHit(
                kind=kind,
                celex=celex_value.upper(),
                confidence=confidence,
                raw_match=match.group(0),
                snippet=make_snippet(text, match.span()),
            )
        )


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


def _collect_bwb_hits(
    text: str,
    record: Callable[[CitationHit], None],
) -> None:
    for match in _BWB_PATTERN.finditer(text):
        bwb_id = match.group(0)
        if not bwb_id:
            continue
        record(
            CitationHit(
                kind="instrument",
                bwb_id=bwb_id.upper(),
                confidence=_CONFIDENCE_BWB_ID,
                raw_match=match.group(0),
                snippet=make_snippet(text, match.span()),
            )
        )


class EUArticleSemanticPipeline(SemanticPipelineBase):
    """Pipeline linking EU instruments to BWB/EU articles via semantic edges."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        """Inspect EU instruments for referenced articles and persist semantic edges."""
        result = PipelineResult()
        since_iso = iso_timestamp(since)
        documents = list(self._load_eu_documents(since_iso=since_iso))
        if not documents:
            logger.debug("No EU instrument nodes found for semantic linking.")
            return result

        code_aliases = self._load_code_aliases()
        logger.info(
            "Processing %d EU instruments for semantic article linking (since=%s).",
            len(documents),
            describe_since(since),
        )

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
                relation = (
                    RELATION_MENTIONS_ARTICLE
                    if hit.kind == "article"
                    else RELATION_MENTIONS_INSTRUMENT
                )
                created = self._create_semantic_edge(
                    from_node=document,
                    to_node=target,
                    relation=relation,
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
                    result=result,
                )
                if created:
                    result.created += 1
                else:
                    result.updated += 1

        logger.info("EU article linker: %s.", result.summary())
        return result

    def _load_eu_documents(self, *, since_iso: str | None = None) -> Iterable[Node]:
        # Scan EU instrument *articles* — their props.text contains the actual
        # directive body, which is where cross-references to other articles live.
        if since_iso is not None:
            recent_celex: set[str] = set()
            aql = """
            FOR raw IN raw_sources
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
            FOR doc IN {COLLECTION_INSTRUMENT_ARTICLES}
                FILTER doc.props.celex IN @celex_list
                RETURN doc
            """
            for doc in self.store.query(aql, bind_vars={"celex_list": celex_list}):
                yield Node.from_document(COLLECTION_INSTRUMENT_ARTICLES, doc)
        else:
            aql = f"""
            FOR doc IN {COLLECTION_INSTRUMENT_ARTICLES}
                FILTER doc.props.celex != null
                RETURN doc
            """
            for doc in self.store.query(aql):
                yield Node.from_document(COLLECTION_INSTRUMENT_ARTICLES, doc)

    def _extract_document_text(self, document: Node) -> str | None:
        # EU instrument_articles store their text directly in props.text.
        text = coerce_text(document.props.get("text"))
        if text:
            return text[:_MAX_TEXT_LENGTH]
        # Fallback: title only (gives minimal signal but avoids skipping entirely)
        return coerce_text(document.props.get("display_name"))

    def _resolve_article_node(
        self, hit: CitationHit, identifier: str, id_prop: str
    ) -> Node | None:
        key = make_node_key(identifier, hit.article_number)
        node = self.store.get_node(COLLECTION_INSTRUMENT_ARTICLES, key)
        if node is None and hit.confidence >= 0.85:
            stub = Node(
                collection=COLLECTION_INSTRUMENT_ARTICLES,
                key=key,
                type=NodeType.ARTICLE,
                props={
                    id_prop: identifier,
                    "article_number": hit.article_number,
                    "stub": True,
                    "display_name": f"Artikel {hit.article_number} ({identifier})",
                },
            )
            node = self.store.insert_or_update(stub)
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
            node = self.store.get_node(COLLECTION_INSTRUMENTS, key)
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
            node = self.store.get_node(COLLECTION_INSTRUMENTS, key)
            if node is None:
                logger.debug(
                    "EU semantic: no node found for %s %s (confidence=%.2f)",
                    hit.kind,
                    hit.bwb_id or hit.celex,
                    hit.confidence,
                )
            return node
        return None
