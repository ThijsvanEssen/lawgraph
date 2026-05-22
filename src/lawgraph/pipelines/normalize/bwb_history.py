from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENT_ARTICLE_VERSIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    RAW_KIND_BWB_TOESTAND_ALL,
    RELATION_PART_OF_VERSION,
    RELATION_SUPERSEDES,
    RELATION_VERSION_OF,
    SOURCE_BWB,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.db import ArangoStore
from lawgraph.db import edge_key as _sha1_edge_key
from lawgraph.pipelines.normalize.bwb import BWBNormalizePipeline

logger = get_logger(__name__)

_OPEN_ENDED_DATE = "9999-12-31"


class BWBHistoryNormalizePipeline(BWBNormalizePipeline):
    """Normalize all historical BWB toestanden into versioned article nodes.

    Inherits the XML-parsing helpers from ``BWBNormalizePipeline``
    (``_extract_instrument_title_from_root``, ``_extract_citation_title_from_root``,
    ``_get_or_create_instrument``, ``_find_article_elements``, etc.)
    and extends them to produce ``instrument_versions`` and
    ``instrument_article_versions`` nodes connected by ``VERSION_OF``,
    ``PART_OF_VERSION``, and ``SUPERSEDES`` edges.
    """

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return raw_source records for all historical BWB toestanden."""
        rows = self._query_raw_sources(
            source=SOURCE_BWB,
            kinds=[RAW_KIND_BWB_TOESTAND_ALL],
            since=since,
        )
        logger.info("Loaded %d historical BWB raw_sources.", len(rows))
        return rows

    def normalize_nodes(
        self,
        raw: list[dict[str, Any]],
        result: PipelineResult,
    ) -> dict[str, Any]:
        """Parse historical BWB XML dumps into instrument_version and article_version nodes."""
        instruments_by_bwb: dict[str, Node] = {}
        versions_by_key: dict[str, Node] = {}
        article_versions_by_key: dict[str, Node] = {}
        version_count = 0
        article_version_count = 0

        for record in raw:
            payload_text = self._payload_text(record)
            if not payload_text:
                logger.warning(
                    "BWB history record %s has no text payload; skipping.",
                    record.get("_key"),
                )
                continue

            meta = self._meta(record)
            bwb_id = meta.get("bwb_id") or record.get("external_id", "").split("@")[0]
            if not bwb_id:
                logger.warning(
                    "BWB history record %s missing bwb_id; skipping.",
                    record.get("_key"),
                )
                continue

            start_date: str = meta.get("start_date") or "unknown"
            end_date: str | None = meta.get("end_date")
            toestand_url: str | None = meta.get("toestand_url")

            # Parse XML once — used for both title extraction and article scanning.
            try:
                root = ET.fromstring(payload_text)
            except ET.ParseError as exc:
                logger.warning(
                    "XML parsing failed for BWB history %s@%s: %s",
                    bwb_id,
                    start_date,
                    exc,
                )
                continue

            # Ensure the parent instrument node exists.
            if bwb_id not in instruments_by_bwb:
                titel = self._extract_instrument_title_from_root(root, bwb_id)
                citation_title = self._extract_citation_title_from_root(root)
                instrument = self._get_or_create_instrument(
                    bwb_id, title=titel, citation_title=citation_title
                )
                instruments_by_bwb[bwb_id] = instrument
            citation_title = instruments_by_bwb[bwb_id].props.get("citation_title")

            # Create the instrument_version node.
            version_key = make_node_key(bwb_id, start_date)
            version_props: dict[str, Any] = {
                "bwb_id": bwb_id,
                "valid_from": start_date,
                "valid_until": end_date,
                "current": end_date == _OPEN_ENDED_DATE,
                "toestand_url": toestand_url,
            }
            version_node = Node(
                collection=COLLECTION_INSTRUMENT_VERSIONS,
                type=NodeType.INSTRUMENT_VERSION,
                key=version_key,
                labels=["BWB", "Version"],
                props=version_props,
            )
            inserted_version = self.store.insert_or_update(version_node)
            versions_by_key[version_key] = inserted_version
            version_count += 1

            article_elements = self._find_article_elements(root)
            if not article_elements:
                logger.debug(
                    "No articles found in BWB history %s@%s.", bwb_id, start_date
                )
                continue

            for article in article_elements:
                article_number = self._extract_article_number(article)
                if not article_number:
                    logger.debug(
                        "Article in %s@%s has no number; skipping.", bwb_id, start_date
                    )
                    continue

                article_text = self._extract_article_text(article)
                if not article_text:
                    logger.debug(
                        "Article %s in %s@%s has no text; skipping.",
                        article_number,
                        bwb_id,
                        start_date,
                    )
                    continue

                article_version_key = make_node_key(bwb_id, article_number, start_date)
                ct = citation_title or ""
                article_version_props: dict[str, Any] = {
                    "bwb_id": bwb_id,
                    "article_number": article_number,
                    "valid_from": start_date,
                    "valid_until": end_date,
                    "current": end_date == _OPEN_ENDED_DATE,
                    "text": article_text,
                    "display_name": f"Artikel {article_number} {ct}".strip(),
                }
                if citation_title:
                    article_version_props["instrument_citation_title"] = citation_title
                article_version_node = Node(
                    collection=COLLECTION_INSTRUMENT_ARTICLE_VERSIONS,
                    type=NodeType.ARTICLE_VERSION,
                    key=article_version_key,
                    labels=["BWB", "ArticleVersion"],
                    props=article_version_props,
                )
                inserted_article_version = self.store.insert_or_update(
                    article_version_node
                )
                article_versions_by_key[article_version_key] = inserted_article_version
                article_version_count += 1

        logger.info(
            "Normalized %d instrument versions and %d article versions for %d instruments.",
            version_count,
            article_version_count,
            len(instruments_by_bwb),
        )

        return {
            "instruments_by_bwb": instruments_by_bwb,
            "versions_by_key": versions_by_key,
            "article_versions_by_key": article_versions_by_key,
        }

    def build_edges(
        self,
        raw: Any,
        normalized: dict[str, Any],
    ) -> int:
        """Create VERSION_OF, PART_OF_VERSION, and SUPERSEDES edges."""
        instruments: dict[str, Node] = normalized.get("instruments_by_bwb", {})
        versions: dict[str, Node] = normalized.get("versions_by_key", {})
        article_versions: dict[str, Node] = normalized.get(
            "article_versions_by_key", {}
        )
        edge_docs: list[dict[str, Any]] = []

        # VERSION_OF: instrument_version → instrument
        for version_node in versions.values():
            if not version_node.arango_id:
                continue
            bwb_id = version_node.props.get("bwb_id")
            if not bwb_id:
                continue
            instrument = instruments.get(bwb_id)
            if not instrument or not instrument.arango_id:
                continue
            edge_key = _sha1_edge_key(
                version_node.arango_id, RELATION_VERSION_OF, instrument.arango_id
            )
            edge_docs.append(
                {
                    "_key": edge_key,
                    "_from": version_node.arango_id,
                    "_to": instrument.arango_id,
                    "relation": RELATION_VERSION_OF,
                    "source": "bwb-history-normalize",
                    "status": "canoniek",
                    "meta": {},
                }
            )

        # PART_OF_VERSION: article_version → instrument_version
        # Match article versions to their version node via bwb_id + valid_from.
        for article_version_node in article_versions.values():
            if not article_version_node.arango_id:
                continue
            bwb_id = article_version_node.props.get("bwb_id")
            start_date = article_version_node.props.get("valid_from") or "unknown"
            if not bwb_id:
                continue
            version_key = make_node_key(bwb_id, start_date)
            linked_version = versions.get(version_key)
            if not linked_version or not linked_version.arango_id:
                continue
            edge_key = _sha1_edge_key(
                article_version_node.arango_id,
                RELATION_PART_OF_VERSION,
                linked_version.arango_id,
            )
            edge_docs.append(
                {
                    "_key": edge_key,
                    "_from": article_version_node.arango_id,
                    "_to": linked_version.arango_id,
                    "relation": RELATION_PART_OF_VERSION,
                    "source": "bwb-history-normalize",
                    "status": "canoniek",
                    "meta": {},
                }
            )

        # SUPERSEDES: newer instrument_version → older instrument_version.
        # Query ALL versions from the DB for each bwb_id seen in this batch so the
        # chain is complete even when normalizing incrementally (e.g. --since 7d).
        seen_bwb_ids: set[str] = {
            str(v.props.get("bwb_id"))
            for v in versions.values()
            if v.props.get("bwb_id")
        }
        for bwb_id in seen_bwb_ids:
            db_versions = self._fetch_all_instrument_versions(bwb_id)
            for i in range(len(db_versions) - 1):
                newer_id = db_versions[i]["_id"]
                older_id = db_versions[i + 1]["_id"]
                if newer_id and older_id:
                    edge_key = _sha1_edge_key(newer_id, RELATION_SUPERSEDES, older_id)
                    edge_docs.append(
                        {
                            "_key": edge_key,
                            "_from": newer_id,
                            "_to": older_id,
                            "relation": RELATION_SUPERSEDES,
                            "source": "bwb-history-normalize",
                            "status": "canoniek",
                            "meta": {},
                        }
                    )

        total_created = self._batch_upsert_edges(edge_docs)
        logger.info(
            "BWB history normalization created/updated %d edges.", total_created
        )
        return total_created

    def _fetch_all_instrument_versions(self, bwb_id: str) -> list[dict]:
        """Return all instrument_versions for bwb_id from the DB, sorted newest first."""
        aql = """
        FOR doc IN instrument_versions
            FILTER doc.props.bwb_id == @bwb_id
            SORT doc.props.valid_from DESC
            RETURN {_id: doc._id, valid_from: doc.props.valid_from}
        """
        return list(self.store.query(aql, {"bwb_id": bwb_id.lower()}))
