"""Semantic pipeline: ADVISES_ON from the conclusion of an advocate-general to its judgment.

The Rechtspraak metadata ties a conclusion and its judgment by a ``dcterms:relation`` of
``psi:type`` conclusie, written on either side (``props.conclusion_eclis``). The edge runs one
way, from the conclusion: a relation a judgment writes to another loaded judgment that is no
conclusion ties nothing. A conclusion that neither side ties is linked by the case number it
shares with a judgment of the court it advises (``core.judgment_metadata.CONCLUSION_BENCH``: the
Parket bij de Hoge Raad advises the Hoge Raad). A court that advises itself (the staatsraad
advocaat-generaal of the Raad van State) asks for the conclusion in a case of its own number
("201406676/2/A3" for the case 201406676/1/A3): such a conclusion is linked to the later
judgments of its court within ``OWN_BENCH_YEARS`` that share its dossier number
(``core.case_numbers.same_case_number``). The edges of a conclusion are derived in full each
run: one no longer derived goes.

With ``--touched-since`` (a poll) it derives in full only the conclusions the judgments
retrieved since then can change (``touched_conclusions``), and comes to the same for them as a
run over all: those judgments themselves, the conclusions they name, the conclusions at either
end of an edge to or from them, the conclusions that share a case number with them, and the
conclusions of their own court within ``OWN_BENCH_YEARS`` before them. What names a conclusion
it reads from those judgments and from the edges the conclusion already has; a judgment that
named nothing and now turns out to be a conclusion waits for the nightly run over all.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import RELATION_ADVISES_ON
from lawgraph.core.case_numbers import same_case_number
from lawgraph.core.judgment_metadata import CONCLUSION_BENCH
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.provenance import BASIS_CASE_NUMBER, BASIS_FORMAL
from lawgraph.core.time import iso_timestamp
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak

from .base import SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "rechtspraak-conclusion-linker"
CONFIDENCE = {BASIS_FORMAL: 1.0, BASIS_CASE_NUMBER: 0.9}
# How long after its conclusion a court that advises itself gives the judgment.
OWN_BENCH_YEARS = 3

Pair = tuple[str, str]  # (conclusion ECLI, judgment ECLI)


def formal_pairs(
    rows: list[dict[str, Any]], not_conclusions: frozenset[str] = frozenset()
) -> set[Pair]:
    """``(conclusion, judgment)`` from the relations the metadata of either side names;
    *not_conclusions* are loaded judgments that are no conclusion, whatever a relation to
    them says."""
    pairs: set[Pair] = set()
    for row in rows:
        ecli = row["ecli"].upper()
        for other in row["conclusion_eclis"]:
            other = other.upper()
            if row["is_conclusion"]:
                pairs.add((ecli, other))
            elif other not in not_conclusions:
                pairs.add((other, ecli))
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


def own_bench_span(conclusion: dict[str, Any]) -> dict[str, str] | None:
    """The court and the dates in which a conclusion of a court that advises itself has
    its judgment; ``None`` for one of another court or without a date."""
    court, date = conclusion["court_code"], conclusion.get("date")
    if court in CONCLUSION_BENCH or not date:
        return None
    start = dt.date.fromisoformat(date)
    end = start.replace(year=start.year + OWN_BENCH_YEARS, day=min(start.day, 28))
    return {"court_code": court, "start": date, "end": end.isoformat()}


def own_bench_pairs(
    conclusions: list[dict[str, Any]], candidates: list[dict[str, Any]]
) -> set[Pair]:
    """``(conclusion, judgment)`` for conclusions of a court that advises itself and the
    later decisions of that court (rows of ``court_decisions_between``) that share their
    dossier number."""
    pairs: set[Pair] = set()
    for conclusion in conclusions:
        span = own_bench_span(conclusion)
        if span is None or not conclusion.get("case_number"):
            continue
        pairs |= {
            (conclusion["ecli"].upper(), row["ecli"].upper())
            for row in candidates
            if row["court_code"] == span["court_code"]
            and span["start"] <= (row["date"] or "") <= span["end"]
            and row["ecli"].upper() != conclusion["ecli"].upper()
            and same_case_number(conclusion["case_number"], row["case_number"])
        }
    return pairs


def own_bench_before(judgment: dict[str, Any]) -> dict[str, str] | None:
    """The court and the dates of the conclusions whose ``own_bench_span`` can hold
    *judgment* (a day or two more); ``None`` for one of a court that advises none of its own,
    or without a date."""
    court, date = judgment["court_code"], judgment.get("date")
    if not court or court in CONCLUSION_BENCH.values() or not date:
        return None
    end = dt.date.fromisoformat(date)
    start = end.replace(year=end.year - OWN_BENCH_YEARS, day=1)
    return {"court_code": court, "start": start.isoformat(), "end": date}


class RechtspraakConclusionsSemanticPipeline(SemanticPipelineBase):
    """Create ADVISES_ON edges from conclusions to the judgments they advise on."""

    def run(self, *, touched_since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        conclusions: set[str] | None = None
        if touched_since is None:
            rows = list(
                self._track(
                    semantic_rechtspraak.conclusion_rows(self.store), "judgments"
                )
            )
        else:
            conclusions = self.touched_conclusions(touched_since)
            rows = self._rows_naming(conclusions)
        named = sorted({e.upper() for row in rows for e in row["conclusion_eclis"]})
        not_conclusions = frozenset(
            str(row["ecli"]).upper()
            for row in semantic_rechtspraak.judgment_instances(self.store, named)
            if not row["is_conclusion"]
        )
        formal = formal_pairs(rows, not_conclusions)
        if conclusions is not None:
            formal = {pair for pair in formal if pair[0] in conclusions}
            rows = [row for row in rows if row["ecli"].upper() in conclusions]
        by_number = self._by_case_number(rows, {c for c, _ in formal})
        logger.info(
            "Conclusions: %d tied by the metadata, %d by a shared case number.",
            len(formal),
            len(by_number),
        )

        ids = self._resolve_eclis(
            {e for pair in formal | by_number for e in pair}
            | {row["ecli"].upper() for row in rows}
        )
        edges = EdgeWriter(self.store, what=None, remembers=True)
        for basis, pairs in ((BASIS_FORMAL, formal), (BASIS_CASE_NUMBER, by_number)):
            for conclusion, judgment in sorted(pairs):
                from_id, to_id = ids.get(conclusion), ids.get(judgment)
                edges.add(
                    from_id,
                    to_id,
                    RELATION_ADVISES_ON,
                    source=EDGE_SOURCE,
                    confidence=CONFIDENCE[basis],
                    meta={"basis": basis},
                )
        edges.flush_into(result)
        derived = (
            set(ids.values())
            if conclusions is None
            else set(self._judgment_ids(sorted(conclusions)))
        )
        removed = edges.remove_stale(RELATION_ADVISES_ON, EDGE_SOURCE, sorted(derived))
        logger.info("Removed %d ADVISES_ON no longer derived.", removed)
        return result

    def touched_conclusions(self, since: dt.datetime) -> set[str]:
        """The ECLIs whose edges the judgments retrieved at or after *since* can change: those
        judgments, the conclusions they name, the conclusions of an edge to or from them, and
        the conclusions that share a case number with them or may have them as a judgment of
        their own court."""
        eclis = sorted(e.upper() for e in self._recent_eclis(iso_timestamp(since)))
        targets = list(semantic_rechtspraak.conclusion_targets(self.store, eclis))
        found = set(eclis)
        for row in semantic_rechtspraak.conclusion_rows(self.store, eclis):
            found |= {e.upper() for e in row["conclusion_eclis"]}
        found |= {
            str(row["conclusion"]).upper()
            for row in semantic_rechtspraak.advice_edges(
                self.store,
                EDGE_SOURCE,
                RELATION_ADVISES_ON,
                [row["id"] for row in targets],
            )
        }
        keys = sorted({key for row in targets for key in row["case_number_keys"]})
        found |= {
            str(row["ecli"]).upper()
            for row in semantic_rechtspraak.judgments_by_case_keys(self.store, keys)
            if row["is_conclusion"] and row["ecli"]
        }
        return found | self._own_bench_conclusions(targets)

    def _own_bench_conclusions(self, judgments: list[dict[str, Any]]) -> set[str]:
        """The conclusions of a court that advises itself that may have one of *judgments*
        as their judgment (``own_bench_pairs``)."""
        by_court: dict[str, dict[str, str]] = {}
        for row in judgments:
            if span := own_bench_before(row):
                court = by_court.setdefault(span["court_code"], span)
                court["start"] = min(court["start"], span["start"])
                court["end"] = max(court["end"], span["end"])
        if not by_court:
            return set()
        spans = list(by_court.values())
        numbers = [row["case_number"] for row in judgments if row["case_number"]]
        return {
            str(row["ecli"]).upper()
            for row in semantic_rechtspraak.conclusions_between(self.store, spans)
            if row["case_number"]
            and any(same_case_number(row["case_number"], n) for n in numbers)
        }

    def _rows_naming(self, conclusions: set[str]) -> list[dict[str, Any]]:
        """The rows of ``conclusion_rows`` of *conclusions* and of the judgments that may
        name one of them: those the retrieval touched are among *conclusions*; the others
        are at the other end of an edge the conclusion already has."""
        ids = self._judgment_ids(sorted(conclusions))
        naming = {
            str(row["judgment"]).upper()
            for row in semantic_rechtspraak.advice_edges(
                self.store, EDGE_SOURCE, RELATION_ADVISES_ON, ids
            )
            if str(row["conclusion"]).upper() in conclusions
        }
        eclis = sorted(conclusions | naming)
        return list(semantic_rechtspraak.conclusion_rows(self.store, eclis))

    def _by_case_number(self, rows: list[dict[str, Any]], tied: set[str]) -> set[Pair]:
        """The pairs of the conclusions no relation ties, by the case number they share
        with a judgment of the court they advise."""
        untied = [
            row
            for row in rows
            if row["is_conclusion"]
            and row["ecli"].upper() not in tied
            and row["case_number_keys"]
        ]
        keys = sorted({key for row in untied for key in row["case_number_keys"]})
        pairs = case_number_pairs(
            untied, list(semantic_rechtspraak.judgments_by_case_keys(self.store, keys))
        )
        paired = {conclusion for conclusion, _ in pairs}
        unpaired = [row for row in untied if row["ecli"].upper() not in paired]
        spans = [span for row in unpaired if (span := own_bench_span(row))]
        if spans:
            candidates = list(
                semantic_rechtspraak.court_decisions_between(self.store, spans)
            )
            pairs |= own_bench_pairs(unpaired, candidates)
        return pairs
