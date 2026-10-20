"""Semantic pipeline: REFERS_TO from the articles of a law of the Staatsblad the BWB does not
hold (yet) to the articles their text cites, of the law itself and of other laws.

Its XML has no links a reader can trust, as a toestand of the BWB has (its ``extref``s point
at articles of the old law where the text names the new one): a reference is read from the
text of an article, an enumeration whose articles each have their parts as one citation
("de artikelen 98, eerste en tweede lid, 98c, eerste lid, … van het Wetboek van Strafrecht",
``core.citations.article_chain``).

* "artikel 2.8.16", "de artikelen 1.1.1 en 1.1.2", "artikel 3.1.1, eerste lid, van deze
  wet": an article of the same law (``core/staatsblad_laws.own_references``), when the law
  has it;
* "artikel 11.7a van de Telecommunicatiewet": an article of another law, read as a judgment
  is read (``_detection.detect_in_text``, dated by the day the law was signed), a stub for one
  of a law that is not loaded when the citation is sure enough. A law the text names by the
  citation title of its own law means itself (the "Wetboek van Strafvordering" in the new
  one).

Each article keeps how many of the references its text makes the step could not link
(``unlinked_references``: of an unknown law, of "die regeling", a number its law lacks), its
law the sum: what ``enrichment.references`` of the API says. Derived in full on every run: an
edge of the step from an article read that no reference supports goes.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_REFERS_TO,
)
from lawgraph.core.citations import CitationHit, DutchCitationExtractor
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key, node_id
from lawgraph.core.qualifiers import parse_qualifier
from lawgraph.core.staatsblad_laws import number_span, own_references, unread_numbers
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import staatsblad_laws as law_queries
from lawgraph.sources.addresses import edge_source

from ._detection import build_extractor, detect_in_text
from .base import SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)
# Read from the words of the text, not from a link: "artikel 2.8.16" without a law after it
# is one of the law itself.
CONFIDENCE = 0.9
# A citation of another law surer than this may make a stub of an article not loaded.
STUB_CONFIDENCE = 0.9


class StaatsbladLawReferencesSemanticPipeline(SemanticPipelineBase):
    """References from the articles of a law of the Staatsblad."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        laws = {row["official_id"]: row for row in law_queries.laws(self.store)}
        rows = list(law_queries.law_articles(self.store))
        keys = {row["key"] for row in rows}
        extractor = self._extractor()
        edges = EdgeWriter(self.store, what=None, remembers=True)
        unlinked: dict[str, int] = {}
        for row in self._track(rows, "articles", total=len(rows)):
            law = laws.get(row["official_id"]) or {}
            unlinked[row["id"]] = self._link(row, law, keys, extractor, edges)
        edges.flush_into(result)
        removed = edges.remove_stale(RELATION_REFERS_TO, EDGE_SOURCE, sorted(unlinked))
        self._keep_unlinked(rows, laws, unlinked)
        logger.info(
            "%d articles of laws of the Staatsblad read, %d references they make not "
            "linked; %d references they no longer make removed.",
            len(unlinked),
            sum(unlinked.values()),
            removed,
        )
        self.add_outcomes(result)
        return result

    def _extractor(self) -> DutchCitationExtractor:
        """The extractor of the article citations of running text, as a judgment is read."""
        mapping, shared = self._load_code_choices()
        return build_extractor(
            mapping,
            self._load_instrument_aliases(),
            self._load_context_aliases(mapping),
            self._load_law_dates(),
            shared,
        )

    def _link(
        self,
        row: dict[str, Any],
        law: dict[str, Any],
        keys: set[str],
        extractor: DutchCitationExtractor,
        edges: EdgeWriter,
    ) -> int:
        """Add the edges of the references of the article *row* of *law*; how many it
        makes that could not be linked."""
        text = row["text"] or ""
        missed = 0
        own = own_references(text)
        for reference in own:
            key = make_node_key(row["official_id"], reference.number)
            if key == row["key"]:
                continue
            if key not in keys:
                missed += 1
                continue
            edges.add(
                row["id"],
                node_id(COLLECTION_ARTICLES, key),
                RELATION_REFERS_TO,
                source=EDGE_SOURCE,
                confidence=CONFIDENCE,
                meta=reference.meta(),
            )
        heads = {reference.head for reference in own}
        hits = [
            hit
            for hit in detect_in_text(
                text,
                extractor,
                every_occurrence=True,
                unknown_laws=True,
                on=law.get("date_signed"),
                chains=True,
            )
            if hit.kind == "article"
            and hit.start is not None
            and hit.start not in heads
        ]
        for hit in hits:
            target = self._target(hit, row, law, keys)
            if target is None:
                missed += 1
            elif target[0] != row["id"]:
                edges.add(
                    row["id"],
                    target[0],
                    RELATION_REFERS_TO,
                    source=EDGE_SOURCE,
                    confidence=hit.confidence,
                    meta=_meta(text, hit, own=target[1]),
                )
        read = [(r.start, r.end) for r in own] + [
            (hit.start or 0, hit.end or 0) for hit in hits
        ]
        return missed + unread_numbers(text, read)

    def _target(
        self, hit: CitationHit, row: dict[str, Any], law: dict[str, Any], keys: set[str]
    ) -> tuple[str, bool] | None:
        """``(id, own)`` of the article *hit* cites, *own* when it is one of the law of
        *row*: the law names itself by its own citation title (``named``); else as
        ``_cited_article`` finds it. None when there is none."""
        law_id = hit.bwb_id or hit.celex
        if not law_id or not hit.article_number:
            return None
        if hit.bwb_id and hit.bwb_id in (law.get("named") or []):
            key = make_node_key(row["official_id"], hit.article_number)
            return (node_id(COLLECTION_ARTICLES, key), True) if key in keys else None
        node = self._cited_article(
            law_id,
            hit.article_number,
            celex=hit.bwb_id is None,
            confidence=hit.confidence,
            min_confidence=STUB_CONFIDENCE,
        )
        return (node.node_id, False) if node is not None and node.node_id else None

    def _keep_unlinked(
        self,
        rows: list[dict[str, Any]],
        laws: dict[str, dict[str, Any]],
        unlinked: dict[str, int],
    ) -> None:
        """Keep ``unlinked_references`` on each article read and on its law (their sum);
        only where it changed."""
        per_law: dict[str, int] = {}
        for row in rows:
            law = laws.get(row["official_id"])
            if law is not None:
                per_law[law["id"]] = per_law.get(law["id"], 0) + unlinked[row["id"]]
        law_queries.keep_counts(
            self.store,
            COLLECTION_ARTICLES,
            "unlinked_references",
            unlinked,
            {row["id"]: row["unlinked_references"] for row in rows},
        )
        law_queries.keep_counts(
            self.store,
            COLLECTION_INSTRUMENTS,
            "unlinked_references",
            per_law,
            {law["id"]: law["unlinked_references"] for law in laws.values()},
        )


def _meta(text: str, hit: CitationHit, *, own: bool) -> dict[str, Any]:
    """Where the citation of *hit* stands: its number in the text (the whole citation for
    a number it does not write), and the parts it names of that article."""
    start, end = number_span(text, hit.start or 0, hit.article_number or "") or (
        hit.start or 0,
        hit.end or 0,
    )
    return {
        "start": start,
        "end": end,
        "text": text[start:end],
        "reference_kind": "intref" if own else "extref",
        **parse_qualifier(hit.qualifier).to_dict(),
    }
