from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RAW_SOURCE_KINDS,
    RELATION_PART_OF_INSTRUMENT,
    SOURCE_BWB,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.normalize.base import NormalizePipeline
from lawgraph.utils.display import make_display_name

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

    def normalize_nodes(
        self,
        raw: list[dict[str, Any]],
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

            instrument = instruments_by_bwb.get(bwb_id)
            if not instrument:
                titel = self._extract_instrument_title(payload_text, bwb_id)
                citation_title = self._extract_citation_title(payload_text)
                instrument = self._get_or_create_instrument(
                    bwb_id, title=titel, citation_title=citation_title
                )
                instruments_by_bwb[bwb_id] = instrument

            try:
                root = ET.fromstring(payload_text)
            except ET.ParseError as exc:
                logger.warning(
                    "XML parsing failed for BWB %s: %s",
                    bwb_id,
                    exc,
                )
                continue

            article_elements = self._find_article_elements(root)
            if not article_elements:
                logger.debug("No articles found in BWB %s.", bwb_id)
                continue

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
                article_props["display_name"] = make_display_name(
                    NodeType.ARTICLE, article_props
                )

                logger.debug("Article props: %s", article_props)

                article_key = make_node_key(bwb_id, article_number)
                node = Node(
                    collection=COLLECTION_INSTRUMENT_ARTICLES,
                    type=NodeType.ARTICLE,
                    key=article_key,
                    labels=["BWB", "Article"],
                    props=article_props,
                )
                inserted = self.store.insert_or_update(node)
                articles_by_bwb.setdefault(bwb_id, []).append(inserted)
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
    ) -> int:
        """Link BWB articles to their instruments via strict PART_OF_INSTRUMENT edges."""
        instruments: dict[str, Node] = normalized.get("instruments_by_bwb", {})
        articles: dict[str, list[Node]] = normalized.get("articles_by_bwb", {})
        edge_count = 0

        for bwb_id, instrument in instruments.items():
            if not instrument.id:
                continue

            for article in articles.get(bwb_id, []):
                if not article.id:
                    continue

                try:
                    self.store.create_edge(
                        from_id=instrument.id,
                        to_id=article.id,
                        relation=RELATION_PART_OF_INSTRUMENT,
                        source="bwb-normalize",
                    )
                    edge_count += 1
                except Exception as exc:
                    logger.error(
                        "Could not create BWB edge %s → %s: %s",
                        instrument.id,
                        article.id,
                        exc,
                    )

        logger.info("BWB normalization created %d edges.", edge_count)
        return edge_count

    @staticmethod
    def _extract_instrument_title(
        xml_text: str | None,
        bwb_id: str,
    ) -> str:
        """Extract the human-readable law title from BWB toestand XML.

        Tries element names in preference order:
          citeertitel → officiele-titel / officieleTitel → intitule
        Falls back to 'BWB-regeling {bwb_id}' if no title element is found.
        """
        if not xml_text:
            return f"BWB-regeling {bwb_id}"
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return f"BWB-regeling {bwb_id}"

        def _local(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        # Map normalised local names → priority (lower = higher priority)
        _TITLE_PRIORITY: dict[str, int] = {
            "citeertitel": 0,
            "officiele-titel": 1,
            "officietitel": 1,  # camelCase without dash
            "intitule": 2,
        }

        best: tuple[int, str] | None = None
        for el in root.iter():
            local = _local(el.tag).lower()
            priority = _TITLE_PRIORITY.get(local)
            if priority is None:
                continue
            text = " ".join((el.text or "").split()).strip()
            if not text:
                continue
            if best is None or priority < best[0]:
                best = (priority, text)

        return best[1] if best else f"BWB-regeling {bwb_id}"

    @staticmethod
    def _extract_citation_title(xml_text: str | None) -> str | None:
        """Extract only the <citeertitel> element from BWB XML.

        Returns the citeertitel text if found, or None if absent.
        """
        if not xml_text:
            return None
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None

        def _local(tag: str) -> str:
            return tag.split("}", 1)[-1] if "}" in tag else tag

        for el in root.iter():
            if _local(el.tag).lower() == "citeertitel":
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
        instrument_props["display_name"] = make_display_name(
            NodeType.INSTRUMENT, instrument_props
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
