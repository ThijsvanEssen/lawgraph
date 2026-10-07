"""Derive whether each dossier is closed, how it ended and when, from the graph.

The Tweede Kamer does not say it: ``Kamerstukdossier.Afgesloten`` is false on every dossier,
also on those whose law was published years ago, and the record has no closing date. What
the graph holds does say it (see :func:`~lawgraph.core.dossier_stages.derive_outcome`): the
publication of the law (``LEGISLATED_IN``, written by ``semantic bwb-amendments``) and the
vote on the bill itself in either chamber. Next to it: the last decision of the Tweede Kamer
on the bill (``tk_decision``, its ``BesluitSoort``), a hamerstuk too, and its outcome in the
Eerste Kamer (``ek_outcome``, :func:`~lawgraph.core.dossier_stages.ek_outcome`), whose vote
gets ``bill_decision``.

Runs over every dossier, since a law published today closes a dossier whose own record did
not change, and writes only the dossiers whose ``closed``, ``outcome``, ``closed_on``,
``tk_decision`` or ``ek_outcome`` changed; with ``--touched-since`` over the dossiers a poll
touched since then (``semantic/_touched.py``).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import COLLECTION_DECISIONS, COLLECTION_DOSSIERS
from lawgraph.core.batching import chunked
from lawgraph.core.dossier_stages import (
    LEGISLATIVE_KINDS,
    derive_outcome,
    ek_outcome,
    outcome_props,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import NodeType, PipelineResult
from lawgraph.db.queries.semantic import tk as semantic_tk

from . import _touched as touched
from .base import SemanticPipelineBase

logger = get_logger(__name__)

# Dossiers whose signals are read in one query (two edge walks each).
_CHUNK = 500


class TKDossierOutcomesSemanticPipeline(SemanticPipelineBase):
    """Write ``closed``, ``outcome``, ``closed_on``, ``tk_decision`` and ``ek_outcome`` on
    every dossier, and ``bill_decision`` on the votes of the Eerste Kamer about it."""

    def run(self, *, touched_since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        ids = (
            list(semantic_tk.dossier_ids(self.store))
            if touched_since is None
            else touched.touched_dossiers(self.store, touched_since)
        )
        closed = 0
        for chunk in self._track(chunked(ids, _CHUNK), "dossier chunks"):
            rows = semantic_tk.dossier_outcome_signals(
                self.store, chunk, bill_case_kinds=list(LEGISLATIVE_KINDS)
            )
            changed: list[dict[str, Any]] = []
            votes: list[dict[str, Any]] = []
            for row in rows:
                stored = row.get("props") or {}
                ek = ek_outcome(row.get("ek_votes") or [], stored.get("ek_rejected"))
                outcome = derive_outcome(
                    row.get("publications") or [], row.get("bill_decisions") or [], ek
                )
                closed += outcome.closed
                props = outcome_props(outcome)
                if any(stored.get(name) != value for name, value in props.items()):
                    changed.append(_node(row["key"], NodeType.DOSSIER, props))
                votes += _bill_decisions(
                    row.get("ek_votes") or [], ek, stored.get("kind")
                )
            if changed:
                self.store.bulk_insert_or_update_nodes(COLLECTION_DOSSIERS, changed)
            if votes:
                self.store.bulk_insert_or_update_nodes(COLLECTION_DECISIONS, votes)
            result.updated += len(changed)
            result.unchanged += len(chunk) - len(changed)
        logger.info(
            "%d of %d dossiers are closed; %d changed.",
            closed,
            len(ids),
            result.updated,
        )
        return result


def _node(key: str, node_type: NodeType, props: dict[str, Any]) -> dict[str, Any]:
    return {"_key": key, "type": node_type.value, "labels": [], "props": props}


def _bill_decisions(
    votes: list[dict[str, Any]], ek: dict[str, Any] | None, kind: str | None
) -> list[dict[str, Any]]:
    """The votes of the Eerste Kamer whose ``bill_decision`` or ``kind`` changes:
    ``bill_decision`` true for the one that decided the bill, false for the others (a
    motion); ``kind`` the kind of the dossier (its ``Zaak.Soort``: the list of the Eerste
    Kamer names none) for the one that decided the bill, none for the others."""
    chosen = (ek or {}).get("decision")
    changed = []
    for vote in votes:
        decided = vote["id"] == chosen
        props = {"bill_decision": decided, "kind": kind if decided else None}
        if any(vote.get(name) != value for name, value in props.items()):
            changed.append(_node(vote["id"].split("/", 1)[1], NodeType.DECISION, props))
    return changed
