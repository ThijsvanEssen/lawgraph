"""Semantic pipeline that links EU instruments to national and EU articles."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Iterable, Literal

from config.config import load_domain_config

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, make_node_key

logger = get_logger(__name__)

CodeMapping = dict[str, str]

SEMANTIC_EDGE_COLLECTION = "edges_semantic"
RELATION_MENTIONS_ARTICLE = "MENTIONS_ARTICLE"
SEMANTIC_SOURCE = "eu-article-linker"

_SNIPPET_WINDOW = 40
_MAX_TEXT_LENGTH = 40_000
ArticleKind = Literal["instrument", "article"]


@dataclass
class CitationHit:
    kind: ArticleKind
    celex: str | None = None
    bwb_id: str | None = None
    article_number: str | None = None
    confidence: float = 0.0
    raw_match: str | None = None
    snippet: str | None = None


_CELEX_PATTERN = re.compile(r"\bCELEX:([0-9A-Z()\\/\.\-]+)\b", re.IGNORECASE)
_RICHTLIJN_PATTERN = re.compile(r"\bRichtlijn\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE)
_VERORDENING_PATTERN = re.compile(r"\bVerordening\s+(\d{4})/(\d+)(?:/EU|/EG)?\b", re.IGNORECASE)
_ARTICLE_WITH_DIRECTIVE_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]?)\s+van\s+Richtlijn\s+(\d{4})/(\d+)(?:/EU|/EG)?\b",
    re.IGNORECASE,
)
_ARTICLE_WITH_REGULATION_PATTERN = re.compile(
    r"\bartikel\s+(\d+[a-z]?)\s+van\s+Verordening\s+(\d{4})/(\d+)(?:/EU|/EG)?\b",
    re.IGNORECASE,
)
_BWB_PATTERN = re.compile(r"\bbwb[rR]0\d{6}\b", re.IGNORECASE)
_ARTICLE_BWB_ALIAS_PATTERN = re.compile(r"\bartikel\s+(\d+[a-z]?)\s*(Sr|Sv|BW)\b", re.IGNORECASE)


def _make_snippet(text: str, span: tuple[int, int]) -> str:
    start, end = span
    begin = max(0, start - _SNIPPET_WINDOW)
    finish = min(len(text), end + _SNIPPET_WINDOW)
    return text[begin:finish].strip()


def _normalize_code_aliases(mapping: CodeMapping) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for alias, target in mapping.items():
        if not alias or not target:
            continue
        normalized[alias.strip().upper()] = target.strip().upper()
    return normalized


def _format_celex(kind: Literal["directive", "regulation"], year: str, number: str) -> str:
    letter = "L" if kind == "directive" else "R"
    padded = 0
    try:
        padded = int(number)
    except ValueError:
        pass
    return f"3{year}{letter}{padded:04d}"


def detect_eu_citations(text: str, code_aliases: CodeMapping) -> list[CitationHit]:
    if not text:
        return []

    normalized_codes = _normalize_code_aliases(code_aliases)
    hits: list[CitationHit] = []
    seen: set[tuple[ArticleKind, str | None, str | None, str | None]] = set()

    def _record(hit: CitationHit) -> None:
        key = (hit.kind, hit.celex, hit.bwb_id, hit.article_number)
        if key in seen:
            return
        seen.add(key)
        hits.append(hit)

    for match in _ARTICLE_WITH_DIRECTIVE_PATTERN.finditer(text):
        article_number = match.group(1)
        year = match.group(2)
        number_value = match.group(3)
        celex = _format_celex("directive", year, number_value)
        _record(
            CitationHit(
                kind="article",
                celex=celex,
                article_number=article_number.strip(),
                confidence=0.85,
                raw_match=match.group(0),
                snippet=_make_snippet(text, match.span()),
            )
        )

    for match in _ARTICLE_WITH_REGULATION_PATTERN.finditer(text):
        article_number = match.group(1)
        year = match.group(2)
        number_value = match.group(3)
        celex = _format_celex("regulation", year, number_value)
        _record(
            CitationHit(
                kind="article",
                celex=celex,
                article_number=article_number.strip(),
                confidence=0.85,
                raw_match=match.group(0),
                snippet=_make_snippet(text, match.span()),
            )
        )

    for match in _CELEX_PATTERN.finditer(text):
        celex_value = match.group(1)
        if not celex_value:
            continue
        _record(
            CitationHit(
                kind="instrument",
                celex=celex_value.upper(),
                confidence=0.9,
                raw_match=match.group(0),
                snippet=_make_snippet(text, match.span()),
            )
        )

    for match in _RICHTLIJN_PATTERN.finditer(text):
        celex_value = _format_celex("directive", match.group(1), match.group(2))
        _record(
            CitationHit(
                kind="instrument",
                celex=celex_value,
                confidence=0.7,
                raw_match=match.group(0),
                snippet=_make_snippet(text, match.span()),
            )
        )

    for match in _VERORDENING_PATTERN.finditer(text):
        celex_value = _format_celex("regulation", match.group(1), match.group(2))
        _record(
            CitationHit(
                kind="instrument",
                celex=celex_value,
                confidence=0.7,
                raw_match=match.group(0),
                snippet=_make_snippet(text, match.span()),
            )
        )

    for match in _ARTICLE_BWB_ALIAS_PATTERN.finditer(text):
        article_number = match.group(1)
        alias = match.group(2)
        if not alias:
            continue
        bwb_id = normalized_codes.get(alias.strip().upper())
        if not bwb_id or not article_number:
            continue
        _record(
            CitationHit(
                kind="article",
                bwb_id=bwb_id,
                article_number=article_number.strip(),
                confidence=0.95,
                raw_match=match.group(0),
                snippet=_make_snippet(text, match.span()),
            )
        )

    for match in _BWB_PATTERN.finditer(text):
        bwb_id = match.group(0)
        if not bwb_id:
            continue
        _record(
            CitationHit(
                kind="instrument",
                bwb_id=bwb_id.upper(),
                confidence=0.7,
                raw_match=match.group(0),
                snippet=_make_snippet(text, match.span()),
            )
        )

    return hits


class EUArticleSemanticPipeline:
    """Pipeline linking EU instruments to BWB/EU articles via semantic edges."""

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
        documents = list(self._load_eu_documents())
        if not documents:
            logger.debug("No EU instrument nodes found for semantic linking.")
            return 0

        code_aliases = self._load_code_aliases()
        logger.info(
            "Processing %d EU instruments for semantic article linking.",
            len(documents),
        )

        edges_created = 0
        for document in documents:
            text = self._extract_document_text(document)
            if not text:
                continue

            hits = detect_eu_citations(text, code_aliases)
            if not hits:
                continue

            for hit in hits:
                target = self._resolve_target(hit)
                if not target:
                    continue
                if self._create_semantic_edge(document, target, hit):
                    edges_created += 1

        logger.info("EU article linker created %d semantic edges.", edges_created)
        return edges_created

    def _load_eu_documents(self) -> Iterable[Node]:
        aql = """
        FOR doc IN instruments
            FILTER "EU" IN doc.labels
            RETURN doc
        """
        for doc in self.store.query(aql):
            yield Node.from_document("instruments", doc)

    def _extract_document_text(self, document: Node) -> str | None:
        fragments: list[str] = []
        for key in ("title", "official_title", "display_name"):
            candidate = document.props.get(key)
            text = _coerce_text(candidate)
            if text:
                fragments.append(text)

        raw_html = _coerce_text(document.props.get("raw_html"))
        if raw_html:
            fragments.append(_strip_html(raw_html))

        if not fragments:
            return None

        joined = "\n".join(fragments)
        if len(joined) > _MAX_TEXT_LENGTH:
            joined = joined[:_MAX_TEXT_LENGTH]
        return joined

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

    def _resolve_target(self, hit: CitationHit) -> Node | None:
        if hit.article_number and hit.bwb_id:
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
        if not document.key or not target.key or not document.id or not target.id:
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


def _strip_html(value: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", cleaned).strip()


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if candidate:
        return candidate
    return None
