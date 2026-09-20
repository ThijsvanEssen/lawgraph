"""Normalize pipeline for ECHR HUDOC judgments."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    MAX_TITLE_CHARS,
    RAW_KIND_ECHR_JUDGMENT,
    SOURCE_ECHR,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult, make_node_key
from lawgraph.core.time import iso_date as _iso_date
from lawgraph.db import NodeWriter
from lawgraph.db.store import ArangoStore
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)


class ECHRNormalizePipeline(NormalizePipelineBase):
    """Normalize ECHR HUDOC judgment JSON into Judgment nodes."""

    def __init__(self, *, store: ArangoStore) -> None:
        super().__init__(store=store)

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_ECHR,
            kinds=[RAW_KIND_ECHR_JUDGMENT],
            since=since,
            batch_size=1000,
        )

    def normalize_nodes(
        self, raw: Iterable[dict[str, Any]], result: PipelineResult
    ) -> int:
        count = 0
        english: dict[str, bool] = {}
        writer = NodeWriter(self.store)

        for record in raw:
            payload = self._payload_json(record)
            if not payload or not isinstance(payload, dict):
                result.skipped += 1
                continue

            item_id = str(payload.get("itemid") or record.get("external_id") or "")
            if not item_id:
                result.skipped += 1
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
            display_name = (
                docname[:MAX_TITLE_CHARS] if docname else f"ECHR {appno or item_id}"
            )

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

            # By its ECLI when it has one: that is what a Dutch judgment cites, so the stub
            # of a cited judgment and the judgment itself are the same node. HUDOC holds a
            # judgment once per language; the English record is the one that stays.
            ecli = str(payload.get("ecli") or "").strip().upper()
            if ecli:
                props["ecli"] = ecli
                if english.get(ecli) and payload.get("languageisocode") != "ENG":
                    result.skipped += 1
                    continue
                english[ecli] = payload.get("languageisocode") == "ENG"
            key = make_node_key(ecli) if ecli else make_node_key("echr", item_id)
            node = Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=key,
                labels=["ECHR"],
                props=props,
            )
            writer.add(node)
            count += 1

        writer.flush()

        logger.info("ECHR normalize: %d judgments processed.", count)
        return count

    def build_edges(self, raw: Iterable[dict[str, Any]], normalized: int) -> None:
        """No structural edges: citations are linked by the semantic pipelines."""
