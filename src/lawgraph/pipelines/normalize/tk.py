"""Normalize TK Zaak records into cases.

Every Zaak the Tweede Kamer handles becomes a Case — no filtering by kind;
what a case is about is the ``kind`` the source gives it. The documents of a
case are written by ``tk_cases``, which also draws the PART_OF edges to the
cases and dossiers they name.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_CASES,
    RAW_KIND_TK_ZAAK,
    SOURCE_TK,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.tk_records.cases import case
from lawgraph.db import NodeWriter
from lawgraph.pipelines.normalize._tk_deleted import DELETED, Deleted
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)


class TKNormalizePipeline(NormalizePipelineBase[Records]):
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

    def write(self, raw: Records, result: PipelineResult) -> None:
        """Case nodes, keyed by the Zaak identifier documents refer to, written as the
        records are read; the node of a Zaak the Kamer deleted is removed. A case is linked
        to its dossiers once the dossiers exist (``normalize tk-dossiers``)."""
        writer = NodeWriter(self.store)
        deleted = Deleted(COLLECTION_CASES)
        for record in raw:
            payload = self._payload_json(record)
            if deleted(payload):
                self.progress.skip(DELETED, payload.get("Id"))
                continue
            parsed = case(payload)
            if parsed is None:
                self.progress.skip("no Zaak identifier", record.get("_key"))
                continue
            key, props = parsed
            writer.add(
                Node(
                    collection=COLLECTION_CASES,
                    key=key,
                    labels=[CHAMBER_TK],
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
