from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_SOURCE_KINDS,
    RELATION_PART_OF,
    SOURCE_EURLEX,
)
from lawgraph.core.eurlex_html import parse_articles
from lawgraph.core.identifiers import parse_celex
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.xml import XML_TAG_RE
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "eu-normalize"

_NODE_BATCH_SIZE = 200

_DOC_TI_RE = re.compile(
    r'<p[^>]+class=["\'][^"\']*doc-ti[^"\']*["\'][^>]*>(.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)

# Dutch citation label per instrument kind (CELEX letters live in core.identifiers).
_KIND_CITATION_LABELS: dict[str, str] = {
    "directive": "Richtlijn",
    "regulation": "Verordening",
    "decision": "Besluit",
    "framework_decision": "Kaderbesluit",
}


def _extract_eu_title_from_html(html: str) -> str | None:
    """Return the document title from CELLAR HTML, or None if not found."""
    m = _DOC_TI_RE.search(html)
    if m:
        text = XML_TAG_RE.sub("", m.group(1)).replace("\xa0", " ").strip()
        if len(text) > 5:
            return " ".join(text.split())
    return None


def _derive_eu_citation_title(celex: str) -> str | None:
    """Derive a short citation title from a CELEX number, e.g. 'Richtlijn 2010/64/EU'."""
    parsed = parse_celex(celex)
    if parsed is None or parsed.kind is None:
        return None
    label = _KIND_CITATION_LABELS.get(parsed.kind)
    if not label:
        return None
    number = parsed.number.lstrip("0") or "0"
    suffix = "JBZ" if parsed.kind == "framework_decision" else "EU"
    return f"{label} {parsed.year}/{number}/{suffix}"


class EurlexNormalizePipeline(NormalizePipelineBase):
    """Normalization pipeline that turns EUR-Lex raw dumps into instrument + article nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream the EUR-Lex CELEX html dumps from raw_sources (whole acts: 20 at a time)."""
        return self._iter_raw_sources(
            source=SOURCE_EURLEX,
            kinds=list(RAW_SOURCE_KINDS[SOURCE_EURLEX]),
            since=since,
        )

    def normalize_nodes(
        self,
        raw: Iterable[dict[str, Any]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Normalize EUR-Lex raw HTML into instrument and article nodes.

        The articles are written as they are parsed; what is kept for the PART_OF edges is
        a node without props per article, not its text.
        """
        instruments_by_celex: dict[str, Node] = {}
        articles_by_celex: dict[str, list[Node]] = {}
        writer = NodeWriter(self.store, batch_size=_NODE_BATCH_SIZE)

        for raw_entry in raw:
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
            inserted_instrument, _ = self.store.insert_or_update(instrument_node)
            instruments_by_celex[celex] = inserted_instrument

            # --- article nodes ---
            if not payload_text:
                continue

            raw_articles = parse_articles(payload_text)
            if not raw_articles:
                logger.debug("No articles found in EUR-Lex CELEX %s.", celex)
                continue

            # Citation title for articles: prefer the stored instrument value so a
            # title already seeded (e.g. "EVRM") is not overwritten by the CELEX
            # pattern derivation.
            inst_props = inserted_instrument.props
            eu_ct = inst_props.get("citation_title") or inst_props.get("title")

            article_nodes: list[Node] = []
            for art in raw_articles:
                article_number = art.number
                article_props: dict[str, Any] = {
                    "celex": celex,
                    "article_number": article_number,
                    # always written: an upsert merges props, so a stale heading goes
                    "heading": art.heading,
                    "text": art.text,
                    "parts": [part.to_dict() for part in art.parts],
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
                    collection=COLLECTION_ARTICLES,
                    type=NodeType.ARTICLE,
                    key=article_key,
                    labels=["EU", "Article"],
                    props=article_props,
                )
                writer.add(article_node)
                article_nodes.append(
                    Node(
                        collection=COLLECTION_ARTICLES,
                        type=NodeType.ARTICLE,
                        key=article_key,
                        props={},
                        _skip_validation=True,
                    )
                )

            articles_by_celex[celex] = article_nodes
            logger.debug("CELEX %s: %d articles extracted.", celex, len(article_nodes))

        writer.flush()
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
        raw: Iterable[dict[str, Any]],
        normalized: dict[str, Any],
    ) -> None:
        """Create PART_OF edges from articles to their instrument."""
        writer = EdgeWriter(self.store, what="article edges")

        # Article → instrument edges
        instruments_by_celex: dict[str, Node] = normalized.get(
            "instruments_by_celex", {}
        )
        for celex, article_nodes in normalized.get("articles_by_celex", {}).items():
            instrument = instruments_by_celex.get(celex)
            if not instrument:
                continue
            for article in article_nodes:
                writer.add(
                    article.arango_id,
                    instrument.arango_id,
                    RELATION_PART_OF,
                    source=EDGE_SOURCE,
                )
        writer.flush()
