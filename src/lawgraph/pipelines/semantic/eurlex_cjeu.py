"""Semantic pipeline: the judgments of the courts of the Union and the judgments they cite
and answer.

``REFERS_TO`` to every judgment a judgment of the Court names by its ECLI in its text, as
the Court writes it ("Schrems, C‑362/14, EU:C:2015:650, punt 73"; ``core.cjeu``), with the
places that name it as ``semantic rechtspraak-citations`` keeps them (``meta.mentions``); a
judgment that is not loaded becomes a stub. ``ANSWERS`` from a preliminary ruling on a
question of a Dutch court to the decision that referred it: the ``*A9*`` decision of the
national decisions CELLAR names (``meta.national``), by its ECLI, else the decision of the
graph of that date with that case number. The articles a judgment cites are read with
those of the Rechtspraak (``semantic rechtspraak``). Derived in full on every run: an edge
no judgment supports any more goes.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_JUDGMENTS,
    RELATION_ANSWERS,
    RELATION_REFERS_TO,
)
from lawgraph.core.case_numbers import Referral
from lawgraph.core.cjeu import referrals
from lawgraph.core.ecli import eu_ecli_mentions
from lawgraph.core.logging import get_logger
from lawgraph.core.mentions import Mention
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.provenance import BASIS_NATIONAL_DECISION
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import cjeu as semantic_cjeu
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak
from lawgraph.sources.addresses import edge_source

from .base import JUDGMENT_BATCH_SIZE, SemanticPipelineBase
from .rechtspraak_citations import CONFIDENCE as CITATION_CONFIDENCE
from .rechtspraak_citations import places_meta
from .rechtspraak_referrals import by_case_number

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)
# By the ECLI CELLAR names, by the date and case number.
CONFIDENCE_ECLI = 1.0
CONFIDENCE_CASE_NUMBER = 0.9
# The country a case was referred from whose courts the graph holds.
NETHERLANDS = "NLD"


def cited_places(paragraphs: list[dict[str, Any]]) -> dict[str, list[Mention]]:
    """Per ECLI of a judgment of the Union that *paragraphs* name, the places that name it,
    in reading order."""
    found: dict[str, list[Mention]] = {}
    for paragraph in paragraphs:
        text = str(paragraph.get("text") or "")
        for ecli, start, end in eu_ecli_mentions(text):
            found.setdefault(ecli, []).append(
                Mention.read(
                    paragraph, text, (start, end), confidence=CITATION_CONFIDENCE
                )
            )
    return found


class EurlexCjeuSemanticPipeline(SemanticPipelineBase):
    """REFERS_TO from the judgments of the Court to those they cite, ANSWERS to the Dutch
    decision that referred the questions."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        # (citing id, cited ECLI, the places as the edge keeps them)
        cited: list[tuple[str, str, dict[str, Any]]] = []
        referred: list[tuple[str, Referral]] = []
        read: list[str] = []
        for row in self._track(
            semantic_cjeu.cjeu_judgments(self.store, batch_size=JUDGMENT_BATCH_SIZE),
            "judgments of the Court",
        ):
            judgment = Node.from_document(COLLECTION_JUDGMENTS, row)
            ecli = str(judgment.props.get("ecli") or "").upper()
            read.append(str(judgment.node_id))
            for other, mentions in cited_places(
                judgment.props.get("paragraphs") or []
            ).items():
                if other != ecli:
                    cited.append((read[-1], other, places_meta(mentions)))
            facts = judgment.props.get("meta") or {}
            if facts.get("country") == NETHERLANDS:
                referred += [(ecli, r) for r in referrals(facts.get("national"))]

        edges = EdgeWriter(self.store, what=None, remembers=True)
        ids = self._resolve_eclis({other for _, other, _ in cited})
        for citing, other, places in cited:
            edges.add(
                citing,
                ids.get(other),
                RELATION_REFERS_TO,
                source=EDGE_SOURCE,
                confidence=CITATION_CONFIDENCE,
                meta={"cited_ecli": other, **places},
            )
        self._answer(referred, edges)
        edges.flush_into(result)
        removed = edges.remove_stale(RELATION_REFERS_TO, EDGE_SOURCE, read)
        removed += edges.remove_stale_of_source(RELATION_ANSWERS, EDGE_SOURCE)
        logger.info("Judgments of the Court: %d edges no judgment supports.", removed)
        self.add_outcomes(result)
        return result

    def _answer(self, referred: list[tuple[str, Referral]], edges: EdgeWriter) -> None:
        """ANSWERS from each ruling to the decisions that referred its questions."""
        links = [
            (ruling, referring, CONFIDENCE_ECLI)
            for ruling, referral in referred
            for referring in referral.eclis
        ]
        by_text = [(r, ref) for r, ref in referred if not ref.eclis and ref.date]
        dates = sorted({ref.date for _, ref in by_text if ref.date})
        candidates = (
            list(semantic_rechtspraak.judgments_on_dates(self.store, dates))
            if dates
            else []
        )
        found = [
            (ruling, by_case_number(ruling, referral, candidates))
            for ruling, referral in by_text
        ]
        # a decision, not the conclusion of an advocate-general on that day
        conclusions = semantic_rechtspraak.conclusions_among(
            self.store, sorted({e for _, eclis in found for e in eclis})
        )
        links += [
            (ruling, referring, CONFIDENCE_CASE_NUMBER)
            for ruling, eclis in found
            for referring in eclis
            if referring not in conclusions
        ]
        ids = self._resolve_eclis({e for link in links for e in link[:2]})
        for ruling, referring, confidence in links:
            edges.add(
                ids.get(ruling),
                ids.get(referring),
                RELATION_ANSWERS,
                source=EDGE_SOURCE,
                confidence=confidence,
                meta={"basis": BASIS_NATIONAL_DECISION},
            )
        logger.info("Judgments of the Court: %d referring decisions found.", len(links))
