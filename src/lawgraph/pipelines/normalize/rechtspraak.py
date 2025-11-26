from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.settings import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_RS_INDEX,
    RAW_SOURCE_KINDS,
    SOURCE_RECHTSPRAAK,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.normalize.base import NormalizePipeline
from lawgraph.utils.display import make_display_name


logger = get_logger(__name__)


class RechtspraakNormalizePipeline(NormalizePipeline):
    """Normalization pipeline that turns Rechtspraak raw dumps into judgment nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store, domain_profile="strafrecht")

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Read Rechtspraak index and content raw_sources records."""
        kinds = list(RAW_SOURCE_KINDS[SOURCE_RECHTSPRAAK])
        rows = self._query_raw_sources(
            source=SOURCE_RECHTSPRAAK, kinds=kinds, since=since)
        grouped = self._group_by_kind(rows, kinds=kinds)

        index_records = grouped.get(RAW_KIND_RS_INDEX, [])
        content_records = grouped.get(RAW_KIND_RS_CONTENT, [])

        logger.info(
            "Loaded %d Rechtspraak index records and %d content records from raw_sources.",
            len(index_records),
            len(content_records),
        )

        return {"index": index_records, "content": content_records}

    def normalize_nodes(
        self,
        raw: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Convert Rechtspraak content payloads into judgment nodes."""
        judgments_by_ecli: dict[str, Node] = {}
        content_records = raw.get("content", [])
        strafrecht_nodes: list[Node] = []

        for raw_entry in content_records:
            payload_text = self._payload_text(raw_entry)
            meta = self._meta(raw_entry)
            ecli = meta.get("ecli")

            if not ecli:
                logger.warning(
                    "Skipping Rechtspraak content record without ECLI (_key=%s).",
                    raw_entry.get("_key"),
                )
                continue

            props: dict[str, Any] = {
                "ecli": ecli,
                "raw_xml": payload_text,
            }
            if raw_entry.get("kind"):
                props["source_kind"] = raw_entry["kind"]
            if meta:
                props["meta"] = meta

            is_strafrecht = self._is_strafrecht_judgment(
                payload_text, meta, ecli)
            labels = ["Rechtspraak"]
            if is_strafrecht:
                labels.append("Strafrecht")
                props["strafrecht_profile"] = "rechtspraak"

            props["display_name"] = make_display_name(NodeType.JUDGMENT, props)
            key = make_node_key(ecli)
            node = Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=key,
                labels=labels,
                props=props,
            )

            inserted_node = self.store.insert_or_update(node)
            judgments_by_ecli[ecli] = inserted_node
            if is_strafrecht:
                strafrecht_nodes.append(inserted_node)

        logger.info(
            "Created %d Rechtspraak judgment nodes.",
            len(judgments_by_ecli),
        )

        return {
            "judgments_by_ecli": judgments_by_ecli,
            "strafrecht_nodes": strafrecht_nodes,
        }

    def build_edges(
        self,
        raw: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> int:
        """Link strafrecht judgments to the topic node via semantic edges."""
        content_records = raw.get("content", [])
        logger.debug(
            "RechtspraakNormalizePipeline currently holds %d content records.",
            len(content_records),
        )

        edge_count = 0
        topic_node = self._get_domain_topic_node()
        if topic_node:
            for node in normalized.get("strafrecht_nodes", []):
                if not node.id:
                    continue
                if self._ensure_related_topic_edge(
                    node=node,
                    topic_node=topic_node,
                    source="rechtspraak-normalize",
                ):
                    edge_count += 1
        else:
            logger.debug(
                "No strafrecht topic found; skipping related-topic edges.")

        logger.info(
            "Rechtspraak normalization created %d semantic edges.",
            edge_count,
        )
        return edge_count

    def _is_strafrecht_judgment(
        self,
        payload_text: str | None,
        meta: dict[str, Any],
        ecli: str,
    ) -> bool:
        config = self._load_domain_config()
        filters = config.get("filters", {}).get("rechtspraak", {})
        rechtsgebieden: list[str] = filters.get("rechtsgebieden", [])
        ecli_prefixes: list[str] = filters.get("ecli_prefixes", [])
        search_terms: list[str] = filters.get("search_terms", [])

        if ecli:
            seed_eclis = config.get("seed_examples", {}).get(
                "rechtspraak_eclis", [])
            if ecli in seed_eclis:
                return True
            for prefix in ecli_prefixes:
                if ecli.startswith(prefix):
                    return True

        if payload_text and self._text_contains_keywords(payload_text, search_terms):
            return True

        rechtsgebied_value = meta.get("rechtsgebied")
        if rechtsgebied_value:
            area_values: list[str] = []
            if isinstance(rechtsgebied_value, str):
                area_values = [
                    item.strip()
                    for item in rechtsgebied_value.split(",")
                    if item.strip()
                ]
            elif isinstance(rechtsgebied_value, list):
                area_values = [str(item).strip()
                               for item in rechtsgebied_value if item]
            for area in area_values:
                for candidate in rechtsgebieden:
                    if area.lower() == candidate.lower():
                        return True

        return False
