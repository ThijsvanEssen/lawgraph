from __future__ import annotations

import datetime as dt
import re
from html.parser import HTMLParser
from typing import Any

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_SOURCE_KINDS,
    RELATION_PART_OF_INSTRUMENT,
    SOURCE_EURLEX,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.normalize.base import NormalizePipeline
from lawgraph.utils.display import CELEX_SHORTHANDS, make_display_name

logger = get_logger(__name__)

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


_EU_MAX_ARTICLE_NUMBER = 200


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
            continue
        articles.append({"article_number": article_number, "text": body})

    return articles


class EUNormalizePipeline(NormalizePipeline):
    """Normalization pipeline that turns EUR-Lex raw dumps into instrument + article nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store, domain_profile="strafrecht")

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
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

        return {"celex_html": records}

    def normalize_nodes(
        self,
        raw: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Normalize EUR-Lex raw HTML into instrument and article nodes."""
        instruments_by_celex: dict[str, Node] = {}
        articles_by_celex: dict[str, list[Node]] = {}
        celex_records = raw.get("celex_html", [])
        strafrecht_nodes: list[Node] = []

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
            props: dict[str, Any] = {"celex": celex}
            if lang:
                props["lang"] = lang
            if meta:
                props["meta"] = meta

            is_strafrecht = self._is_strafrecht_eu_instrument(celex, payload_text)
            labels = ["EU"]
            if is_strafrecht:
                labels.append("Strafrecht")
                props["strafrecht_profile"] = "eu"

            props["display_name"] = make_display_name(NodeType.INSTRUMENT, props)
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
            if is_strafrecht:
                strafrecht_nodes.append(inserted_instrument)

            # --- article nodes ---
            if not payload_text:
                continue

            raw_articles = _extract_eu_articles(payload_text, celex)
            if not raw_articles:
                logger.debug("No articles found in EUR-Lex CELEX %s.", celex)
                continue

            # Derive the citation title for this EU instrument so every article
            # carries the law name (used by make_display_name and stub labels).
            inst_props = inserted_instrument.props if inserted_instrument else {}
            eu_ct = (
                inst_props.get("citation_title")
                or inst_props.get("title")
                or CELEX_SHORTHANDS.get(celex.upper())
            )

            article_nodes: list[Node] = []
            for art in raw_articles:
                article_number = art["article_number"]
                article_props: dict[str, Any] = {
                    "celex": celex,
                    "article_number": article_number,
                    "text": art["text"],
                }
                if eu_ct:
                    article_props["instrument_citation_title"] = eu_ct
                article_props["display_name"] = make_display_name(
                    NodeType.ARTICLE, article_props
                )
                article_key = make_node_key(celex, article_number)
                article_node = Node(
                    collection=COLLECTION_INSTRUMENT_ARTICLES,
                    type=NodeType.ARTICLE,
                    key=article_key,
                    labels=["EU", "Article"],
                    props=article_props,
                )
                inserted_article = self.store.insert_or_update(article_node)
                article_nodes.append(inserted_article)

            articles_by_celex[celex] = article_nodes
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
            "strafrecht_nodes": strafrecht_nodes,
        }

    def build_edges(
        self,
        raw: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> int:
        """Create PART_OF_INSTRUMENT edges for articles and topic edges for instruments."""
        edge_count = 0

        # Article → instrument edges
        instruments_by_celex: dict[str, Node] = normalized.get(
            "instruments_by_celex", {}
        )
        for celex, article_nodes in normalized.get("articles_by_celex", {}).items():
            instrument = instruments_by_celex.get(celex)
            if not instrument or not instrument.id:
                continue
            for article in article_nodes:
                if not article.id:
                    continue
                self.store.create_edge(
                    from_id=article.id,
                    to_id=instrument.id,
                    relation=RELATION_PART_OF_INSTRUMENT,
                    source="eu-normalize",
                )
                edge_count += 1

        # Instrument → topic edges
        topic_node = self._get_domain_topic_node()
        if topic_node:
            for node in normalized.get("strafrecht_nodes", []):
                if not node.id:
                    continue
                if self._ensure_related_topic_edge(
                    node=node,
                    topic_node=topic_node,
                    source="eu-normalize",
                ):
                    edge_count += 1
        else:
            logger.debug("No strafrecht topic found; skipping related-topic edges.")

        logger.info(
            "EUNormalizePipeline created %d semantic edges.",
            edge_count,
        )
        return edge_count

    def _is_strafrecht_eu_instrument(
        self,
        celex: str | None,
        payload_text: str | None,
    ) -> bool:
        config = self._load_domain_config()
        filters = config.get("filters", {}).get("eurlex", {})
        instrument_celex = {
            entry.get("celex")
            for entry in config.get("eu_instruments", [])
            if entry.get("celex")
        }
        celex_ids = set(filters.get("celex_ids", []))
        subject_keywords = filters.get("subject_keywords", [])

        if celex and (celex in instrument_celex or celex in celex_ids):
            return True

        if payload_text and self._text_contains_keywords(
            payload_text, subject_keywords
        ):
            return True

        return False
