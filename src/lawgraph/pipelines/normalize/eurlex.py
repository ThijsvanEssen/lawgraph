from __future__ import annotations

import datetime as dt
import os
import re
from html.parser import HTMLParser
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_SOURCE_KINDS,
    RELATION_PART_OF_INSTRUMENT,
    SOURCE_EURLEX,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)

_NODE_BATCH_SIZE = 200

# Matches "Artikel 1", "Artikel 12a", "Article 1" (English fallback)
_ARTICLE_HEADER_RE = re.compile(
    r"(?:^|\n)\s*(?:Artikel|Article)\s+(\d+[a-z]*)\b",
    re.IGNORECASE,
)


class _TextExtractor(HTMLParser):
    """Strip HTML tags and collect visible text, preserving block-level whitespace."""

    _BLOCK_TAGS = {
        "p",
        "div",
        "article",
        "section",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "tr",
        "td",
        "th",
        "br",
        "hr",
    }
    _SKIP_TAGS = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif (
            tag in self._BLOCK_TAGS
            and self._parts
            and not self._parts[-1].endswith("\n")
        ):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


# Read at module import time; changing the env var requires a process restart.
try:
    _EU_MAX_ARTICLE_NUMBER: int = int(os.getenv("EURLEX_MAX_ARTICLE_NUMBER", "200"))
except ValueError as _exc:
    raise ValueError(
        f"EURLEX_MAX_ARTICLE_NUMBER must be an integer, got: "
        f"{os.getenv('EURLEX_MAX_ARTICLE_NUMBER')!r}"
    ) from _exc


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = parser.get_text()
    # Replace non-breaking spaces with regular spaces
    text = text.replace("\xa0", " ")
    # Collapse runs of blank lines to a single newline
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of spaces/tabs within lines (but keep newlines)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


