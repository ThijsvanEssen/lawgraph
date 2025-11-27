"""Semantic linkage pipeline that connects TK publications to legal articles."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal

from config.config import load_domain_config

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_PROCEDURES,
    COLLECTION_PUBLICATIONS,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, make_node_key

logger = get_logger(__name__)

CodeMapping = dict[str, str]

SEMANTIC_EDGE_COLLECTION = "edges_semantic"
RELATION_MENTIONS_ARTICLE = "MENTIONS_ARTICLE"
SEMANTIC_SOURCE = "tk-article-linker"

_SNIPPET_WINDOW = 40
_MAX_TEXT_LENGTH = 40_000
ArticleKind = Literal["article", "instrument"]


@dataclass
class CitationHit:
    kind: ArticleKind
    bwb_id: str | None = None
    article_number: str | None = None
    celex: str | None = None
    confidence: float = 0.0
    raw_match: str | None = None
    snippet: str | None = None


_BWBR_PATTERN = re.compile(r"\b(BWBR0\d{6})\b", re.IGNORECASE)
_ARTICLE_ALIAS_PATTERNS = (
    re.compile(r"\bartikel\s+(\d+[a-z]?)\s*(Sr|Sv|BW|EVRM)\b", re.IGNORECASE),
    re.compile(r"\bart\.\s*(\d+[a-z]?)\s*(Sr|Sv|BW)\b", re.IGNORECASE),
)
_CELEX_DIRECT_PATTERN = re.compile(r"\bCELEX:([0-9A-Z()\\/\.\-]+)\b", re.IGNORECASE)
_RICHTLIJN_PATTERN = re.compile(r"\bRichtlijn\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE)
_VERORDENING_PATTERN = re.compile(r"\bVerordening\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE)


def _make_snippet(text: str, span: tuple[int, int]) -> str:
    start, end = span
    begin = max(0, start - _SNIPPET_WINDOW)
    finish = min(len(text), end + _SNIPPET_WINDOW)
    return text[begin:finish].strip()


def _normalize_code_aliases(mapping: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for alias, target in mapping.items():
        if not alias or not target:
            continue
        normalized[alias.strip().upper()] = target.strip().upper()
    return normalized


def _parse_instrument_aliases(raw_aliases: dict[str, Any]) -> dict[str, tuple[str | None, str | None]]:
    aliases: dict[str, tuple[str | None, str | None]] = {}
    for alias, value in raw_aliases.items():
        label = str(alias or "").strip()
        if not label:
            continue
        if isinstance(value, dict):
            bwb_id = value.get("bwb_id")
            celex = value.get("celex")
            aliases[label] = (
                str(bwb_id).strip().upper() if bwb_id else None,
                str(celex).strip().upper() if celex else None,
            )
            continue
        scalar = str(value or "").strip()
        if not scalar:
            continue
        if scalar.upper().startswith("BWBR"):
            aliases[label] = (scalar.upper(), None)
        else:
            aliases[label] = (None, scalar.upper())
    return aliases


def _build_named_act_patterns(
    aliases: dict[str, tuple[str | None, str | None]]
) -> list[tuple[str, re.Pattern[str], str | None, str | None]]:
    patterns: list[tuple[str, re.Pattern[str], str | None, str | None]] = []
    for label, (bwb_id, celex) in aliases.items():
        if not (bwb_id or celex):
            continue
        escaped = re.escape(label)
        pattern = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
        patterns.append((label, pattern, bwb_id, celex))
    return patterns


def _format_celex(kind: Literal["directive", "regulation"], year: str, number: str) -> str:
    letter = "L" if kind == "directive" else "R"
    padded = 0
    try:
        padded = int(number)
    except ValueError:
        pass
    return f"3{year}{letter}{padded:04d}"


def detect_tk_citations(
    text: str,
    code_aliases: dict[str, str],
    instrument_aliases: dict[str, tuple[str | None, str | None]],
) -> list[CitationHit]:
    if not text:
        return []

    normalized_codes = _normalize_code_aliases(code_aliases)
    named_act_patterns = _build_named_act_patterns(instrument_aliases)

    hits: list[CitationHit] = []
    seen: set[tuple[ArticleKind, str | None, str | None, str | None]] = set()

    def _record(hit: CitationHit) -> None:
        key = (hit.kind, hit.bwb_id, hit.article_number, hit.celex)
        if key in seen:
            return
        seen.add(key)
        hits.append(hit)

    for _, pattern, bwb_id, celex in named_act_patterns:
        for match in pattern.finditer(text):
            hit = CitationHit(
                kind="instrument",
                bwb_id=bwb_id,
                celex=celex,
                confidence=0.6,
                raw_match=match.group(0),
                snippet=_make_snippet(text, match.span()),
            )
            _record(hit)

    for match in _BWBR_PATTERN.finditer(text):
        identifier = match.group(1)
        if not identifier:
            continue
        hit = CitationHit(
            kind="instrument",
            bwb_id=identifier.upper(),
            confidence=0.75,
            raw_match=match.group(0),
            snippet=_make_snippet(text, match.span()),
        )
        _record(hit)

    for pattern in _ARTICLE_ALIAS_PATTERNS:
        for match in pattern.finditer(text):
            article_number = match.group(1)
            alias = match.group(2)
            if not alias or not article_number:
                continue
            bwb_id = normalized_codes.get(alias.strip().upper())
            if not bwb_id:
                continue
            hit = CitationHit(
                kind="article",
                bwb_id=bwb_id,
                article_number=article_number.strip(),
                confidence=0.95,
                raw_match=match.group(0),
                snippet=_make_snippet(text, match.span()),
            )
            _record(hit)

    for match in _CELEX_DIRECT_PATTERN.finditer(text):
        celex_value = match.group(1)
        if not celex_value:
            continue
        hit = CitationHit(
            kind="instrument",
            celex=celex_value.upper(),
            confidence=0.9,
            raw_match=match.group(0),
            snippet=_make_snippet(text, match.span()),
        )
        _record(hit)

    for match in _RICHTLIJN_PATTERN.finditer(text):
        celex_value = _format_celex("directive", match.group(1), match.group(2))
        hit = CitationHit(
            kind="instrument",
            celex=celex_value,
            confidence=0.65,
            raw_match=match.group(0),
            snippet=_make_snippet(text, match.span()),
        )
        _record(hit)

    for match in _VERORDENING_PATTERN.finditer(text):
        celex_value = _format_celex("regulation", match.group(1), match.group(2))
        hit = CitationHit(
            kind="instrument",
            celex=celex_value,
            confidence=0.65,
            raw_match=match.group(0),
            snippet=_make_snippet(text, match.span()),
        )
        _record(hit)

    return hits


class TKArticleSemanticPipeline:
    """Pipeline connecting TK publications and procedures to legal articles."""

    def __init__(
        self,
        *,
        store: ArangoStore,
        domain_profile: str | None = None,
        domain_config: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self._domain_profile_name = domain_profile
        self._domain_config = domain_config

    def run(self, *, since: dt.datetime | None = None) -> int:
        documents = list(self._load_tk_documents())
        if not documents:
            logger.debug("No TK documents found for semantic linking.")
            return 0

        code_aliases = self._load_code_aliases()
        instrument_aliases = self._load_instrument_aliases()
        if not code_aliases and not instrument_aliases:
            logger.warning("No instrument or code aliases configured for TK semantic linking.")
            return 0

        logger.info(
            "Processing %d TK documents for semantic linking.",
            len(documents),
        )

        edges_created = 0
        for document in documents:
            text = self._extract_document_text(document)
            if not text:
                continue

            hits = detect_tk_citations(text, code_aliases, instrument_aliases)
            if not hits:
                continue

            for hit in hits:
                target_node = self._resolve_target_node(hit)
                if not target_node:
                    continue
                if self._create_semantic_edge(document, target_node, hit):
                    edges_created += 1

        logger.info("TK semantic article linker created %d edges.", edges_created)
        return edges_created

    def _load_tk_documents(self) -> Iterable[Node]:
        for collection in (COLLECTION_PUBLICATIONS, COLLECTION_PROCEDURES):
            aql = (
                f"FOR doc IN {collection}\n"
                '    FILTER "TK" IN doc.labels\n'
                "    RETURN doc"
            )
            for doc in self.store.query(aql):
                yield Node.from_document(collection, doc)

    def _load_domain_config(self) -> dict[str, Any]:
        if self._domain_config is not None:
            return self._domain_config
        if not self._domain_profile_name:
            self._domain_config = {}
            return self._domain_config
        try:
            self._domain_config = load_domain_config(self._domain_profile_name)
        except FileNotFoundError as exc:
            logger.warning(
                "Unable to load profile %s: %s",
                self._domain_profile_name,
                exc,
            )
            self._domain_config = {}
        return self._domain_config

    def _load_code_aliases(self) -> CodeMapping:
        config = self._load_domain_config()
        aliases = config.get("code_aliases", {})
        if not isinstance(aliases, dict):
            return {}
        return {str(k).strip(): str(v).strip() for k, v in aliases.items() if k and v}

    def _load_instrument_aliases(self) -> dict[str, tuple[str | None, str | None]]:
        config = self._load_domain_config()
        raw_aliases = config.get("instrument_aliases", {})
        if not isinstance(raw_aliases, dict):
            return {}
        return _parse_instrument_aliases(raw_aliases)

    def _resolve_target_node(self, hit: CitationHit) -> Node | None:
        if hit.kind == "article" and hit.bwb_id and hit.article_number:
            key = make_node_key(hit.bwb_id, hit.article_number)
            return self.store.get_node(COLLECTION_INSTRUMENT_ARTICLES, key)
        if hit.celex:
            key = make_node_key(hit.celex)
            return self.store.get_node(COLLECTION_INSTRUMENTS, key)
        if hit.bwb_id:
            key = make_node_key(hit.bwb_id)
            return self.store.get_node(COLLECTION_INSTRUMENTS, key)
        return None

    def _create_semantic_edge(
        self,
        document: Node,
        target: Node,
        hit: CitationHit,
    ) -> bool:
        if not document.key or not document.id or not target.key or not target.id:
            return False

        edge_key = (
            f"{make_node_key(document.key)}__{make_node_key(target.key)}__{RELATION_MENTIONS_ARTICLE}"
        )
        meta: dict[str, Any] = {}
        if hit.raw_match:
            meta["raw_match"] = hit.raw_match
        if hit.snippet:
            meta["snippet"] = hit.snippet

        edge_doc = {
            "_key": edge_key,
            "_from": document.id,
            "_to": target.id,
            "relation": RELATION_MENTIONS_ARTICLE,
            "confidence": hit.confidence,
            "source": SEMANTIC_SOURCE,
            "strict": False,
            "meta": meta,
        }
        _, created = self.store.insert_or_update_edge(
            collection_name=SEMANTIC_EDGE_COLLECTION,
            doc=edge_doc,
        )
        return created

    def _extract_document_text(self, document: Node) -> str | None:
        fragments: list[str] = []
        total_length = 0
        for key in ("title", "summary", "body", "text"):
            candidate = document.props.get(key)
            text_value = _coerce_text(candidate)
            if not text_value:
                continue
            fragments.append(text_value)
            total_length += len(text_value)

        total_length = self._collect_raw_text(document.props.get("raw"), fragments, total_length)
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
                current_length = self._collect_raw_text(child, fragments, current_length)
                if current_length >= _MAX_TEXT_LENGTH:
                    break
        elif isinstance(value, list):
            for item in value:
                current_length = self._collect_raw_text(item, fragments, current_length)
                if current_length >= _MAX_TEXT_LENGTH:
                    break
        return current_length


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if candidate:
        return candidate
    return None
