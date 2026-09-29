"""Derive whether each dossier is closed, how it ended and when, from the graph.

The Tweede Kamer does not say it: ``Kamerstukdossier.Afgesloten`` is false on every dossier,
also on those whose law was published years ago, and the record has no closing date. What
the graph holds does say it (see :func:`~lawgraph.core.dossier_stages.derive_outcome`): the
publication of the law (``LEGISLATED_IN``, written by ``semantic bwb-amendments``) and the
vote on the bill itself. Next to it: the last decision of the Kamer on the bill
(``tk_decision``, its ``BesluitSoort``), a hamerstuk too.

Runs over every dossier, since a law published today closes a dossier whose own record did
not change, and writes only the dossiers whose ``closed``, ``outcome``, ``closed_on`` or
``tk_decision`` changed.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core.batching import chunked
from lawgraph.core.dossier_stages import (
    LEGISLATIVE_KINDS,
    derive_outcome,
    outcome_props,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import NodeType, PipelineResult
from lawgraph.db.queries import semantic as semantic_queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Dossiers whose signals are read in one query (two edge walks each).
_CHUNK = 500


class TKDossierOutcomesSemanticPipeline(SemanticPipelineBase):
    """Write ``closed``, ``outcome``, ``closed_on`` and ``tk_decision`` on every
    dossier."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        ids = list(semantic_queries.dossier_ids(self.store))
        closed = 0
        for chunk in self._track(chunked(ids, _CHUNK), "dossier chunks"):
            rows = semantic_queries.dossier_outcome_signals(
                self.store, chunk, bill_case_kinds=list(LEGISLATIVE_KINDS)
            )
            changed: list[dict[str, Any]] = []
            for row in rows:
                outcome = derive_outcome(
                    row.get("publications") or [], row.get("bill_decisions") or []
                )
                closed += outcome.closed
                props = outcome_props(outcome)
                stored = row.get("props") or {}
                if any(stored.get(name) != value for name, value in props.items()):
                    changed.append(
                        {
                            "_key": row["key"],
                            "type": NodeType.DOSSIER.value,
                            "labels": [],
                            "props": props,
                        }
                    )
            if changed:
                self.store.bulk_insert_or_update_nodes(COLLECTION_DOSSIERS, changed)
            result.updated += len(changed)
            result.unchanged += len(chunk) - len(changed)
        logger.info(
            "%d of %d dossiers are closed; %d changed.",
            closed,
            len(ids),
            result.updated,
        )
        return result
