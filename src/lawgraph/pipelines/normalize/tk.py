"""Normalize TK Zaak records into cases.

Every Zaak the Tweede Kamer handles becomes a Case — no filtering by kind;
what a case is about is the ``kind`` the source gives it. The documents of a
case are written by ``tk_cases``, which also draws the PART_OF edges to the
cases and dossiers they name.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from typing import Any

from lawgraph.config.constants import COLLECTION_CASES, RAW_KIND_TK_ZAAK, SOURCE_TK
from lawgraph.core import tk_records
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db import NodeWriter
from lawgraph.pipelines.normalize._tk_deleted import Deleted
from lawgraph.pipelines.normalize.base import NormalizePipelineBase

logger = get_logger(__name__)


class TKNormalizePipeline(NormalizePipelineBase):
    """Turn raw TK Zaak records into cases."""

    def fetch_raw(
        self,
        *,
        since: dt.datetime | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Stream the TK Zaak raw records to normalize."""
        return self._iter_raw_sources(
            source=SOURCE_TK, kinds=[RAW_KIND_TK_ZAAK], since=since, batch_size=1000
        )

    def normalize_nodes(
        self,
        raw: Iterable[dict[str, Any]],
        result: PipelineResult,
    ) -> int:
        """Write the case node of each raw record as it is read; none is kept."""
        return self._normalize_cases(raw)

    def build_edges(
        self,
        raw: Iterable[dict[str, Any]],
        normalized: int,
    ) -> None:
        """None: a case is linked to its dossiers once the dossiers exist."""

    def _normalize_cases(self, raw_records: Iterable[dict[str, Any]]) -> int:
        """Case nodes, keyed by the Zaak identifier documents refer to; the node of a Zaak
        the Kamer deleted is removed."""
        writer = NodeWriter(self.store)
        deleted = Deleted(COLLECTION_CASES)
        for raw in raw_records:
            payload = self._payload_json(raw)
            if deleted(payload):
                continue
            parsed = tk_records.case(payload)
            if parsed is None:
                logger.warning(
                    "Skipping a TK Zaak without an identifier (_key=%s).",
                    raw.get("_key"),
                )
                continue
            key, props = parsed
            writer.add(
                Node(
                    collection=COLLECTION_CASES,
                    type=NodeType.CASE,
                    key=key,
                    labels=["TK"],
                    props=props,
                )
            )

        writer.flush()
        removed = deleted.remove(self.store)
        logger.info(
            "Normalized %d TK cases; removed %d the Kamer deleted.",
            writer.written,
            removed,
        )
        return writer.written
