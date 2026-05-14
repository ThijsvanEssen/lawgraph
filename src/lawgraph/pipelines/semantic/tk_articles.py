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
from lawgraph.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.utils.time import describe_since

from .base import InstrumentAliasMap, SemanticPipelineBase, _parse_instrument_aliases
from .citation_detect import (
    CitationHit,
    DutchCitationExtractor,
    _hit_reason,
    coerce_text,
    format_celex,
    make_snippet,
)

logger = get_logger(__name__)

SEMANTIC_SOURCE = "tk-article-linker"

_MAX_TEXT_LENGTH = 200_000

# Soort values that indicate an explanatory (MvT) document.
_MVT_SOORT_MARKER = "toelichting"

# ---------------------------------------------------------------------------
# Instrument-level patterns (not driven by registry — EU/BWBR literal forms)
# ---------------------------------------------------------------------------

_BWBR_PATTERN = re.compile(r"\b(BWBR0\d{6})\b", re.IGNORECASE)
_CELEX_DIRECT_PATTERN = re.compile(r"\bCELEX:([0-9A-Z()\\/.\-]+)\b", re.IGNORECASE)
_RICHTLIJN_PATTERN = re.compile(
    r"\bRichtlijn\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE
)
_VERORDENING_PATTERN = re.compile(
    r"\bVerordening\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE
)

# EU article-level patterns (year+number → CELEX, not registry-driven)
_ARTICLE_RICHTLIJN_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]*)\s+van\s+(?:de\s+)?[Rr]ichtlijn\s+(\d{4})/(\d+)(?:/EU|/EG)?\b",
    re.IGNORECASE,
)
_ARTICLE_VERORDENING_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]*)\s+van\s+(?:de\s+)?[Vv]erordening\s+(\d{4})/(\d+)(?:/EU|/EG)?\b",
    re.IGNORECASE,
)
_ARTICLE_BESLUIT_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]*)\s+van\s+(?:het\s+)?[Bb]esluit\s+(\d{4})/(\d+)(?:/EU|/EG|/GBVB)?\b",
    re.IGNORECASE,
)
_ARTICLE_KADERBESLUIT_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]*)\s+van\s+(?:het\s+)?[Kk]aderbesluit\s+(\d{4})/(\d+)(?:/JBZ|/EU)?\b",
    re.IGNORECASE,
)

_EU_ARTICLE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_ARTICLE_RICHTLIJN_PATTERN, "directive"),
    (_ARTICLE_VERORDENING_PATTERN, "regulation"),
    (_ARTICLE_BESLUIT_PATTERN, "decision"),
    (_ARTICLE_KADERBESLUIT_PATTERN, "framework_decision"),
)

_KIND_TO_LETTER = {
    "directive": "L",
    "regulation": "R",
    "decision": "C",
    "framework_decision": "D",
}


# ---------------------------------------------------------------------------
# Relation selector
# ---------------------------------------------------------------------------


def _pick_tk_relation(document: Node, hit_kind: str) -> str:
    if hit_kind == "instrument":
        return RELATION_MENTIONS_INSTRUMENT
    soort = str(document.props.get("soort") or "").lower()
    if _MVT_SOORT_MARKER in soort:
        return RELATION_EXPLAINS_ARTICLE
    return RELATION_MENTIONS_ARTICLE


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


def _collect_bwbr_hits(
    text: str,
    record: Callable[[CitationHit], None],
) -> None:
    for match in _BWBR_PATTERN.finditer(text):
        identifier = match.group(1).upper()
        record(
            CitationHit(
                kind="instrument",
                bwb_id=identifier,
                confidence=0.75,
                raw_match=match.group(0),
                snippet=make_snippet(text, match.span()),
            )
        )


def _collect_celex_hits(
    text: str,
    record: Callable[[CitationHit], None],
) -> None:
    for match in _CELEX_DIRECT_PATTERN.finditer(text):
        celex_value = match.group(1).upper()
        record(
            CitationHit(
                kind="instrument",
                celex=celex_value,
                confidence=0.9,
                raw_match=match.group(0),
                snippet=make_snippet(text, match.span()),
            )
        )


def _collect_eu_instrument_hits(
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
                CitationHit(
                    kind="instrument",
                    celex=celex_value,
                    confidence=0.65,
                    raw_match=match.group(0),
                    snippet=make_snippet(text, match.span()),
                )
            )


