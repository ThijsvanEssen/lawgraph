"""Semantic pipeline: ``SAME_AS`` between the language versions of one ECHR decision.

HUDOC holds a decision once per language. A decision with an ECLI is one node (normalize keys
it by the ECLI and keeps the English record); one without is a node per HUDOC item, so its
English and French versions stand side by side, unlinked. Two such nodes are one decision
when they have the same application numbers (``appno``) and the same date: the other
documents of a case (the decision on admissibility, the judgment of the Chamber, that of the
Grand Chamber) have the case's numbers too, but another date.

Of each decision the English version is kept, else the French, else the one of the lowest
key; every other version is ``SAME_AS`` it and names its HUDOC item id in ``props.same_as``,
by which ``/api/judgments/{id}`` finds it. The lists show the decision once, as they do the
publications the Rechtspraak replaced (``rechtspraak-duplicates``). Derived in full each run.
"""

from __future__ import annotations

import re
from typing import Any

from lawgraph.config.constants import COLLECTION_JUDGMENTS, RELATION_SAME_AS
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
from lawgraph.db.store import edge_key

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "echr-version-linker"
BASIS = "appno_and_date"

# The language of the version that is kept, best first (as normalize keeps a decision with
# an ECLI).
_LANGUAGES = ("ENG", "FRE")
# The separators of several application numbers in one field: "7481/23;7493/23".
_APPNO_SEPARATORS = re.compile(r"[;,\s]+")


def decision_of(row: dict[str, Any]) -> tuple[tuple[str, ...], str] | None:
    """``(application numbers, date)`` that the versions of one decision share; None
    without either."""
    numbers = tuple(
        sorted({n for n in _APPNO_SEPARATORS.split(row.get("appno") or "") if n})
    )
    date = row.get("date")
    return (numbers, str(date)) if numbers and date else None


def versions_kept(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Node id of a version that is not kept -> the row of the version kept, for every
    decision of two versions or more."""
    decisions: dict[tuple[tuple[str, ...], str], list[dict[str, Any]]] = {}
    for row in rows:
        if (decision := decision_of(row)) is not None:
            decisions.setdefault(decision, []).append(row)
    kept: dict[str, dict[str, Any]] = {}
    for versions in decisions.values():
        if len(versions) < 2:
            continue
        best = min(versions, key=_rank)
        kept.update({row["id"]: best for row in versions if row is not best})
    return kept


def _rank(row: dict[str, Any]) -> tuple[int, str]:
    language = row.get("language")
    order = _LANGUAGES.index(language) if language in _LANGUAGES else len(_LANGUAGES)
    return order, str(row["key"])


class ECHRVersionsSemanticPipeline(SemanticPipelineBase):
    """Create SAME_AS from each language version of an ECHR decision to the one kept."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        rows = list(
            self._track(semantic_rechtspraak.echr_versions(self.store), "decisions")
        )
        kept = versions_kept(rows)
        self._write_same_as(rows, kept, result)
        written: dict[str, set[str]] = {}
        edges = EdgeWriter(self.store, what=None)
        for row in rows:
            best = kept.get(row["id"])
            if best is not None and edges.add(
                row["id"],
                best["id"],
                RELATION_SAME_AS,
                source=SEMANTIC_SOURCE,
                confidence=1.0,
                meta={"basis": BASIS},
            ):
                written.setdefault(row["id"], set()).add(
                    edge_key(row["id"], RELATION_SAME_AS, best["id"])
                )
        edges.flush_into(result)
        removed = semantic_edges.remove_edges_from(
            self.store,
            RELATION_SAME_AS,
            SEMANTIC_SOURCE,
            sorted(row["id"] for row in rows),
            written,
        )
        logger.info(
            "%d ECHR versions are another version of a decision kept; removed %d "
            "SAME_AS no longer derived.",
            len(kept),
            removed,
        )
        return result

    def _write_same_as(
        self,
        rows: list[dict[str, Any]],
        kept: dict[str, dict[str, Any]],
        result: PipelineResult,
    ) -> None:
        """``props.same_as``: the item id of the version kept, null for one kept or alone;
        only those that change are written."""
        with NodeWriter(self.store) as writer:
            for row in rows:
                best = kept.get(row["id"])
                same_as = best["item_id"] if best is not None else None
                if row.get("same_as") == same_as:
                    result.unchanged += 1
                    continue
                writer.add(
                    Node(
                        collection=COLLECTION_JUDGMENTS,
                        type=NodeType.JUDGMENT,
                        key=row["key"],
                        props={"same_as": same_as},
                    )
                )
                result.updated += 1
