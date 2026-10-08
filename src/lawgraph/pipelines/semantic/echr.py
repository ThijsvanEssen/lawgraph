"""Semantic pipeline: ECHR judgments → REFERS_TO → the articles of the Convention.

HUDOC names the Convention articles a judgment applies in its ``article`` field, as
``8;8-1;8-2;41;P1-1``: articles separated by ``;``, a paragraph after ``-`` (``8-1`` is
article 8, paragraph 1), articles applied together joined by ``+`` (``13+8``), and ``P<n>-``
before an article of a Protocol (``P1-1``). ``convention_articles`` reads that into the
articles of the Convention and the paragraphs named of each.

The Convention is the treaty of the BWB, ``ECHR_CONVENTION_BWB_ID`` (BWBV0001000): its articles
are numbered as HUDOC numbers them (``8``), so a judgment of the ECHR and a Dutch judgment that
cites "art. 8 EVRM" reach the same article. While the treaty is not loaded its cited articles
are stubs, as the cited articles of any law that is not loaded (``_cited_article``). A Protocol
is a treaty of its own, which HUDOC names by number only: the curated list ``echr-protocols``
gives its BWB treaty (P1 is BWBV0001001), and ``P1-1`` is article 1 of it. A Protocol the list
does not have (one that only changes the procedure of the Court) is not linked.

Judgments are also linked to the BWB instruments whose id their ``conclusion`` names, and to the
decisions of the Court their text cites by application number ("Kılıç v. Turkey, no. 22492/93"):
the decision of that number and date, or without a date the only decision of the number
(``_echr_citations``). The edges of a judgment are derived in full each run: one it no longer
supports is removed.
"""

from __future__ import annotations

import re
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    ECHR_CONVENTION_BWB_ID,
    RELATION_REFERS_TO,
)
from lawgraph.core.curated import LISTS
from lawgraph.core.echr_citations import appnos, cited_in_english
from lawgraph.core.identifiers import BWB_ID_PATTERN
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, NodeType, PipelineResult
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak

from . import _echr_citations
from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "echr-citation-linker"
CONFIDENCE_ARTICLE = 0.95
CONFIDENCE_CONCLUSION = 0.80

# One article as HUDOC writes it: "8", "8-1", "5-1-f", "35-3-a"; a Protocol's starts with "P".
_HUDOC_ARTICLE_RE = re.compile(r"^(?P<number>\d+[a-z]?)(?:-(?P<paragraph>\d+))?")
# An article of a Protocol: "P1-1", "P1-1-1" (its paragraph), "P4-2".
_PROTOCOL_ARTICLE_RE = re.compile(
    r"^(?P<protocol>P\d+)-(?P<number>\d+[a-z]?)(?:-(?P<paragraph>\d+))?"
)


def _items(labels: list[str] | str | None) -> list[str]:
    """The articles HUDOC names, one per item: ``8;8-1;13+8`` is ``8``, ``8-1``, ``13``, ``8``."""
    if isinstance(labels, str):
        labels = [labels]
    return [
        item.strip() for label in labels or [] for item in re.split(r"[;+]", str(label))
    ]


def protocol_articles(
    labels: list[str] | str | None,
) -> dict[tuple[str, str], list[str]]:
    """(Protocol, article) -> the paragraphs named of it, in the order HUDOC names them:
    ``["8;P1-1;P1-1-1;P4-2"]`` is ``{("P1", "1"): ["1"], ("P4", "2"): []}``."""
    found: dict[tuple[str, str], list[str]] = {}
    for item in _items(labels):
        match = _PROTOCOL_ARTICLE_RE.match(item)
        if not match:
            continue
        paragraphs = found.setdefault((match["protocol"], match["number"]), [])
        if match["paragraph"] and match["paragraph"] not in paragraphs:
            paragraphs.append(match["paragraph"])
    return found


def protocol_treaties() -> dict[str, str]:
    """HUDOC Protocol -> the BWB id of its treaty (curated ``echr-protocols``)."""
    return {
        protocol: str(value["bwb_id"])
        for protocol, value in LISTS["echr-protocols"].entries().items()
    }


def convention_articles(labels: list[str] | str | None) -> dict[str, list[str]]:
    """Article number -> the paragraphs named of it, in the order HUDOC names the articles:
    ``["8;8-1;8-2;41;P1-1"]`` is ``{"8": ["1", "2"], "41": []}``."""
    found: dict[str, list[str]] = {}
    for item in _items(labels):
        match = _HUDOC_ARTICLE_RE.match(item)
        if not match:  # a Protocol ("P1-1"), or nothing
            continue
        paragraphs = found.setdefault(match["number"], [])
        paragraph = match["paragraph"]
        if paragraph and paragraph not in paragraphs:
            paragraphs.append(paragraph)
    return found


