"""Semantic linkage pipeline for Rechtspraak judgments and BWB articles."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Iterable

from config.config import load_domain_config
from lawgraph.config.settings import RAW_KIND_RS_CONTENT, SOURCE_RECHTSPRAAK
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, make_node_key

logger = get_logger(__name__)

CodeMapping = dict[str, str]

SEMANTIC_EDGE_COLLECTION = "edges_semantic"
RELATION_MENTIONS_ARTICLE = "MENTIONS_ARTICLE"
SEMANTIC_SOURCE = "rechtspraak-article-linker"

_ALIAS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bart\.\s*(\d+[a-z]?)\s*(Sr|Sv|WVW)\b", re.IGNORECASE),
    re.compile(r"\bartikel\s+(\d+[a-z]?)\s*(Sr|Sv|WVW)\b", re.IGNORECASE),
)

_NUMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bartikel\s+(\d+[a-z]?)\b", re.IGNORECASE),
    re.compile(r"\bart\.\s*(\d+[a-z]?)\b", re.IGNORECASE),
)

_SNIPPET_WINDOW = 40


@dataclass
class ArticleHit:
    """Detected reference to a BWB article inside judgment text."""

    bwb_id: str
    article_number: str
    confidence: float
    raw_match: str | None = None
    snippet: str | None = None


def detect_article_references(
    text: str | None,
    mapping: CodeMapping,
) -> list[ArticleHit]:
    """Return article hints detected in the text together with confidence values."""
    if not text:
        return []

    normalized_mapping: CodeMapping = {
        alias.upper(): bwb_id
        for alias, bwb_id in mapping.items()
        if alias and bwb_id
    }

    hits: list[ArticleHit] = []
    seen_pairs: set[tuple[str, str]] = set()
    alias_spans: list[tuple[int, int]] = []

    def _snippet(match_span: tuple[int, int]) -> str:
        start, end = match_span
        begin = max(0, start - _SNIPPET_WINDOW)
        finish = min(len(text), end + _SNIPPET_WINDOW)
        return text[begin:finish].strip()

    for pattern in _ALIAS_PATTERNS:
        for match in pattern.finditer(text):
            article_number = match.group(1)
            alias = match.group(2)
            if not article_number or not alias:
                continue
            bwb_id = normalized_mapping.get(alias.upper(), "")
            if not bwb_id:
                continue
            pair = (bwb_id, article_number)
            if pair in seen_pairs:
                continue

            seen_pairs.add(pair)
            alias_spans.append(match.span())

            hits.append(
                ArticleHit(
                    bwb_id=bwb_id,
                    article_number=article_number,
                    confidence=0.95,
                    raw_match=match.group(0),
                    snippet=_snippet(match.span()),
                )
            )

    for pattern in _NUMBER_PATTERNS:
        for match in pattern.finditer(text):
            span = match.span()
            if any(not (span[1] <= span_start or span[0] >= span_end) for span_start, span_end in alias_spans):
                continue
            article_number = match.group(1)
            if not article_number:
                continue
            pair = ("", article_number)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            hits.append(
                ArticleHit(
                    bwb_id="",
                    article_number=article_number,
                    confidence=0.35,
                    raw_match=match.group(0),
                    snippet=_snippet(span),
                )
            )

    return hits


class RechtspraakArticleSemanticPipeline:
    """Link Rechtspraak judgments to BWB articles via semantic edges."""

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
        """Add MENTIONS_ARTICLE edges for newly referenced articles."""
        since_iso = self._since_iso(since)
        eclis = self._recent_rechtspraak_eclis(since_iso)
        judgments = list(self._load_judgments(eclis))

        mapping = self._load_code_aliases()
        if not mapping:
            logger.warning("No code_aliases configured; skipping semantic linkage.")
            return 0

        logger.info(
            "Processing %d Rechtspraak judgments (since=%s).",
            len(judgments),
            self._describe_since(since),
        )

        edges_created = 0
        for doc in judgments:
            judgment = Node.from_document("judgments", doc)
            text = self._extract_judgment_text(judgment)
            hits = detect_article_references(text, mapping)
            if not hits:
                continue

            for hit in hits:
                if not hit.bwb_id:
                    continue

                article = self._resolve_article(hit)
                if article is None:
                    continue

                if self._create_semantic_edge(judgment, article, hit):
                    edges_created += 1

        logger.info(
            "Rechtspraak article linker created %d semantic edges.", edges_created
        )
        return edges_created

    def _load_code_aliases(self) -> CodeMapping:
        config = self._load_domain_config()
        aliases = config.get("code_aliases", {})
        mapping: CodeMapping = {}
        if not isinstance(aliases, dict):
            return mapping
        for alias, value in aliases.items():
            if not alias or not value:
                continue
            key = str(alias).strip().upper()
            mapping[key] = str(value).strip()
        return mapping

    def _resolve_article(self, hit: ArticleHit) -> Node | None:
        article_key = make_node_key(hit.bwb_id, hit.article_number)
        return self.store.get_node("instrument_articles", article_key)

    def _create_semantic_edge(
        self,
        judgment: Node,
        article: Node,
        hit: ArticleHit,
    ) -> bool:
        if judgment.key is None or article.key is None:
            return False
        if judgment.id is None or article.id is None:
            return False

        edge_key = f"{make_node_key(judgment.key)}__{make_node_key(article.key)}__{RELATION_MENTIONS_ARTICLE}"
        meta = {}
        if hit.raw_match:
            meta["raw_match"] = hit.raw_match
        if hit.snippet:
            meta["snippet"] = hit.snippet

        edge_doc: dict[str, Any] = {
            "_key": edge_key,
            "_from": judgment.id,
            "_to": article.id,
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
        if eclis:
            bind_vars = {"eclis": list(eclis)}
            aql = """
            FOR doc IN judgments
                FILTER doc.props.meta.ecli IN @eclis
            RETURN doc
            """
        else:
            bind_vars = {}
            aql = "FOR doc IN judgments RETURN doc"

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

    @staticmethod
    def _since_iso(since: dt.datetime | None) -> str | None:
        if since is None:
            return None

        if since.tzinfo is None:
            since = since.replace(tzinfo=dt.timezone.utc)

        iso = since.astimezone(dt.timezone.utc).isoformat()
        if iso.endswith("+00:00"):
            return iso.replace("+00:00", "Z")
        return iso

    @staticmethod
    def _describe_since(since: dt.datetime | None) -> str:
        if since is None:
            return "full history"
        return RechtspraakArticleSemanticPipeline._since_iso(since) or "full history"
