"""Semantic pipeline: RELATED_TO from a judgment to the connected cases its summary names.

The court tells connected cases in its summary (inhoudsindicatie), never in the metadata:
"Samenhang met 24/03860 E en 24/03859 P", "Zie ook: ECLI:NL:GHDHA:2025:1539"
(``core.related_cases``). An edge only on an exact match with a judgment in the graph: the
ECLI it names, or the case number of a judgment of the same court (``case_number_keys``,
the Hoge Raad's type letter is not part of the comparison). What is named and not found
gets no edge and is counted. The edges are derived in full on every run.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_RELATED_TO
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.related_cases import RelatedCases, read_related_cases
from lawgraph.db import EdgeWriter, edge_key
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "rechtspraak-related-cases"
BASIS = "summary_text"

Named = tuple[str, str, RelatedCases]  # (judgment id, its court code, the sentence)


def match_case_number(
    keys: list[str], court_code: str, rows_by_key: dict[str, list[dict[str, Any]]]
) -> list[str]:
    """The ECLIs of the judgments of *court_code* with the case number *keys* (as written
    first, then without the type of case): those of the first key that has any."""
    for key in keys:
        found = sorted(
            {
                str(row["ecli"]).upper()
                for row in rows_by_key.get(key, [])
                if row.get("ecli") and row.get("court_code") == court_code
            }
        )
        if found:
            return found
    return []


class RechtspraakRelatedSemanticPipeline(SemanticPipelineBase):
    """RELATED_TO from a judgment to the connected cases its summary names."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        named: list[Named] = []
        for row in self._track(
            semantic_rechtspraak.judgments_naming_related_cases(self.store),
            "judgments naming connected cases",
        ):
            for sentence in read_related_cases(row.get("summary")):
                named.append(
                    (str(row["id"]), str(row.get("court_code") or ""), sentence)
                )

        keys = sorted(
            {k for _, _, s in named for number in s.case_numbers for k in number}
        )
        rows_by_key: dict[str, list[dict[str, Any]]] = {}
        for row in semantic_rechtspraak.judgments_by_case_keys(self.store, keys):
            rows_by_key.setdefault(row["key"], []).append(row)

        links, unresolved = self._links(named, rows_by_key)
        ids = {
            str(row["ecli"]).upper(): str(row["id"])
            for row in semantic_rechtspraak.judgment_ids_by_ecli(
                self.store, sorted({target for _, target, _ in links})
            )
        }
        edges = EdgeWriter(self.store, what=None)
        kept: list[str] = []
        for source_id, target, text in links:
            target_id = ids.get(target)
            if target_id is None:
                unresolved += 1
                continue
            if target_id == source_id:
                continue
            edges.add(
                source_id,
                target_id,
                RELATION_RELATED_TO,
                source=SEMANTIC_SOURCE,
                confidence=1.0,
                meta={"basis": BASIS, "text": text},
            )
            kept.append(edge_key(source_id, RELATION_RELATED_TO, target_id))
        edges.flush_into(result)
        removed = semantic_edges.remove_edges_of_source_except(
            self.store, RELATION_RELATED_TO, SEMANTIC_SOURCE, kept
        )
        result.skipped += unresolved
        logger.info(
            "Connected cases: %d sentences in %d judgments; %d edges, %d named cases not "
            "found (not loaded, not published, or no exact match); removed %d.",
            len(named),
            len({source for source, _, _ in named}),
            len(set(kept)),
            unresolved,
            removed,
        )
        return result

    @staticmethod
    def _links(
        named: list[Named], rows_by_key: dict[str, list[dict[str, Any]]]
    ) -> tuple[list[tuple[str, str, str]], int]:
        """``(judgment id, target ECLI, sentence)`` of every case named, and how many case
        numbers matched no judgment of the same court."""
        links: list[tuple[str, str, str]] = []
        unresolved = 0
        for source_id, court_code, sentence in named:
            targets = list(sentence.eclis)
            for keys in sentence.case_numbers:
                found = match_case_number(keys, court_code, rows_by_key)
                unresolved += not found
                targets += found
            links += [
                (source_id, target, sentence.text) for target in dict.fromkeys(targets)
            ]
        return links, unresolved
