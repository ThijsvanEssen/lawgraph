"""Semantic pipeline: ADVISES_ON from the conclusion of an advocate-general to its judgment.

The Rechtspraak metadata ties a conclusion and its judgment by a ``dcterms:relation`` of
``psi:type`` conclusie, written on either side (``props.conclusion_eclis``). A conclusion
that neither side ties is linked by the case number it shares with a judgment of the court
it advises (``core.judgments.CONCLUSION_BENCH``: the Parket bij de Hoge Raad advises the
Hoge Raad).
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_ADVISES_ON
from lawgraph.core.judgments import CONCLUSION_BENCH
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import semantic as semantic_queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "rechtspraak-conclusion-linker"
BASIS_FORMAL = "formal_relation"
BASIS_CASE_NUMBER = "case_number"
CONFIDENCE = {BASIS_FORMAL: 1.0, BASIS_CASE_NUMBER: 0.9}

Pair = tuple[str, str]  # (conclusion ECLI, judgment ECLI)


def formal_pairs(rows: list[dict[str, Any]]) -> set[Pair]:
    """``(conclusion, judgment)`` from the relations the metadata of either side names."""
    pairs: set[Pair] = set()
    for row in rows:
        for other in row["conclusion_eclis"]:
            other = other.upper()
            ecli = row["ecli"].upper()
            pairs.add((ecli, other) if row["is_conclusion"] else (other, ecli))
    return pairs


def case_number_pairs(
    conclusions: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> set[Pair]:
    """``(conclusion, judgment)`` for conclusions that share a case number with a judgment
    of the court they advise; *candidates* are the rows of ``judgments_by_case_keys``."""
    judgments: dict[tuple[str, str], set[str]] = {}
    for row in candidates:
        if not row["is_conclusion"] and row["ecli"]:
            judgments.setdefault((row["key"], row["court_code"]), set()).add(
                row["ecli"].upper()
            )
    pairs: set[Pair] = set()
    for conclusion in conclusions:
        bench = CONCLUSION_BENCH.get(conclusion["court_code"], conclusion["court_code"])
        for key in conclusion["case_number_keys"]:
            for judgment in judgments.get((key, bench), ()):
                pairs.add((conclusion["ecli"].upper(), judgment))
    return pairs


class RechtspraakConclusionsSemanticPipeline(SemanticPipelineBase):
    """Create ADVISES_ON edges from conclusions to the judgments they advise on."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        rows = list(
            self._track(semantic_queries.conclusion_rows(self.store), "judgments")
        )
        formal = formal_pairs(rows)
        tied = {conclusion for conclusion, _ in formal}
        untied = [
            row
            for row in rows
            if row["is_conclusion"]
            and row["ecli"].upper() not in tied
            and row["case_number_keys"]
        ]
        keys = sorted({key for row in untied for key in row["case_number_keys"]})
        by_number = case_number_pairs(
            untied, list(semantic_queries.judgments_by_case_keys(self.store, keys))
        )
        logger.info(
            "Conclusions: %d tied by the metadata, %d by a shared case number.",
            len(formal),
            len(by_number),
        )

        ids = self._resolve_eclis({e for pair in formal | by_number for e in pair})
        edges = EdgeWriter(self.store, what=None)
        for basis, pairs in ((BASIS_FORMAL, formal), (BASIS_CASE_NUMBER, by_number)):
            for conclusion, judgment in sorted(pairs):
                edges.add(
                    ids.get(conclusion),
                    ids.get(judgment),
                    RELATION_ADVISES_ON,
                    source=SEMANTIC_SOURCE,
                    confidence=CONFIDENCE[basis],
                    meta={"basis": basis},
                )
        edges.flush_into(result)
        return result
