"""Normalize pipeline for ECHR HUDOC judgments."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.settings import (
    COLLECTION_JUDGMENTS,
    RAW_KIND_ECHR_JUDGMENT,
    SOURCE_ECHR,
)
from lawgraph.logging import get_logger
from lawgraph.models import Node, NodeType, make_node_key
from lawgraph.pipelines.normalize.base import NormalizePipeline

logger = get_logger(__name__)


def _iso_date(val: Any) -> str | None:
    if not val:
        return None
    s = str(val)
    if "T" in s:
        return s[:10]
    return s[:10] if len(s) >= 10 else s


class EchrNormalizePipeline(NormalizePipeline):
    """Normalize ECHR HUDOC judgment JSON into Judgment nodes."""

    def __init__(self, *, store: Any) -> None:
        super().__init__(store=store)

    def fetch_raw(self, *, since: dt.datetime | None = None) -> list[dict[str, Any]]:
        rows = self._query_raw_sources(
            source=SOURCE_ECHR,
            kinds=[RAW_KIND_ECHR_JUDGMENT],
            since=since,
        )
        logger.info("Loaded %d ECHR raw_sources.", len(rows))
        return rows

    def normalize_nodes(self, raw: list[dict[str, Any]]) -> dict[str, Node]:
        nodes: dict[str, Node] = {}

        for record in raw:
            payload = self._payload_json(record)
            if not payload or not isinstance(payload, dict):
                self._result.skipped += 1
                continue

            item_id = str(payload.get("itemid") or record.get("external_id") or "")
            if not item_id:
                self._result.skipped += 1
                continue

            appno = payload.get("appno") or ""
            docname = payload.get("docname") or f"ECHR {item_id}"
            kpdate = _iso_date(payload.get("kpdate"))
            respondent = payload.get("respondent") or ""
            importance = payload.get("importance")
            articles = payload.get("article") or []
            conclusion = payload.get("conclusion") or ""
            originating_body = payload.get("originatingbody") or ""

            # Construct a human-readable display name
            display_name = docname[:200] if docname else f"ECHR {appno or item_id}"

            props: dict[str, Any] = {
                "source": SOURCE_ECHR,
                "external_id": item_id,
                "appno": appno,
                "title": docname,
                "display_name": display_name,
                "date": kpdate,
                "respondent": respondent,
                "originating_body": originating_body,
                "articles": articles if isinstance(articles, list) else [articles],
                "conclusion": conclusion,
            }
            if importance is not None:
                try:
                    props["importance"] = int(importance)
                except (TypeError, ValueError):
                    props["importance"] = importance

            key = make_node_key("echr", item_id)
            node = Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=key,
                labels=["ECHR"],
                props=props,
            )
            node = self.store.insert_or_update(node)
            nodes[item_id] = node
            self._result.created += 1

        logger.info("ECHR normalize: %d judgments processed.", len(nodes))
        return nodes

    def build_edges(
        self, raw: list[dict[str, Any]], normalized: dict[str, Node]
    ) -> int:
        return 0
