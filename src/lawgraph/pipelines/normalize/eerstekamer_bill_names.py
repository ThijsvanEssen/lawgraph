"""Normalize the names the Eerste Kamer gives its bills onto their dossiers.

Every name (``ek-bill-name-json``) whose dossier the graph holds becomes ``ek_name`` on that
dossier, as the list gives it. A bill whose dossier the graph does not hold is skipped.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOSSIERS,
    RAW_KIND_EERSTEKAMER_BILL_NAME,
    SOURCE_EERSTEKAMER,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.core.raw_records import payload_json
from lawgraph.db import NodeWriter
from lawgraph.pipelines.normalize.base import NormalizePipelineBase, Records

logger = get_logger(__name__)


class EerstekamerBillNamesNormalizePipeline(NormalizePipelineBase[Records]):
    """``ek_name`` on the dossier of every bill the Eerste Kamer names."""

    def fetch_raw(
        self, *, since: dt.datetime | None = None
    ) -> Iterator[dict[str, Any]]:
        return self._iter_raw_sources(
            source=SOURCE_EERSTEKAMER,
            kinds=[RAW_KIND_EERSTEKAMER_BILL_NAME],
            since=since,
        )

    def write(self, raw: Records, result: PipelineResult) -> None:
        """``ek_name`` on the dossiers. No edges: a name adds to its dossier only."""
        found: dict[str, str] = {}
        for record in raw:
            bill = payload_json(record) or {}
            found[make_node_key(str(bill.get("label")))] = str(bill.get("name"))
        known = self.store.existing_keys(COLLECTION_DOSSIERS, set(found))
        for key in sorted(set(found) - known):
            self.progress.skip("dossier not in the graph", key)
        with NodeWriter(self.store) as writer:
            writer.add_all(
                Node(
                    collection=COLLECTION_DOSSIERS,
                    key=key,
                    labels=[],
                    props={"ek_name": found[key]},
                )
                for key in sorted(known)
            )
        logger.info(
            "Eerste Kamer: %d names of bills, %d on a dossier the graph holds.",
            len(found),
            len(known),
        )
