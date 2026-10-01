from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_EU_CELEX,
    RELATION_PART_OF,
    SOURCE_EURLEX,
)
from lawgraph.core.eu_titles import act_names
from lawgraph.core.eurlex_html import parse_act
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import EdgeWriter, GraphStore, NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "eu-normalize"

_NODE_BATCH_SIZE = 200


class EurlexNormalizePipeline(NormalizePipelineBase):
    """Normalization pipeline that turns EUR-Lex raw dumps into instrument + article nodes."""

    def __init__(self, *, store: GraphStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream the EUR-Lex CELEX html dumps from raw_sources (whole acts: 20 at a time)."""
        return self._iter_raw_sources(
            source=SOURCE_EURLEX,
            kinds=[RAW_KIND_EU_CELEX],
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

            act = parse_act(payload_text or "")
            names = act_names(celex, act.title)
            # always written: an upsert merges props, so a stale name goes
            props["title"] = names.title
            props["citation_title"] = names.citation_title
            props["short_title"] = names.short_title
            props["display_name"] = names.citation_title or names.title or f"EU {celex}"

            labels = ["EU"]
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
            raw_articles = act.articles
            if not raw_articles:
                logger.debug("No articles found in EUR-Lex CELEX %s.", celex)
                continue

            eu_ct = names.citation_title or names.title

            article_nodes: list[Node] = []
            for position, art in enumerate(raw_articles):
                article_number = art.number
                article_props: dict[str, Any] = {
                    "celex": celex,
                    "article_number": article_number,
                    # always written: an upsert merges props, so a stale heading goes
                    "heading": art.heading,
                    "text": art.text,
                    "parts": [part.to_dict() for part in art.parts],
                    "position": position,
                    "breadcrumb": [crumb.to_dict() for crumb in art.breadcrumb] or None,
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
                    article.node_id,
                    instrument.node_id,
                    RELATION_PART_OF,
                    source=EDGE_SOURCE,
                )
        writer.flush()