class ECHRSemanticPipeline(SemanticPipelineBase):
    """Links ECHR judgments to the Convention articles they apply and the instruments their
    conclusion names."""

    def run(self) -> PipelineResult:
        result = PipelineResult()
        rows = list(
            self._track(
                semantic_rechtspraak.echr_judgments(self.store), "ECHR judgments"
            )
        )
        texts = list(semantic_rechtspraak.echr_texts(self.store))
        if not rows and not texts:
            logger.debug("ECHR citations: no ECHR judgments found.")
            return result

        instruments = self._instruments_named(rows)
        edges = EdgeWriter(self.store, what=None)
        kept: dict[str, set[str]] = {}
        read: list[str] = []
        treaties = protocol_treaties()
        unknown = sum(
            1
            for row in rows
            for protocol, _ in protocol_articles(row.get("articles"))
            if protocol not in treaties
        )
        if unknown:
            logger.info(
                "ECHR citations: %d articles of a Protocol not linked (not in the curated "
                "list echr-protocols: it changes the procedure of the Court).",
                unknown,
            )
        for row in rows:
            if not row.get("j_id"):
                result.skipped += 1
                continue
            read.append(row["j_id"])
            judgment = Node(
                collection=COLLECTION_JUDGMENTS,
                type=NodeType.JUDGMENT,
                key=row["j_key"],
                props={},
            )
            for target, confidence, meta in self._targets(row, instruments, treaties):
                doc = self._make_edge_doc(
                    from_node=judgment,
                    to_node=target,
                    relation=RELATION_REFERS_TO,
                    source=SEMANTIC_SOURCE,
                    confidence=confidence,
                    meta=meta,
                )
                if doc:
                    edges.add_doc(doc)
                    kept.setdefault(row["j_id"], set()).add(doc["_key"])
        edges.flush_into(result)
        self._link_cited_decisions(texts, read, kept, result)
        removed = semantic_edges.remove_edges_from(
            self.store, RELATION_REFERS_TO, SEMANTIC_SOURCE, read, kept
        )
        logger.info("ECHR citations: %d edges no judgment supports removed.", removed)
        return result

    def _link_cited_decisions(
        self,
        texts: list[dict[str, Any]],
        read: list[str],
        kept: dict[str, set[str]],
        result: PipelineResult,
    ) -> None:
        """``REFERS_TO`` to the decisions of the Court the text of a judgment cites by
        application number, not its own; adds the judgments read to *read* and the edges
        to *kept*."""
        cited = []
        seen = set(read)
        for row in texts:
            own = frozenset(appnos(row.get("appno")))
            cited += [(row["j_id"], c) for c in cited_in_english(row["text"], own=own)]
            if row["j_id"] not in seen:
                read.append(row["j_id"])
        if not cited:
            return
        decisions = _echr_citations.decisions_index(self.store)
        for from_id, keys in _echr_citations.link(
            self.store, cited, decisions, source=SEMANTIC_SOURCE, result=result
        ).items():
            kept.setdefault(from_id, set()).update(keys)

    def _targets(
        self,
        row: dict[str, Any],
        instruments: dict[str, Node],
        treaties: dict[str, str],
    ) -> list[tuple[Node, float, dict[str, Any]]]:
        """``(target, confidence, meta)`` of every edge of one judgment: the articles of the
        Convention, of a Protocol (its treaty from *treaties*), and the instruments its
        conclusion names."""
        cited = [
            (ECHR_CONVENTION_BWB_ID, number, paragraphs, None)
            for number, paragraphs in convention_articles(row.get("articles")).items()
        ] + [
            (treaties[protocol], number, paragraphs, protocol)
            for (protocol, number), paragraphs in protocol_articles(
                row.get("articles")
            ).items()
            if protocol in treaties
        ]
        targets: list[tuple[Node, float, dict[str, Any]]] = []
        for bwb_id, number, paragraphs, protocol in cited:
            article = self._cited_article(
                bwb_id,
                number,
                celex=False,
                confidence=CONFIDENCE_ARTICLE,
                min_confidence=CONFIDENCE_ARTICLE,
            )
            if article is not None:
                meta: dict[str, Any] = {
                    "leden": paragraphs,
                    "hudoc_articles": row.get("articles"),
                }
                if protocol:
                    meta["protocol"] = protocol
                targets.append((article, CONFIDENCE_ARTICLE, meta))
        conclusion = row.get("conclusion") or ""
        for bwb_id in sorted(
            {m.group(1).upper() for m in BWB_ID_PATTERN.finditer(conclusion)}
        ):
            if bwb_id in instruments:
                meta = {"match_type": "bwb_text_scan"}
                targets.append((instruments[bwb_id], CONFIDENCE_CONCLUSION, meta))
        return targets

    def _instruments_named(self, rows: list[dict[str, Any]]) -> dict[str, Node]:
        """The instruments whose BWB id a conclusion names, in one query."""
        named = {
            m.group(1).upper()
            for row in rows
            for m in BWB_ID_PATTERN.finditer(row.get("conclusion") or "")
        }
        if not named:
            return {}
        found: dict[str, Node] = {}
        for doc in semantic_bwb.instrument_keys_by_bwb_id(self.store, sorted(named)):
            bwb_id = str((doc.get("props") or {}).get("bwb_id") or "").upper()
            if bwb_id:
                found[bwb_id] = Node(
                    collection=COLLECTION_INSTRUMENTS,
                    type=NodeType.INSTRUMENT,
                    key=doc["_key"],
                    props={},
                )
        return found