_DOC_TI_RE = re.compile(
    r'<p[^>]+class=["\'][^"\']*doc-ti[^"\']*["\'][^>]*>(.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_CELEX_CITATION_RE = re.compile(r"^3(\d{4})([LRDF])(\d+)$", re.ASCII)

_CELEX_TYPE_LABELS: dict[str, str] = {
    "L": "Richtlijn",
    "R": "Verordening",
    "D": "Besluit",
    "F": "Kaderbesluit",
}


def _extract_eu_title_from_html(html: str) -> str | None:
    """Return the document title from CELLAR HTML, or None if not found."""
    m = _DOC_TI_RE.search(html)
    if m:
        text = _HTML_TAG_RE.sub("", m.group(1)).replace("\xa0", " ").strip()
        if len(text) > 5:
            return " ".join(text.split())
    return None


def _derive_eu_citation_title(celex: str) -> str | None:
    """Derive a short citation title from a CELEX number, e.g. 'Richtlijn 2010/64/EU'."""
    m = _CELEX_CITATION_RE.match(celex.upper())
    if not m:
        return None
    year, doc_type, number = m.group(1), m.group(2), m.group(3).lstrip("0") or "0"
    label = _CELEX_TYPE_LABELS.get(doc_type)
    if not label:
        return None
    suffix = "JBZ" if doc_type == "F" else "EU"
    return f"{label} {year}/{number}/{suffix}"


def _extract_eu_articles(html: str, celex: str) -> list[dict[str, str]]:
    """Parse EUR-Lex HTML and return list of {article_number, text} dicts."""
    text = _html_to_text(html)
    matches = list(_ARTICLE_HEADER_RE.finditer(text))
    if not matches:
        return []

    articles: list[dict[str, str]] = []
    for i, match in enumerate(matches):
        article_number = match.group(1)
        # Skip unreasonably large article numbers (treaty cross-references in preamble)
        try:
            int_val = int(re.sub(r"[a-z]+$", "", article_number))
            if int_val > _EU_MAX_ARTICLE_NUMBER:
                continue
        except ValueError:
            pass

        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        # Skip preamble fragments — cross-references start with ", lid" or similar punctuation
        if not body or len(body) < 10 or body.startswith(","):
            logger.debug(
                "Skipping article %s (body too short or punctuation-only): %r",
                article_number,
                body[:40],
            )
            continue
        articles.append({"article_number": article_number, "text": body})

    return articles


class EUNormalizePipeline(NormalizePipeline):
    """Normalization pipeline that turns EUR-Lex raw dumps into instrument + article nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Load EUR-Lex CELEX html dumps from raw_sources."""
        kinds = list(RAW_SOURCE_KINDS[SOURCE_EURLEX])
        records = self._query_raw_sources(
            source=SOURCE_EURLEX,
            kinds=kinds,
            since=since,
        )

        logger.info(
            "Loaded %d EUR-Lex html records from raw_sources.",
            len(records),
        )

        return records

    def normalize_nodes(
        self,
        raw: list[dict[str, Any]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Normalize EUR-Lex raw HTML into instrument and article nodes."""
        instruments_by_celex: dict[str, Node] = {}
        articles_by_celex: dict[str, list[Node]] = {}
        celex_records = raw

        for raw_entry in celex_records:
            payload_text = self._payload_text(raw_entry)
            meta = self._meta(raw_entry)
            celex = meta.get("celex")
            lang = meta.get("lang")

            if not celex:
                logger.warning(
                    "Skipping EUR-Lex record without CELEX (_key=%s).",
                    raw_entry.get("_key"),
                )
                continue

            # --- instrument node ---
            props: dict[str, Any] = {
                "source": SOURCE_EURLEX,
                "celex": celex,
                "jurisdiction": "eu",
            }
            if lang:
                props["lang"] = lang
            if meta:
                props["meta"] = meta

            # Extract title from CELLAR HTML; derive short citation title from CELEX.
            if payload_text:
                html_title = _extract_eu_title_from_html(payload_text)
                if html_title:
                    props["title"] = html_title
            citation_title = _derive_eu_citation_title(celex)
            if citation_title:
                props["citation_title"] = citation_title

            labels = ["EU"]

            props["display_name"] = (
                props.get("title") or citation_title or f"EU {celex}"
            )
            instrument_key = make_node_key(celex)

            instrument_node = Node(
                collection=COLLECTION_INSTRUMENTS,
                type=NodeType.INSTRUMENT,
                key=instrument_key,
                labels=labels,
                props=props,
            )
            inserted_instrument = self.store.insert_or_update(instrument_node)
            instruments_by_celex[celex] = inserted_instrument

            # --- article nodes ---
            if not payload_text:
                continue

            raw_articles = _extract_eu_articles(payload_text, celex)
            if not raw_articles:
                logger.debug("No articles found in EUR-Lex CELEX %s.", celex)
                continue

            # Citation title for articles: prefer the stored instrument value so a
            # previously-seeded title (e.g. "EVRM") is not overwritten by the CELEX
            # pattern derivation.
            inst_props = inserted_instrument.props
            eu_ct = inst_props.get("citation_title") or inst_props.get("title")

            article_nodes: list[Node] = []
            article_docs: list[dict[str, Any]] = []
            for art in raw_articles:
                article_number = art["article_number"]
                article_props: dict[str, Any] = {
                    "celex": celex,
                    "article_number": article_number,
                    "text": art["text"],
                }
                if eu_ct:
                    article_props["instrument_citation_title"] = eu_ct
                article_props["display_name"] = (
                    f"Artikel {article_number} {eu_ct}".strip()
                    if eu_ct
                    else f"Artikel {article_number}"
                )
                article_key = make_node_key(celex, article_number)
                article_node = Node(
                    collection=COLLECTION_INSTRUMENT_ARTICLES,
                    type=NodeType.ARTICLE,
                    key=article_key,
                    labels=["EU", "Article"],
                    props=article_props,
                )
                article_docs.append(article_node.to_document())
                article_nodes.append(article_node)

            # Batch-upsert all article nodes for this CELEX record.
            if article_docs:
                for batch_start in range(0, len(article_docs), _NODE_BATCH_SIZE):
                    batch = article_docs[batch_start : batch_start + _NODE_BATCH_SIZE]
                    self.store.bulk_insert_or_update_nodes(
                        COLLECTION_INSTRUMENT_ARTICLES, batch
                    )

            articles_by_celex[celex] = [
                node.with_key(node.key or "") for node in article_nodes
            ]
            logger.debug("CELEX %s: %d articles extracted.", celex, len(article_nodes))

        total_articles = sum(len(v) for v in articles_by_celex.values())
        logger.info(
            "Created %d EUR-Lex instrument nodes and %d article nodes.",
            len(instruments_by_celex),
            total_articles,
        )

        return {
            "instruments_by_celex": instruments_by_celex,
            "articles_by_celex": articles_by_celex,
        }

    def build_edges(
        self,
        raw: list[dict[str, Any]],
        normalized: dict[str, Any],
    ) -> int:
        """Create PART_OF_INSTRUMENT edges for articles."""
        edge_count = 0

        # Article → instrument edges
        instruments_by_celex: dict[str, Node] = normalized.get(
            "instruments_by_celex", {}
        )
        for celex, article_nodes in normalized.get("articles_by_celex", {}).items():
            instrument = instruments_by_celex.get(celex)
            if not instrument or not instrument.arango_id:
                continue
            for article in article_nodes:
                if not article.arango_id:
                    continue
                self.store.create_edge(
                    from_id=article.arango_id,
                    to_id=instrument.arango_id,
                    relation=RELATION_PART_OF_INSTRUMENT,
                    source="eu-normalize",
                )
                edge_count += 1

        logger.info(
            "EUNormalizePipeline created %d edges.",
            edge_count,
        )
        return edge_count
