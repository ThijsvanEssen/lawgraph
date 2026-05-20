from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_SOURCE_KINDS,
    RELATION_PART_OF_INSTRUMENT,
    SOURCE_BWB,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore
from lawgraph.db import _edge_key as _sha1_edge_key
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)


class BWBNormalizePipeline(NormalizePipeline):
    """
    Normaliseer BWB-XML naar instrument- en artikel-nodes in Arango.
    """

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return the BWB raw_sources records relevant to instrument/article parsing."""
        kinds = list(RAW_SOURCE_KINDS[SOURCE_BWB])
        rows = self._query_raw_sources(
            source=SOURCE_BWB,
            kinds=kinds,
            since=since,
        )
        logger.info("Loaded %d BWB raw_sources.", len(rows))
        return rows

    _NODE_BATCH_SIZE = 200

    def normalize_nodes(
        self,
        raw: list[dict[str, Any]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Parse BWB XML dumps into instrument and article nodes."""
        instruments_by_bwb: dict[str, Node] = {}
        articles_by_bwb: dict[str, list[Node]] = {}
        article_count = 0

        for record in raw:
            payload_text = self._payload_text(record)
            if not payload_text:
                logger.warning(
                    "BWB record %s has no text payload; skipping.",
                    record.get("_key"),
                )
                continue

            meta = self._meta(record)
            bwb_id = meta.get("bwb_id") or record.get("external_id")
            if not bwb_id:
                logger.warning(
                    "BWB record %s missing bwb_id; skipping.",
                    record.get("_key"),
                )
                continue

            # Parse XML once and reuse the root for title extraction and article scanning.
            try:
                root = ET.fromstring(payload_text)
            except ET.ParseError as exc:
                logger.warning("XML parsing failed for BWB %s: %s", bwb_id, exc)
                continue

            instrument = instruments_by_bwb.get(bwb_id)
            if not instrument:
                titel = self._extract_instrument_title_from_root(root, bwb_id)
                citation_title = self._extract_citation_title_from_root(root)
                instrument = self._get_or_create_instrument(
                    bwb_id, title=titel, citation_title=citation_title
                )
                instruments_by_bwb[bwb_id] = instrument
            citation_title = instrument.props.get("citation_title")

            article_elements = self._find_article_elements(root)
            if not article_elements:
                logger.debug("No articles found in BWB %s.", bwb_id)
                continue

            # Accumulate article node docs and batch-upsert per instrument.
            article_docs: list[dict[str, Any]] = []
            article_nodes: list[Node] = []

            for article in article_elements:
                article_number = self._extract_article_number(article)
                if not article_number:
                    logger.debug("Article in %s has no number; skipping.", bwb_id)
                    continue

                article_text = self._extract_article_text(article)
                if not article_text:
                    logger.debug(
                        "Article %s in %s has no text; skipping.",
                        article_number,
                        bwb_id,
                    )
                    continue

                article_props: dict[str, Any] = {
                    "bwb_id": bwb_id,
                    "article_number": article_number,
                    "text": article_text,
                }
                if citation_title:
                    article_props["instrument_citation_title"] = citation_title
                ct = citation_title or ""
                article_props["display_name"] = f"Artikel {article_number} {ct}".strip()

                logger.debug("Article props: %s", article_props)

                article_key = make_node_key(bwb_id, article_number)
                node = Node(
                    collection=COLLECTION_INSTRUMENT_ARTICLES,
                    type=NodeType.ARTICLE,
                    key=article_key,
                    labels=["BWB", "Article"],
                    props=article_props,
                )
                article_docs.append(node.to_document())
                article_nodes.append(node)

            # Batch-upsert all article nodes for this BWB record.
            if article_docs:
                for batch_start in range(0, len(article_docs), self._NODE_BATCH_SIZE):
                    batch = article_docs[
                        batch_start : batch_start + self._NODE_BATCH_SIZE
                    ]
                    self.store.bulk_insert_or_update_nodes(
                        COLLECTION_INSTRUMENT_ARTICLES, batch
                    )
                articles_by_bwb.setdefault(bwb_id, []).extend(
                    node.with_key(node.key or "") for node in article_nodes
                )
                article_count += len(article_nodes)

        logger.info(
            "Normalized %d BWB articles for %d instruments.",
            article_count,
            len(instruments_by_bwb),
        )

        return {
            "instruments_by_bwb": instruments_by_bwb,
            "articles_by_bwb": articles_by_bwb,
        }

    _EDGE_BATCH_SIZE = 500

    def build_edges(
        self,
        raw: Any,
        normalized: dict[str, Any],
    ) -> int:
        """Link BWB articles to their instruments via strict PART_OF_INSTRUMENT edges."""
        instruments: dict[str, Node] = normalized.get("instruments_by_bwb", {})
        articles: dict[str, list[Node]] = normalized.get("articles_by_bwb", {})
        edge_docs: list[dict[str, Any]] = []

        for bwb_id, instrument in instruments.items():
            if not instrument.id:
                continue
            for article in articles.get(bwb_id, []):
                if not article.id:
                    continue
                edge_key = _sha1_edge_key(
                    instrument.id, RELATION_PART_OF_INSTRUMENT, article.id
                )
                edge_docs.append(
                    {
                        "_key": edge_key,
                        "_from": instrument.id,
                        "_to": article.id,
                        "relation": RELATION_PART_OF_INSTRUMENT,
                        "source": "bwb-normalize",
                        "status": "canoniek",
                        "meta": {},
                    }
                )

        total_created = 0
        for batch_start in range(0, len(edge_docs), self._EDGE_BATCH_SIZE):
            batch = edge_docs[batch_start : batch_start + self._EDGE_BATCH_SIZE]
            try:
                created, _ = self.store.bulk_insert_or_update_edges(batch)
                total_created += created
            except Exception as exc:
                logger.error("BWB edge batch upsert failed: %s", exc)
                raise

        logger.info("BWB normalization created/updated %d edges.", total_created)
        return total_created

    @classmethod
    def _extract_instrument_title_from_root(
        cls,
        root: ET.Element,
        bwb_id: str,
    ) -> str:
        """Extract instrument title from a pre-parsed XML root."""
        _TITLE_PRIORITY: dict[str, int] = {
            "citeertitel": 0,
            "officiele-titel": 1,
            "officietitel": 1,
            "intitule": 2,
        }
        best: tuple[int, str] | None = None
        for el in root.iter():
            local = cls._local_name(el.tag).lower()
            priority = _TITLE_PRIORITY.get(local)
            if priority is None:
                continue
            text = " ".join((el.text or "").split()).strip()
            if not text:
                continue
            if best is None or priority < best[0]:
                best = (priority, text)
        return best[1] if best else f"BWB-regeling {bwb_id}"

    @classmethod
    def _extract_citation_title_from_root(cls, root: ET.Element) -> str | None:
        """Extract <citeertitel> from a pre-parsed XML root."""
        for el in root.iter():
            if cls._local_name(el.tag).lower() == "citeertitel":
                text = " ".join((el.text or "").split()).strip()
                if text:
                    return text
        return None

    def _get_or_create_instrument(
        self,
        bwb_id: str,
        title: str | None = None,
        citation_title: str | None = None,
    ) -> Node:
        instrument_key = make_node_key(bwb_id)
        instrument_props: dict[str, Any] = {
            "source": SOURCE_BWB,
            "bwb_id": bwb_id,
            "title": title if title is not None else f"BWB-regeling {bwb_id}",
            "jurisdiction": "nl",
        }
        if citation_title:
            instrument_props["citation_title"] = citation_title
        instrument_props["display_name"] = (
            instrument_props.get("title") or f"BWB {bwb_id}"
        )
        node = Node(
            collection=COLLECTION_INSTRUMENTS,
            type=NodeType.INSTRUMENT,
            key=instrument_key,
            labels=["BWB"],
            props=instrument_props,
        )
        return self.store.insert_or_update(node)

    @staticmethod
    def _find_article_elements(root: ET.Element) -> list[ET.Element]:
        articles: list[ET.Element] = []
        for element in root.iter():
            local = BWBNormalizePipeline._local_name(element.tag)
            if local == "artikel":
                articles.append(element)
                continue

            label = (element.attrib.get("label") or "").strip()
            if label and label.lower().startswith("artikel"):
                articles.append(element)

        return articles

    @classmethod
    def _extract_article_number(cls, article: ET.Element) -> str | None:
        kop = cls._find_descendant(article, "kop")
        if kop is not None:
            nr = cls._find_descendant(kop, "nr")
            if nr is not None:
                text = cls._text_from_element(nr)
                if text:
                    return text

        label = (article.attrib.get("label") or "").strip()
        prefix = "artikel"
        if label and label.lower().startswith(prefix):
            remainder = label[len(prefix) :]
            remainder = remainder.lstrip(":. ").strip()
            if remainder:
                return remainder

        return None

    @classmethod
    def _extract_article_text(cls, article: ET.Element) -> str:
        lid_texts = cls._collect_lid_texts(article)
        if lid_texts:
            return "\n".join(lid_texts).strip()
        return cls._collect_fallback_texts(article)

    @classmethod
    def _collect_lid_texts(cls, article: ET.Element) -> list[str]:
        lid_texts: list[str] = []
        for element in article.iter():
            if cls._local_name(element.tag) != "lid":
                continue
            parts = [
                cls._text_from_element(child)
                for child in element
                if cls._local_name(child.tag) == "al" and cls._text_from_element(child)
            ]
            if not parts:
                continue
            lidnr_elem = cls._find_descendant(element, "lidnr")
            lidnr = cls._text_from_element(lidnr_elem) if lidnr_elem is not None else ""
            prefix = f"{lidnr}. " if lidnr else ""
            lid_texts.append(f"{prefix}{' '.join(parts)}")
        return lid_texts

    @classmethod
    def _collect_fallback_texts(cls, article: ET.Element) -> str:
        parts: list[str] = []
        for element in article.iter():
            if cls._local_name(element.tag) == "al":
                text = cls._text_from_element(element)
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()

    @staticmethod
    def _local_name(tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    @staticmethod
    def _text_from_element(element: ET.Element | None) -> str:
        if element is None:
            return ""
        return "".join(element.itertext()).strip()

    @classmethod
    def _find_descendant(
        cls, element: ET.Element, local_name: str
    ) -> ET.Element | None:
        for node in element.iter():
            if node is element:
                continue
            if cls._local_name(node.tag) == local_name:
                return node
        return None
