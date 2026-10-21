"""``lawgraph semantic tk-motion-kinds``: which motions are of censure or of no confidence.

Per motion and per decision on one, ``motion_kind`` from its subject (``core/motion_kinds.py``:
``censure``, ``no_confidence``, else null), written only where it differs from what is kept (of
a motion its light row, ``lg_document_light``, which the trigger on ``documents`` keeps with it).
With ``--since`` only those dated from then on (the poll and the daily run); without it every
one (after the rule changed).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import COLLECTION_DECISIONS, COLLECTION_DOCUMENTS
from lawgraph.core.batching import chunked
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.motion_kinds import motion_kind
from lawgraph.core.time import iso_day
from lawgraph.db.queries.motion_kinds import motion_subjects

from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Nodes written in one statement.
_BATCH = 1_000

_TYPES = {COLLECTION_DOCUMENTS: "document", COLLECTION_DECISIONS: "decision"}


class TKMotionKindsSemanticPipeline(SemanticPipelineBase):
    """Write ``motion_kind`` on every motion and decision on one whose kind changed."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        for collection, node_type in _TYPES.items():
            changed: list[dict[str, Any]] = []
            rows = motion_subjects(self.store, collection, iso_day(since))
            for row in self._track(rows, collection, total=len(rows)):
                kind = motion_kind(row["subject"])
                if kind == row["kept"]:
                    result.unchanged += 1
                    continue
                changed.append(
                    {
                        "key": row["key"],
                        "type": node_type,
                        "labels": [],
                        "props": {"motion_kind": kind},
                    }
                )
            for batch in chunked(changed, _BATCH):
                self.store.bulk_insert_or_update_nodes(collection, batch)
            result.updated += len(changed)
            logger.info(
                "Motion kinds of %d %s: %d changed.",
                len(rows),
                collection,
                len(changed),
            )
        return result
