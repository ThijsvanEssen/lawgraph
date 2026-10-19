"""Semantic pipeline: RELATED_TO from a judgment to the connected cases its summary names.

The court tells connected cases in its summary (inhoudsindicatie), never in the metadata:
"Samenhang met 24/03860 E en 24/03859 P", "Zie ook: ECLI:NL:GHDHA:2025:1539"
(``core.related_cases``). An edge only on an exact match with a judgment in the graph: the
ECLI it names, or the case number of a judgment of the same court (``case_number_keys``,
the Hoge Raad's type letter is not part of the comparison). What is named and not found
gets no edge and is counted. The edges of a judgment are derived in full each run: one no
longer derived goes.

With ``since`` only the judgments retrieved from then on are read (the daily run): their
summary is all their edges come from. An older judgment that names a judgment retrieved since
waits for a run without it (the weekly run), which reads every summary.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, NamedTuple

from lawgraph.config.constants import RELATION_RELATED_TO
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.provenance import BASIS_SUMMARY_TEXT
from lawgraph.core.related_cases import RelatedCases, read_related_cases
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak

from .base import EXACT_CONFIDENCE, SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "rechtspraak-related-cases"


class Named(NamedTuple):
    """A sentence of a judgment's summary that names connected cases."""

    judgment_id: str
    court_code: str
    sentence: RelatedCases


class Link(NamedTuple):
    """A RELATED_TO edge to write: to the judgment of an ECLI, with the sentence."""

    from_id: str
    to_ecli: str
    text: str


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

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        since_iso = iso_timestamp(since)
        # the judgments retrieved since then; all of them without since
        eclis = self._recent_eclis(since_iso) if since_iso else None
        logger.info("Connected cases (since=%s).", describe_since(since))
        named: list[Named] = []
        for row in self._track(
            semantic_rechtspraak.judgments_naming_related_cases(
                self.store, eclis=eclis
            ),
            "judgments naming connected cases",
        ):
            for sentence in read_related_cases(row.get("summary")):
                named.append(
                    Named(str(row["id"]), str(row.get("court_code") or ""), sentence)
                )

        keys = sorted(
            {k for n in named for number in n.sentence.case_numbers for k in number}
        )
        rows_by_key: dict[str, list[dict[str, Any]]] = {}
        for row in semantic_rechtspraak.judgments_by_case_keys(self.store, keys):
            rows_by_key.setdefault(row["key"], []).append(row)

        links, unresolved = self._links(named, rows_by_key)
        ids = {
            str(row["ecli"]).upper(): str(row["id"])
            for row in semantic_rechtspraak.judgment_ids_by_ecli(
                self.store, sorted({link.to_ecli for link in links})
            )
        }
        edges = EdgeWriter(self.store, what=None, remembers=True)
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
                source=EDGE_SOURCE,
                confidence=EXACT_CONFIDENCE,
                meta={"basis": BASIS_SUMMARY_TEXT, "text": text},
            )
        edges.flush_into(result)
        if eclis is None:
            removed = edges.remove_stale_of_source(RELATION_RELATED_TO, EDGE_SOURCE)
        else:
            read = [
                str(row["id"])
                for row in semantic_rechtspraak.judgment_ids_by_ecli(self.store, eclis)
            ]
            removed = edges.remove_stale(RELATION_RELATED_TO, EDGE_SOURCE, read)
        result.skipped += unresolved
        logger.info(
            "Connected cases: %d sentences in %d judgments; %d edges, %d named cases not "
            "found (not loaded, not published, or no exact match); removed %d.",
            len(named),
            len({n.judgment_id for n in named}),
            edges.written(RELATION_RELATED_TO),
            unresolved,
            removed,
        )
        return result

    @staticmethod
    def _links(
        named: list[Named], rows_by_key: dict[str, list[dict[str, Any]]]
    ) -> tuple[list[Link], int]:
        """The link to every case named, and how many case numbers matched no judgment of
        the same court."""
        links: list[Link] = []
        unresolved = 0
        for source_id, court_code, sentence in named:
            targets = list(sentence.eclis)
            for keys in sentence.case_numbers:
                found = match_case_number(keys, court_code, rows_by_key)
                unresolved += not found
                targets += found
            links += [
                Link(source_id, target, sentence.text)
                for target in dict.fromkeys(targets)
            ]
        return links, unresolved
