from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_EURLEX_CELEX,
    RELATION_PART_OF,
    SOURCE_EURLEX,
)
from lawgraph.core.eu_titles import act_names
from lawgraph.core.eurlex_html import parse_act
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key, node_id
from lawgraph.core.raw_records import meta, payload_text
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)

EDGE_SOURCE = "eu-normalize"

_NODE_BATCH_SIZE = 200


@dataclass(frozen=True)
class Written:
    """What the edges need of the nodes written: per CELEX its instrument and the keys of
    its articles."""

    instruments: dict[str, Node] = field(default_factory=dict)
    articles: dict[str, list[str]] = field(default_factory=dict)


class EurlexNormalizePipeline(NormalizePipelineBase[Records]):
    """Normalization pipeline that turns EUR-Lex raw dumps into instrument + article nodes."""

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream the EUR-Lex CELEX html dumps from raw_sources (whole acts: 20 at a time)."""
        return self._iter_raw_sources(
            source=SOURCE_EURLEX,
            kinds=[RAW_KIND_EURLEX_CELEX],
            since=since,
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """The instruments and articles, then PART_OF from each article to its instrument."""
        self._link(self._write_nodes(raw))

    def _write_nodes(self, raw: Records) -> Written:
        """Normalize EUR-Lex raw HTML into instrument and article nodes.

        The articles are written as they are parsed; what is kept for the PART_OF edges is
        the key of each article, not its text.
        """
        written = Written()
        writer = NodeWriter(self.store, batch_size=_NODE_BATCH_SIZE)

        for raw_entry in raw:
            text = payload_text(raw_entry)
            facts = meta(raw_entry)
            celex = facts.get("celex")
            lang = facts.get("lang")

            if not celex:
                self.progress.skip("no CELEX", raw_entry.get("key"))
                continue

            # --- instrument node ---
            props: dict[str, Any] = {
                "source": SOURCE_EURLEX,
                "celex": celex,
                "jurisdiction": "eu",
            }
            if lang:
                props["lang"] = lang
            if facts:
                props["meta"] = facts

            act = parse_act(text or "")
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
                key=instrument_key,
                labels=labels,
                props=props,
            )
            # through the writer like the articles: one round trip per act was a write
            # also when nothing changed
            writer.add(instrument_node)
            written.instruments[celex] = instrument_node

            # --- article nodes ---
            raw_articles = act.articles
            if not raw_articles:
                logger.debug("No articles found in EUR-Lex CELEX %s.", celex)
                continue

            eu_ct = names.citation_title or names.title

            article_keys: list[str] = []
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
                    key=article_key,
                    labels=["EU", "Article"],
                    props=article_props,
                )
                writer.add(article_node)
                article_keys.append(article_key)

            written.articles[celex] = article_keys
            logger.debug("CELEX %s: %d articles extracted.", celex, len(article_keys))

        writer.flush()
        logger.info(
            "Created %d EUR-Lex instrument nodes and %d article nodes.",
            len(written.instruments),
            sum(len(keys) for keys in written.articles.values()),
        )
        return written

    def _link(self, written: Written) -> None:
        """Create PART_OF edges from articles to their instrument."""
        writer = EdgeWriter(self.store, what="article edges")
        for celex, article_keys in written.articles.items():
            instrument = written.instruments.get(celex)
            if not instrument:
                continue
            for article_key in article_keys:
                writer.add(
                    node_id(COLLECTION_ARTICLES, article_key),
                    instrument.node_id,
                    RELATION_PART_OF,
                    source=EDGE_SOURCE,
                )
        writer.flush()
