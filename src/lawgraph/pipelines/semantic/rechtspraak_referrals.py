"""Semantic pipeline: ANSWERS from a preliminary ruling to the decision that asked it.

A preliminary ruling (``psi:procedure`` Prejudiciële beslissing: the Hoge Raad answering
questions of a lower court, art. 392 Rv) names the referring decision as its earlier
instance in the metadata (``props.related_eclis``). Without it, its text says who asked:
"Bij tussenvonnis in de zaak C/19/117301/HA ZA 16-256 van 10 oktober 2018 heeft de
rechtbank ... prejudiciële vragen ... gesteld" (``core.case_numbers.read_referrals``): the
ECLIs it names, else the decision of that date with that case number
(``core.case_numbers.same_case_number``). Derived in full on every run: an edge no ruling
supports any more goes.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_ANSWERS
from lawgraph.core.case_numbers import REFERRAL_PARAGRAPHS, Referral, read_referrals
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.core.provenance import BASIS_FORMAL, BASIS_REFERRAL_TEXT, Basis
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak

from .base import SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = "rechtspraak-referral-linker"
CONFIDENCE = {BASIS_FORMAL: 1.0, BASIS_REFERRAL_TEXT: 0.9}

Link = tuple[str, str, Basis]  # (ruling ECLI, referring ECLI, basis)


def by_case_number(
    ruling: str, referral: Referral, candidates: list[dict[str, Any]]
) -> list[str]:
    """The referring decisions among *candidates* (rows of ``judgments_on_dates``): of the
    date the text gives, with one of the case numbers it names; upper case."""
    return sorted(
        {
            row["ecli"].upper()
            for row in candidates
            if row["date"] == referral.date
            and row["ecli"].upper() != ruling
            and referral.names(row["case_number"])
        }
    )


class RechtspraakReferralsSemanticPipeline(SemanticPipelineBase):
    """Create ANSWERS edges from preliminary rulings to the decisions that referred."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        links: list[Link] = []
        by_text: list[tuple[str, Referral]] = []
        for row in self._track(
            semantic_rechtspraak.preliminary_rulings(
                self.store, paragraphs=REFERRAL_PARAGRAPHS
            ),
            "preliminary rulings",
        ):
            ruling = row["ecli"].upper()
            if row["related_eclis"]:
                links += [
                    (ruling, e.upper(), BASIS_FORMAL) for e in row["related_eclis"]
                ]
                continue
            for referral in read_referrals(row["paragraphs"]):
                links += [(ruling, e, BASIS_REFERRAL_TEXT) for e in referral.eclis]
                if referral.case_numbers and referral.date:
                    by_text.append((ruling, referral))

        dates = sorted({referral.date for _, referral in by_text if referral.date})
        candidates = list(semantic_rechtspraak.judgments_on_dates(self.store, dates))
        found = [
            (ruling, by_case_number(ruling, referral, candidates))
            for ruling, referral in by_text
        ]
        # a decision, not the conclusion of an advocate-general on that day
        conclusions = semantic_rechtspraak.conclusions_among(
            self.store, sorted({e for _, eclis in found for e in eclis})
        )
        links += [
            (ruling, referring, BASIS_REFERRAL_TEXT)
            for ruling, eclis in found
            for referring in eclis
            if referring not in conclusions
        ]
        logger.info("Preliminary rulings: %d referring decisions found.", len(links))

        ids = self._resolve_eclis({e for link in links for e in link[:2]})
        edges = EdgeWriter(self.store, what=None, remembers=True)
        for ruling, referring, basis in links:
            edges.add(
                ids.get(ruling),
                ids.get(referring),
                RELATION_ANSWERS,
                source=EDGE_SOURCE,
                confidence=CONFIDENCE[basis],
                meta={"basis": basis},
            )
        edges.flush_into(result)
        removed = edges.remove_stale_of_source(RELATION_ANSWERS, EDGE_SOURCE)
        logger.info(
            "Preliminary rulings: %d edges no ruling supports removed.", removed
        )
        return result
