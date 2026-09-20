from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_SOURCE_KINDS,
    RELATION_PART_OF,
    SOURCE_BWB,
)
from lawgraph.core.bwb_xml import article_props, instrument_props, parse_toestand
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "bwb-normalize"


class BWBNormalizePipeline(NormalizePipelineBase):
    """Normalize BWB XML into Instrument and Article nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream the BWB raw_sources records relevant to instrument/article parsing."""
        return self._iter_raw_sources(
            source=SOURCE_BWB, kinds=list(RAW_SOURCE_KINDS[SOURCE_BWB]), since=since
        )

    def normalize_nodes(
        self,
        raw: Iterable[dict[str, Any]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Parse the current BWB toestand of each regulation into Instrument and Article nodes."""
        instruments_by_bwb: dict[str, Node] = {}
        articles_by_bwb: dict[str, list[Node]] = {}
        article_count = 0

        with NodeWriter(self.store) as writer:
            for record in raw:
                payload_text = self._payload_text(record)
                bwb_id = self._meta(record).get("bwb_id") or record.get("external_id")
                if not payload_text or not bwb_id:
                    logger.warning(
                        "BWB record %s has no text payload or bwb_id; skipping.",
                        record.get("_key"),
                    )
                    continue
                try:
                    toestand = parse_toestand(payload_text)
                except ET.ParseError as exc:
                    logger.warning("XML parsing failed for BWB %s: %s", bwb_id, exc)
                    continue

                instrument = instruments_by_bwb.get(bwb_id)
                if instrument is None:
                    instrument = self._upsert_instrument(
                        bwb_id, instrument_props(toestand, bwb_id)
                    )
                    instruments_by_bwb[bwb_id] = instrument

                for article in toestand.articles:
                    if not article.number or not article.text:
                        logger.debug(
                            "Skipping article without number or text in %s.", bwb_id
                        )
                        continue
                    props = article_props(
                        article, bwb_id, instrument.props.get("citation_title")
                    )
                    key = make_node_key(bwb_id, article.number)
                    writer.add(
                        Node(
                            collection=COLLECTION_ARTICLES,
                            type=NodeType.ARTICLE,
                            key=key,
                            labels=["BWB", "Article"],
                            props=props,
                        )
                    )
                    # build_edges only needs identity, so keep light nodes in memory
                    articles_by_bwb.setdefault(bwb_id, []).append(
                        Node(
                            collection=COLLECTION_ARTICLES,
                            type=NodeType.ARTICLE,
                            key=key,
                            props={},
                            _skip_validation=True,
                        )
                    )
                    article_count += 1

        logger.info(
            "Normalized %d BWB articles for %d instruments.",
            article_count,
            len(instruments_by_bwb),
        )
        return {
            "instruments_by_bwb": instruments_by_bwb,
            "articles_by_bwb": articles_by_bwb,
        }

    def build_edges(
        self,
        raw: Any,
        normalized: dict[str, Any],
    ) -> None:
        """Link BWB articles to their instruments with PART_OF edges."""
        instruments: dict[str, Node] = normalized.get("instruments_by_bwb", {})
        articles: dict[str, list[Node]] = normalized.get("articles_by_bwb", {})
        writer = EdgeWriter(self.store)
        for bwb_id, instrument in instruments.items():
            for article in articles.get(bwb_id, []):
                writer.add(
                    article.arango_id,
                    instrument.arango_id,
                    RELATION_PART_OF,
                    source=EDGE_SOURCE,
                )
        writer.flush()

    def _upsert_instrument(self, bwb_id: str, props: dict[str, Any]) -> Node:
        node = Node(
            collection=COLLECTION_INSTRUMENTS,
            type=NodeType.INSTRUMENT,
            key=make_node_key(bwb_id),
            labels=["BWB"],
            props=props,
        )
        instrument, _ = self.store.insert_or_update(node)
        return instrument