def _collect_eu_article_hits(
    text: str,
    record: Callable[[CitationHit], None],
) -> None:
    for pattern, kind in _EU_ARTICLE_PATTERNS:
        for match in pattern.finditer(text):
            article_number = match.group(1)
            year = match.group(2)
            number_value = match.group(3)
            letter = _KIND_TO_LETTER.get(kind, "L")
            try:
                padded = int(number_value)
            except ValueError:
                padded = 0
            celex = f"3{year}{letter}{padded:04d}"
            record(
                CitationHit(
                    kind="article",
                    celex=celex,
                    article_number=article_number,
                    confidence=0.88,
                    raw_match=match.group(0),
                    snippet=make_snippet(text, match.span()),
                )
            )


# ---------------------------------------------------------------------------
# Backward-compat public function
# ---------------------------------------------------------------------------


def detect_tk_citations(
    text: str,
    code_aliases: dict[str, str],
    instrument_aliases: InstrumentAliasMap | dict[str, Any],
) -> list[CitationHit]:
    """Detect article and instrument citations in TK publication text.

    Thin wrapper around ``DutchCitationExtractor`` kept for backward compat.
    New code should instantiate ``DutchCitationExtractor`` directly.
    """
    if not text:
        return []

    parsed_aliases: InstrumentAliasMap = _parse_instrument_aliases(instrument_aliases)

    # Build name_aliases: {full name → first non-None id (bwb or celex)}
    name_aliases: dict[str, str] = {}
    for name, (bwb_id, celex) in parsed_aliases.items():
        law_id = bwb_id or celex
        if law_id:
            name_aliases[name] = law_id

    extractor = DutchCitationExtractor(
        code_aliases=code_aliases,
        name_aliases=name_aliases,
    )
    hits = extractor.extract(text)

    seen: set[tuple[str | None, str | None]] = {
        (h.bwb_id, h.celex) for h in hits if h.kind == "instrument"
    }

    def _record(hit: CitationHit) -> None:
        key = (hit.bwb_id, hit.celex)
        if key in seen:
            return
        seen.add(key)
        hits.append(hit)

    named_act_patterns = _build_named_act_patterns(parsed_aliases)
    _collect_named_act_hits(text, named_act_patterns, _record)
    _collect_bwbr_hits(text, _record)
    _collect_celex_hits(text, _record)
    _collect_eu_instrument_hits(text, _record)
    _collect_eu_article_hits(text, _record)

    return hits


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class TKArticleSemanticPipeline(SemanticPipelineBase):
    """Pipeline connecting TK publications and procedures to legal articles."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        from lawgraph.utils.time import iso_timestamp

        since_iso = iso_timestamp(since)
        documents = list(self._load_tk_documents(since_iso=since_iso))
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

        # Build name_aliases for DutchCitationExtractor (article-level "van de" form)
        name_aliases: dict[str, str] = {}
        for name, (bwb_id, celex) in instrument_aliases.items():
            law_id = bwb_id or celex
            if law_id:
                name_aliases[name] = law_id

        extractor = DutchCitationExtractor(
            code_aliases=code_aliases,
            name_aliases=name_aliases,
        )
        named_act_patterns = _build_named_act_patterns(instrument_aliases)

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

            hits = self._collect_all_hits(text, extractor, named_act_patterns)
            if not hits:
                continue

            for hit in hits:
                target_node = self._resolve_target_node(hit)
                if not target_node:
                    continue
                relation = _pick_tk_relation(document, hit.kind)
                meta = {
                    k: v
                    for k, v in {
                        "raw_match": hit.raw_match,
                        "snippet": hit.snippet,
                        "reason": _hit_reason(hit),
                        "qualifier": hit.qualifier,
                    }.items()
                    if v
                }
                created = self._create_semantic_edge(
                    from_node=document,
                    to_node=target_node,
                    relation=relation,
                    source=SEMANTIC_SOURCE,
                    confidence=hit.confidence,
                    meta=meta,
                    result=result,
                )
                if created:
                    result.created += 1
                else:
                    result.updated += 1

        logger.info("TK semantic article linker: %s.", result.summary())
        return result

    def _collect_all_hits(
        self,
        text: str,
        extractor: DutchCitationExtractor,
        named_act_patterns: list[tuple[str, re.Pattern[str], str | None, str | None]],
    ) -> list[CitationHit]:
        hits = extractor.extract(text)

        seen_instruments: set[tuple[str | None, str | None]] = {
            (h.bwb_id, h.celex) for h in hits if h.kind == "instrument"
        }

        def _record(hit: CitationHit) -> None:
            key = (hit.bwb_id, hit.celex)
            if key in seen_instruments:
                return
            seen_instruments.add(key)
            hits.append(hit)

        _collect_named_act_hits(text, named_act_patterns, _record)
        _collect_bwbr_hits(text, _record)
        _collect_celex_hits(text, _record)
        _collect_eu_instrument_hits(text, _record)
        _collect_eu_article_hits(text, _record)

        return hits

    def _load_tk_documents(self, *, since_iso: str | None = None) -> Iterable[Node]:
        if since_iso is not None:
            from lawgraph.config.settings import (
                RAW_KIND_TK_DOCUMENTVERSIE,
                RAW_KIND_TK_ZAAK,
                SOURCE_TK,
            )

            recent_ids: set[str] = set()
            for kind in (RAW_KIND_TK_DOCUMENTVERSIE, RAW_KIND_TK_ZAAK):
                aql = """
                FOR raw IN raw_sources
                    FILTER raw.source == @source AND raw.kind == @kind
                    FILTER raw.fetched_at >= @since
                    FILTER raw.external_id != null
                RETURN raw.external_id
                """
                for row in self.store.query(
                    aql,
                    bind_vars={"source": SOURCE_TK, "kind": kind, "since": since_iso},
                ):
                    if isinstance(row, str):
                        recent_ids.add(row)
                    elif isinstance(row, dict):
                        eid = row.get("external_id")
                        if eid:
                            recent_ids.add(str(eid))
            if not recent_ids:
                return
            id_list = list(recent_ids)
            for collection in (COLLECTION_PUBLICATIONS, COLLECTION_PROCEDURES):
                aql = (
                    f"FOR doc IN {collection}\n"
                    '    FILTER "TK" IN doc.labels\n'
                    "    FILTER doc.props.external_id IN @ids\n"
                    "    RETURN doc"
                )
                for doc in self.store.query(aql, bind_vars={"ids": id_list}):
                    yield Node.from_document(collection, doc)
        else:
            for collection in (COLLECTION_PUBLICATIONS, COLLECTION_PROCEDURES):
                aql = (
                    f"FOR doc IN {collection}\n"
                    '    FILTER "TK" IN doc.labels\n'
                    "    RETURN doc"
                )
                for doc in self.store.query(aql):
                    yield Node.from_document(collection, doc)

    def _resolve_target_node(self, hit: CitationHit) -> Node | None:
        if hit.kind == "article" and hit.bwb_id and hit.article_number:
            key = make_node_key(hit.bwb_id, hit.article_number)
            node = self.store.get_node(COLLECTION_INSTRUMENT_ARTICLES, key)
            if node is None and hit.confidence >= 0.85:
                stub = Node(
                    collection=COLLECTION_INSTRUMENT_ARTICLES,
                    key=key,
                    type=NodeType.ARTICLE,
                    props={
                        "bwb_id": hit.bwb_id,
                        "article_number": hit.article_number,
                        "stub": True,
                        "display_name": f"Artikel {hit.article_number} ({hit.bwb_id})",
                    },
                )
                node = self.store.insert_or_update(stub)
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
            node = self.store.get_node(COLLECTION_INSTRUMENT_ARTICLES, key)
            if node is None and hit.confidence >= 0.85:
                stub = Node(
                    collection=COLLECTION_INSTRUMENT_ARTICLES,
                    key=key,
                    type=NodeType.ARTICLE,
                    props={
                        "celex": hit.celex,
                        "article_number": hit.article_number,
                        "stub": True,
                        "display_name": f"Artikel {hit.article_number} ({hit.celex})",
                    },
                )
                node = self.store.insert_or_update(stub)
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
            node = self.store.get_node(COLLECTION_INSTRUMENTS, key)
            if node is None:
                logger.debug("TK semantic: no instrument node for CELEX %s", hit.celex)
            return node

        if hit.bwb_id:
            key = make_node_key(hit.bwb_id)
            node = self.store.get_node(COLLECTION_INSTRUMENTS, key)
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
        if len(text) >= _MAX_TEXT_LENGTH:
            logger.debug(
                "TK semantic: document text truncated at %d chars (node %s).",
                _MAX_TEXT_LENGTH,
                document.key if hasattr(document, "key") else "unknown",
            )
        return text

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
