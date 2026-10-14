"""Semantic pipeline: ``SAME_AS`` between the publications of one decision.

The Rechtspraak published many old arresten twice or more (an LJN of the first publication
and one of a later, complete one); the metadata of the old publication names the one that
replaces it in ``dcterms:isReplacedBy`` ("Vervangen door"), kept as ``props.replaced_by``.
That, and not the court, date and case number (a publication may be dated or numbered
otherwise, or made under the court of the hearing), is the signal.

A publication whose replacing one is loaded is ``SAME_AS`` it: the edge runs from the
publication replaced to the one kept, following a replaced one to the last that is loaded,
and ``props.same_as`` names the one kept. The lists show the decision once, by the one
kept, and count the citations of all its publications there (``graph-list-stats``). One
whose replacing publication is not loaded stands alone. Derived in full each run.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import COLLECTION_JUDGMENTS, RELATION_SAME_AS
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.provenance import BASIS_REPLACED_BY
from lawgraph.db import EdgeWriter, NodeWriter
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "rechtspraak-duplicate-linker"


def kept_publications(replaced_by: dict[str, str], loaded: set[str]) -> dict[str, str]:
    """ECLI of a replaced publication -> the loaded publication that is kept: the one that
    replaces it, or the one that replaces that in turn, as far as they are loaded; of
    publications that replace each other in a circle, the lowest ECLI. A publication whose
    replacing one is not loaded is in none."""
    kept: dict[str, str] = {}
    for ecli in replaced_by:
        path = [ecli]
        while (following := replaced_by.get(path[-1])) in loaded:
            if following in path:  # a circle: its lowest ECLI is kept
                path.append(min(path[path.index(following) :]))
                break
            path.append(following)
        if path[-1] != ecli:
            kept[ecli] = path[-1]
    return kept


class RechtspraakDuplicatesSemanticPipeline(SemanticPipelineBase):
    """Write ``SAME_AS`` and ``props.same_as`` from a replaced publication to the one kept."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        rows = [
            row
            for row in self._track(
                semantic_rechtspraak.replaced_judgments(self.store), "judgments"
            )
            if row.get("ecli")
        ]
        replaced_by = {
            row["ecli"].upper(): row["replaced_by"].upper()
            for row in rows
            if row.get("replaced_by")
        }
        ids = {
            str(row["ecli"]).upper(): row["id"]
            for row in semantic_rechtspraak.loaded_judgment_ids(
                self.store, sorted(set(replaced_by.values()))
            )
        }
        kept = kept_publications(replaced_by, set(ids))
        self._write_same_as(rows, kept, result)
        edges = EdgeWriter(self.store, what=None, remembers=True)
        for row in rows:
            edges.add(
                row["id"],
                ids.get(kept.get(row["ecli"].upper(), "")),
                RELATION_SAME_AS,
                source=SEMANTIC_SOURCE,
                confidence=1.0,
                meta={"basis": BASIS_REPLACED_BY},
            )
        edges.flush_into(result)
        removed = edges.remove_stale(
            RELATION_SAME_AS, SEMANTIC_SOURCE, sorted(row["id"] for row in rows)
        )
        logger.info(
            "%d publication(s) replaced by one that is loaded, of %d replaced; "
            "removed %d SAME_AS no longer derived.",
            len(kept),
            len(replaced_by),
            removed,
        )
        return result

    def _write_same_as(
        self, rows: list[dict[str, Any]], kept: dict[str, str], result: PipelineResult
    ) -> None:
        with NodeWriter(self.store) as writer:
            for row in rows:
                same_as = kept.get(row["ecli"].upper())
                if row.get("same_as") == same_as:
                    result.unchanged += 1
                    continue
                writer.add(
                    Node(
                        collection=COLLECTION_JUDGMENTS,
                        key=row["key"],
                        props={"same_as": same_as},
                    )
                )
                result.updated += 1
