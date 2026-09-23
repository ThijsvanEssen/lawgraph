from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_WTI_GENERAL,
    RELATION_PART_OF,
    SOURCE_BWB,
)
from lawgraph.core.annex_xml import ANNEX_EDGE_SOURCE, annex_node_key, annex_props
from lawgraph.core.batching import chunked
from lawgraph.core.bwb_wti import choose_short_titles, parse_abbreviations
from lawgraph.core.bwb_xml import (
    article_props,
    celex_refs,
    instrument_props,
    parse_toestand,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter
from lawgraph.db.queries import normalize as normalize_queries
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "bwb-normalize"
# Only the current toestand: the historical ones (``bwb-toestand-xml-all``) carry the same
# bwb_id and would overwrite the articles of today with those of whichever came last.
TOESTAND_KINDS = [RAW_KIND_BWB_TOESTAND]
SHORT_TITLE_BATCH_SIZE = 1000


class BWBNormalizePipeline(NormalizePipelineBase):
    """Normalize BWB XML into Instrument and Article nodes, with their short titles."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream the BWB raw_sources records relevant to instrument/article parsing."""
        return self._iter_raw_sources(
            source=SOURCE_BWB, kinds=TOESTAND_KINDS, since=since
        )

    def normalize_nodes(
        self,
        raw: Iterable[dict[str, Any]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Parse the current BWB toestand of each regulation into Instrument and Article nodes."""
        instruments_by_bwb: dict[str, Node] = {}
        articles_by_bwb: dict[str, list[Node]] = {}
        annexes_by_bwb: dict[str, list[str]] = {}  # annex keys
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
                    props = instrument_props(
                        toestand, bwb_id, celex_refs=celex_refs(payload_text)
                    )
                    # Through the writer, like the articles: one request per regulation
                    # was 42,000 round trips, and a write also when nothing changed.
                    instrument = Node(
                        collection=COLLECTION_INSTRUMENTS,
                        type=NodeType.INSTRUMENT,
                        key=make_node_key(bwb_id),
                        labels=["BWB"],
                        props=props,
                    )
                    writer.add(instrument)
                    instruments_by_bwb[bwb_id] = instrument

                for annex in toestand.annexes:
                    key = annex_node_key(bwb_id, annex.label)
                    writer.add(
                        Node(
                            collection=COLLECTION_ANNEXES,
                            type=NodeType.ANNEX,
                            key=key,
                            labels=["BWB", "Annex"],
                            props=annex_props(annex, bwb_id),
                        )
                    )
                    annexes_by_bwb.setdefault(bwb_id, []).append(key)

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
        self._write_short_titles(result)
        return {
            "instruments_by_bwb": instruments_by_bwb,
            "articles_by_bwb": articles_by_bwb,
            "annexes_by_bwb": annexes_by_bwb,
        }

    def build_edges(
        self,
        raw: Any,
        normalized: dict[str, Any],
    ) -> None:
        """PART_OF from every article and annex to its instrument."""
        instruments: dict[str, Node] = normalized.get("instruments_by_bwb", {})
        articles: dict[str, list[Node]] = normalized.get("articles_by_bwb", {})
        writer = EdgeWriter(self.store, what="article and annex edges")
        for bwb_id, instrument in instruments.items():
            for article in articles.get(bwb_id, []):
                writer.add(
                    article.arango_id,
                    instrument.arango_id,
                    RELATION_PART_OF,
                    source=EDGE_SOURCE,
                )
            for annex_key in normalized.get("annexes_by_bwb", {}).get(bwb_id, []):
                writer.add(
                    f"{COLLECTION_ANNEXES}/{annex_key}",
                    instrument.arango_id,
                    RELATION_PART_OF,
                    source=ANNEX_EDGE_SOURCE,
                    confidence=1.0,
                )
        writer.flush()

    def _write_short_titles(self, result: PipelineResult) -> None:
        """Set ``short_title`` on the instruments from the official WTI abbreviations.

        Which abbreviation wins depends on what the other regulations claim
        (``choose_short_titles``), so every stored WTI record is read on every run,
        whatever ``since`` is; the records are about 1 KB each. A regulation without a
        winning abbreviation loses a short title it had. Instruments that do not exist
        are not created.
        """
        abbreviations_by_bwb: dict[str, list[str]] = {}
        for record in self._iter_raw_sources(
            source=SOURCE_BWB, kinds=[RAW_KIND_BWB_WTI_GENERAL], batch_size=1000
        ):
            bwb_id = self._meta(record).get("bwb_id") or record.get("external_id")
            payload_text = self._payload_text(record)
            if not bwb_id or not payload_text:
                continue
            try:
                abbreviations_by_bwb[bwb_id] = parse_abbreviations(payload_text)
            except ET.ParseError as exc:
                logger.warning("XML parsing failed for BWB WTI %s: %s", bwb_id, exc)

        rows = [
            {"key": make_node_key(bwb_id), "short_title": short_title}
            for bwb_id, short_title in choose_short_titles(abbreviations_by_bwb).items()
        ]
        changed = 0
        for batch in chunked(rows, SHORT_TITLE_BATCH_SIZE):
            changed += normalize_queries.update_short_titles(self.store, batch)
        # The AQL update bypasses the counting store's upsert methods, so add it here.
        result.updated += changed
        logger.info(
            "BWB short titles: %d regulations with WTI, %d with an abbreviation, "
            "%d instruments changed.",
            len(rows),
            sum(1 for row in rows if row["short_title"]),
            changed,
        )
