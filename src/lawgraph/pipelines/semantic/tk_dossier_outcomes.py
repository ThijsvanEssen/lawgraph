"""Derive whether each dossier is closed, how it ended and when, from the graph.

The Tweede Kamer does not say it: ``Kamerstukdossier.Afgesloten`` is false on every dossier,
also on those whose law was published years ago, and the record has no closing date. What
the graph holds does say it (see :func:`~lawgraph.core.dossier_stages.derive_outcome`): the
publication of the law (``LEGISLATED_IN``, written by ``semantic bwb-amendments``), the
letter that withdraws the bill, and the vote on the bill itself.

Runs over every dossier, since a law published today closes a dossier whose own record did
not change, and writes only the dossiers whose answer changed: ``closed``, ``outcome``,
``closed_on`` and, as a closed dossier is ``afgehandeld``, ``current_stage`` and
``stages_present``.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core.batching import chunked
from lawgraph.core.dossier_stages import (
    BILL_CASE_KINDS,
    DossierOutcome,
    derive_outcome,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import NodeType, PipelineResult
from lawgraph.db.queries import semantic as semantic_queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

CLOSED_STAGE = "afgehandeld"

# Dossiers whose signals are read in one query (three edge walks each).
_CHUNK = 500


def outcome_props(stored: dict[str, Any], outcome: DossierOutcome) -> dict[str, Any]:
    """The props that record *outcome* on a dossier that holds *stored* now.

    A closed dossier is at stage ``afgehandeld``; a dossier that is open again (the
    evidence that closed it is gone) falls back to the last stage before it.
    """
    stages = [s for s in stored.get("stages_present") or [] if s != CLOSED_STAGE]
    props: dict[str, Any] = {
        "closed": outcome.closed,
        "outcome": outcome.outcome,
        "closed_on": outcome.closed_on,
    }
    if outcome.closed:
        props["current_stage"] = CLOSED_STAGE
        props["stages_present"] = [*stages, CLOSED_STAGE]
    elif stored.get("current_stage") == CLOSED_STAGE:
        props["current_stage"] = stages[-1] if stages else "onbekend"
        props["stages_present"] = stages
    return props


class TKDossierOutcomesSemanticPipeline(SemanticPipelineBase):
    """Write ``closed``, ``outcome`` and ``closed_on`` on every dossier."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        ids = list(semantic_queries.dossier_ids(self.store))
        closed = 0
        for chunk in self._track(chunked(ids, _CHUNK), "dossier chunks"):
            changed = []
            rows = semantic_queries.dossier_outcome_signals(
                self.store, chunk, bill_case_kinds=list(BILL_CASE_KINDS)
            )
            for row in rows:
                outcome = derive_outcome(
                    row.get("publications") or [],
                    row.get("letters") or [],
                    row.get("bill_votes") or [],
                )
                closed += outcome.closed
                stored = row.get("props") or {}
                props = outcome_props(stored, outcome)
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
