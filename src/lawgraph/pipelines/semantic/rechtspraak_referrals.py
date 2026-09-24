"""Semantic pipeline: ANSWERS from a preliminary ruling to the decision that asked it.

A preliminary ruling (``psi:procedure`` Prejudiciële beslissing: the Hoge Raad answering
questions of a lower court, art. 392 Rv) names the referring decision as its earlier
instance in the metadata (``props.related_eclis``). Without it, its text says who asked:
"Bij tussenvonnis in de zaak C/19/117301/HA ZA 16-256 van 10 oktober 2018 heeft de
rechtbank ... prejudiciële vragen ... gesteld" (``core.judgments.read_referrals``): the
ECLIs it names, else the decision of that date with that case number
(``core.judgments.same_case_number``).
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import RELATION_ANSWERS
from lawgraph.core.judgments import REFERRAL_PARAGRAPHS, Referral, read_referrals
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import semantic as semantic_queries

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "rechtspraak-referral-linker"
BASIS_FORMAL = "formal_relation"
BASIS_TEXT = "referral_text"
CONFIDENCE = {BASIS_FORMAL: 1.0, BASIS_TEXT: 0.9}

Link = tuple[str, str, str]  # (ruling ECLI, referring ECLI, basis)


def by_case_number(
    ruling: str, referral: Referral, candidates: list[dict[str, Any]]
) -> list[str]:
    """The referring decisions among *candidates* (rows of ``decisions_on_dates``): of the
    date the text gives, with one of the case numbers it names."""
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
            semantic_queries.preliminary_rulings(
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
                links += [(ruling, e, BASIS_TEXT) for e in referral.eclis]
                if referral.case_numbers and referral.date:
                    by_text.append((ruling, referral))

        dates = sorted({referral.date for _, referral in by_text if referral.date})
        candidates = list(semantic_queries.decisions_on_dates(self.store, dates))
        for ruling, referral in by_text:
            links += [
                (ruling, referring, BASIS_TEXT)
                for referring in by_case_number(ruling, referral, candidates)
            ]
        logger.info("Preliminary rulings: %d referring decisions found.", len(links))

        ids = self._resolve_eclis({e for link in links for e in link[:2]})
        edges = EdgeWriter(self.store, what=None)
        for ruling, referring, basis in links:
            edges.add(
                ids.get(ruling),
                ids.get(referring),
                RELATION_ANSWERS,
                source=SEMANTIC_SOURCE,
                confidence=CONFIDENCE[basis],
                meta={"basis": basis},
            )
        edges.flush_into(result)
        return result
