from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.settings import (
    COLLECTION_INSTRUMENTS,
    RAW_SOURCE_KINDS,
    SOURCE_EURLEx,
)
from lawgraph.db import ArangoStore
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.normalize.base import NormalizePipeline
from lawgraph.utils.display import make_display_name


logger = get_logger(__name__)


class EUNormalizePipeline(NormalizePipeline):
    """Normalization pipeline that turns EUR-Lex raw dumps into instrument nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store, domain_profile="strafrecht")

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Load EUR-Lex CELEX html dumps from raw_sources."""
        kinds = list(RAW_SOURCE_KINDS[SOURCE_EURLEx])
        records = self._query_raw_sources(
            source=SOURCE_EURLEx,
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
        """Normalize EUR-Lex raw HTML into instrument nodes, tagging strafrecht nodes."""
        instruments_by_celex: dict[str, Node] = {}
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

            props: dict[str, Any] = {
                "celex": celex,
                "raw_html": payload_text,
            }
            if lang:
                props["lang"] = lang
            if meta:
                props["meta"] = meta

            is_strafrecht = self._is_strafrecht_eu_instrument(
                celex, payload_text)
            labels = ["EU"]
            if is_strafrecht:
                labels.append("Strafrecht")
                props["strafrecht_profile"] = "eu"

            props["display_name"] = make_display_name(NodeType.INSTRUMENT, props)
            key = make_node_key(celex)

            node = Node(
                collection=COLLECTION_INSTRUMENTS,
                type=NodeType.INSTRUMENT,
                key=key,
                labels=labels,
                props=props,
            )

            inserted_node = self.store.insert_or_update(node)
            instruments_by_celex[celex] = inserted_node
            if is_strafrecht:
                strafrecht_nodes.append(inserted_node)

        logger.info(
            "Created %d EUR-Lex instrument nodes.",
            len(instruments_by_celex),
        )

        return {
            "instruments_by_celex": instruments_by_celex,
            "strafrecht_nodes": strafrecht_nodes,
        }

    def build_edges(
        self,
        raw: dict[str, list[dict[str, Any]]],
        normalized: dict[str, Any],
    ) -> int:
        """Attach strafrecht nodes to the configured topic via semantic edges."""
        celex_records = raw.get("celex_html", [])
        logger.debug(
            "EUNormalizePipeline currently holds %d celex html records.",
            len(celex_records),
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
                    source="eu-normalize",
                ):
                    edge_count += 1
        else:
            logger.debug(
                "No strafrecht topic found; skipping related-topic edges.")

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

        if payload_text and self._text_contains_keywords(payload_text, subject_keywords):
            return True

        return False
