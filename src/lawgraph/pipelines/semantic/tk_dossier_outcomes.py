"""Derive whether each dossier is closed, how it ended and when, from the graph.

The Tweede Kamer does not say it: ``Kamerstukdossier.Afgesloten`` is false on every dossier,
also on those whose law was published years ago, and the record has no closing date. What
the graph holds does say it (see :func:`~lawgraph.core.dossier_stages.derive_outcome`): the
publication of the law (``LEGISLATED_IN``, written by ``semantic bwb-amendments``), the
letter that withdraws the bill, and the vote on the bill itself.

Runs over every dossier, since a law published today closes a dossier whose own record did
not change, and writes only the dossiers whose outcome changed: ``closed``, ``outcome``,
``closed_on`` and their stages recomputed for it (``current_stage``, ``stages_present``,
``stages_complete``, ``stages_missing``; a closed dossier is ``afgehandeld``), from the same
signals and rules as ``normalize tk-dossiers``.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_DOSSIERS
from lawgraph.core.batching import chunked
from lawgraph.core.dossier_stages import (
    BILL_CASE_KINDS,
    DossierOutcome,
    derive_outcome,
    dossier_stages,
    outcome_props,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import NodeType, PipelineResult
from lawgraph.db.queries import normalize as normalize_queries
from lawgraph.db.queries import semantic as semantic_queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Dossiers whose signals are read in one query (three edge walks each).
_CHUNK = 500

_OUTCOME_PROPS = ("closed", "outcome", "closed_on")


def _outcome_changed(stored: dict[str, Any], outcome: DossierOutcome) -> bool:
    found = (outcome.closed, outcome.outcome, outcome.closed_on)
    return tuple(stored.get(name) for name in _OUTCOME_PROPS) != found


class TKDossierOutcomesSemanticPipeline(SemanticPipelineBase):
    """Write ``closed``, ``outcome`` and ``closed_on`` on every dossier."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        ids = list(semantic_queries.dossier_ids(self.store))
        closed = 0
        for chunk in self._track(chunked(ids, _CHUNK), "dossier chunks"):
            rows = semantic_queries.dossier_outcome_signals(
                self.store, chunk, bill_case_kinds=list(BILL_CASE_KINDS)
            )
            pending: dict[str, tuple[dict[str, Any], DossierOutcome]] = {}
            for row in rows:
                outcome = derive_outcome(
                    row.get("publications") or [],
                    row.get("letters") or [],
                    row.get("bill_votes") or [],
                )
                closed += outcome.closed
                stored = row.get("props") or {}
                if _outcome_changed(stored, outcome):
                    pending[f"{COLLECTION_DOSSIERS}/{row['key']}"] = (stored, outcome)
            changed = self._with_stages(pending)
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

    def _with_stages(
        self, pending: dict[str, tuple[dict[str, Any], DossierOutcome]]
    ) -> list[dict[str, Any]]:
        """The node updates for the dossiers whose outcome changed, their stages
        recomputed for the new outcome."""
        if not pending:
            return []
        changed = []
        for row in normalize_queries.dossier_signals(self.store, list(pending)):
            dossier_id = row["dossier_id"]
            stored, outcome = pending[dossier_id]
            stages = dossier_stages(
                stored.get("track_kind"),
                row.get("docs") or [],
                row.get("activities") or [],
                row.get("decisions") or [],
                list(row.get("case_kinds") or []),
                closed=outcome.closed,
                outcome=outcome.outcome,
            )
            changed.append(
                {
                    "_key": dossier_id.split("/", 1)[1],
                    "type": NodeType.DOSSIER.value,
                    "labels": [],
                    "props": outcome_props(outcome, stages),
                }
            )
        return changed
