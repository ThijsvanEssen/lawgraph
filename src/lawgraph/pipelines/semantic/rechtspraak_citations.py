"""``REFERS_TO`` between judgments: the ECLIs a judgment names in its text.

Only the text the court or advocate-general wrote is read (``core.judgments.body_text``), never
the metadata: its ``dcterms:relation`` names the earlier instance and the conclusion, which are
the procedural edges ``APPEAL_OF`` and ``ADVISES_ON`` of their own steps, not citations. Two
judgments of one case that such an edge ties (``PROCEDURAL_RELATIONS``, either way) have that
edge only: a Hoge Raad ruling that names the arrest under cassation and the conclusion in a
footnote does not cite them. The procedural steps run before this one. The edges of a judgment
are derived in full each time it is read: one its text no longer supports (made by an earlier
rule) is removed.

The ECLIs are read by ``core.ecli.cited_eclis``: a malformed one is repaired where the text shows
what was meant (a split LJN, NL and the court swapped, a range) and dropped otherwise, so it
makes no stub. A stub judgment no edge reaches any more goes at the end.

A decision before 2013 is cited by its LJN alone ("CRvB 12 januari 2010, LJN BK9271"): the
number of its ECLI (``ECLI:NL:CRVB:2010:BK9271``), unique over the courts. Such an LJN cites the
judgment in the graph whose ECLI has it for its number (``core.ecli.cited_ljns``, ``ljn_of``);
one that no judgment has, or that two have, cites nothing and makes no stub.

A decision of the ECHR is cited by application number ("EHRM 28 maart 2000, nr. 22492/93"):
``REFERS_TO`` to the decision of that number and date, or without a date to the only decision of
the number (``_echr_citations``).

An edge keeps every place in the judgment that names the judgment it cites (by ECLI, LJN or
application number), as a judgment→article edge does (``core.mentions``): ``meta.mentions``,
each with the paragraph (``paragraph_id``, ``paragraph_number``), the ``start`` and ``end`` of
the citation in its text and a ``snippet``; one in a footnote (``core.judgments.judgment_text``)
with the footnote's ``label`` (``footnote``) and offsets into the text of the footnote, its
paragraph the one that refers to it. ``meta.mention_count`` counts them all, ``meta.paragraphs``
lists the numbers of their paragraphs ("4.3", "5.1", as the judgment prints them), so a list of
citing judgments shows where each one cites without reading its text. A judgment named only
outside the first ``<uitspraak>`` or ``<conclusie>`` has no mentions.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from lawgraph.config.constants import (
    EDGE_STATUS_CANONIEK,
    RELATION_ADVISES_ON,
    RELATION_ANSWERS,
    RELATION_APPEAL_OF,
    RELATION_CONTINUES,
    RELATION_REFERRED_BY,
    RELATION_REFERS_TO,
)
from lawgraph.core.echr_citations import Cited, cited_in_dutch, dutch_mentions
from lawgraph.core.ecli import (
    cited_eclis,
    cited_ljns,
    ecli_mentions,
    ljn_mentions,
    ljn_of,
)
from lawgraph.core.judgments import body_text, judgment_text, parse_judgment
from lawgraph.core.logging import get_logger
from lawgraph.core.mentions import MAX_MENTIONS_PER_EDGE, Mention, footnote_paragraphs
from lawgraph.core.models import Node, PipelineResult
from lawgraph.core.time import iso_timestamp
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import rechtspraak as semantic_rechtspraak

from . import _echr_citations
from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "judgment-citation-linker"
# How sure a citation by ECLI is.
CONFIDENCE = 0.95
# The edges that tie two judgments of one case; such a pair is not also a citation.
PROCEDURAL_RELATIONS = (
    RELATION_APPEAL_OF,
    RELATION_CONTINUES,
    RELATION_REFERRED_BY,
    RELATION_ADVISES_ON,
    RELATION_ANSWERS,
)


def cited(text: str, by_ljn: Mapping[str, str]) -> list[str]:
    """The ECLIs *text* cites: those it names, then those of the LJNs it names (*by_ljn*:
    LJN -> the ECLI of the judgment in the graph that has it), once each."""
    ljns = (by_ljn[ljn] for ljn in cited_ljns(text) if ljn in by_ljn)
    return list(dict.fromkeys([*cited_eclis(text), *ljns]))


def judgment_mentions(
    texts: list[dict[str, Any]], by_ljn: Mapping[str, str] | None = None
) -> tuple[dict[str, list[Mention]], dict[str, list[Mention]]]:
    """Where *texts* name the judgments they cite: ``(by ECLI, by application number)``,
    each the places in reading order. *texts* are the paragraphs of a judgment and its
    footnotes as ``core.mentions.footnote_paragraphs`` gives them; an LJN counts for the
    ECLI *by_ljn* gives it."""
    by_ecli: dict[str, list[Mention]] = {}
    by_appno: dict[str, list[Mention]] = {}
    for paragraph in texts:
        text = str(paragraph.get("text") or "")
        named = [
            *ecli_mentions(text),
            *(
                (by_ljn[ljn], start, end)
                for ljn, start, end in ljn_mentions(text)
                if by_ljn and ljn in by_ljn
            ),
        ]
        for ecli, start, end in sorted(named, key=lambda found: found[1]):
            by_ecli.setdefault(ecli, []).append(
                Mention.read(paragraph, text, (start, end), confidence=CONFIDENCE)
            )
        for cited_echr, start, end in dutch_mentions(text):
            sure = _echr_citations.confidence(cited_echr)
            by_appno.setdefault(cited_echr.appno, []).append(
                Mention.read(paragraph, text, (start, end), confidence=sure)
            )
    return by_ecli, by_appno


def places_meta(mentions: list[Mention]) -> dict[str, Any]:
    """The places of a citation as an edge keeps them: ``paragraphs`` (the numbers of their
    paragraphs, each once), ``mentions`` (the first ``MAX_MENTIONS_PER_EDGE``) and
    ``mention_count``; nothing without places."""
    if not mentions:
        return {}
    numbers = [m.paragraph_number for m in mentions if m.paragraph_number]
    return {
        **({"paragraphs": list(dict.fromkeys(numbers))} if numbers else {}),
        "mentions": [m.to_dict(parts=False) for m in mentions[:MAX_MENTIONS_PER_EDGE]],
        "mention_count": len(mentions),
    }


class RechtspraakCitationsSemanticPipeline(SemanticPipelineBase):
    """Detect ECLI cross-references in judgment texts and create REFERS_TO edges."""

    def __init__(
        self, store: Any, *, after: str | None = None, limit: int | None = None
    ) -> None:
        """*after* and *limit*: a slice of a run over all, past that record key, so many
        judgments; the log names the last one read."""
        super().__init__(store)
        # (citing id, cited ECLI) -> the places that name it, as the edge keeps them
        self._places: dict[tuple[str, str], dict[str, Any]] = {}
        # (citing id, application number) -> the same
        self._echr_places: dict[tuple[str, str], dict[str, Any]] = {}
        self._by_ljn: dict[str, str] | None = (
            None  # read once, when a text names an LJN
        )
        self.after = after
        self.limit = limit

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        self._places, self._echr_places = {}, {}
        pending, all_cited_eclis, read, by_appno = self._collect_references(
            iso_timestamp(since)
        )

        logger.info(
            "Found %d ECLI references in the text of %d judgments.",
            len(pending),
            len(read),
        )

        ecli_to_id = self._resolve_eclis(all_cited_eclis) if pending else {}
        tied = self._procedural_pairs(sorted({from_id for from_id, _ in pending}))
        edges = EdgeWriter(self.store, what=None, remembers=True)
        self._emit_edges(pending, ecli_to_id, tied, edges)
        if by_appno:
            _echr_citations.link(
                edges,
                by_appno,
                _echr_citations.decisions_index(self.store),
                source=SEMANTIC_SOURCE,
                places=self._echr_places,
            )
        edges.flush_into(result)
        removed = edges.remove_stale(RELATION_REFERS_TO, SEMANTIC_SOURCE, read)
        logger.info("Removed %d citations the text does not name.", removed)
        stubs = semantic_rechtspraak.remove_unreached_judgment_stubs(self.store)
        logger.info("Removed %d stub judgments no edge reaches.", stubs)
        if self.after or self.limit is not None:
            last = self.last_judgment_read
            logger.info("The last read was %s (go on with --after %s).", last, last)
        self.add_outcomes(result)
        return result

    def _collect_references(
        self, since_iso: str | None = None
    ) -> tuple[list[tuple[str, str]], set[str], list[str], list[tuple[str, Cited]]]:
        """``(citing id, cited ECLI)`` pairs, the ECLIs cited, the ids of every judgment
        whose text was read, and ``(citing id, cited ECHR decision)`` pairs."""
        pending: list[tuple[str, str]] = []
        all_cited_eclis: set[str] = set()
        read: list[str] = []
        by_appno: list[tuple[str, Cited]] = []
        for judgment, xml in self._judgment_texts(
            since_iso, after=self.after, limit=self.limit
        ):
            source_ecli = str(judgment.props["ecli"]).upper()
            try:
                root = parse_judgment(xml)
            except ValueError as exc:
                self.progress.fail("unreadable judgment XML", f"{source_ecli}: {exc}")
                continue
            text = body_text(root)
            if not judgment.node_id:
                continue
            read.append(judgment.node_id)
            by_ljn = self._judgments_by_ljn() if cited_ljns(text) else {}
            paragraphs, footnotes = judgment_text(root)
            by_ecli, by_number = judgment_mentions(
                [*paragraphs, *footnote_paragraphs(paragraphs, footnotes)], by_ljn
            )
            for ecli in cited(text, by_ljn):
                if ecli == source_ecli:
                    continue
                pending.append((judgment.node_id, ecli))
                all_cited_eclis.add(ecli)
                if by_ecli.get(ecli):
                    self._places[(judgment.node_id, ecli)] = places_meta(by_ecli[ecli])
            for echr in cited_in_dutch(text):
                by_appno.append((judgment.node_id, echr))
                if by_number.get(echr.appno):
                    self._echr_places[(judgment.node_id, echr.appno)] = places_meta(
                        by_number[echr.appno]
                    )
        return pending, all_cited_eclis, read, by_appno

    def _judgments_by_ljn(self) -> dict[str, str]:
        """LJN -> the ECLI of the one judgment in the graph whose number it is; an LJN two
        judgments have is left out."""
        if self._by_ljn is None:
            claims: dict[str, list[str]] = {}
            for ecli in semantic_rechtspraak.eclis_with_an_ljn(self.store):
                ljn = ljn_of(str(ecli))
                if ljn:
                    claims.setdefault(ljn, []).append(str(ecli).upper())
            self._by_ljn = {
                ljn: eclis[0] for ljn, eclis in claims.items() if len(eclis) == 1
            }
            logger.info("Read the LJNs of %d judgments.", len(self._by_ljn))
        return self._by_ljn

    def _procedural_pairs(self, ids: list[str]) -> set[tuple[str, str]]:
        """``(id, other)`` for every judgment of *ids* and the judgments a procedural edge
        ties it to."""
        return {
            (row[0], row[1])
            for row in semantic_rechtspraak.procedural_neighbours(
                self.store, ids, list(PROCEDURAL_RELATIONS)
            )
        }

    def _emit_edges(
        self,
        pending: list[tuple[str, str]],
        ecli_to_id: dict[str, str],
        tied: set[tuple[str, str]],
        edges: EdgeWriter,
    ) -> None:
        """Queue the edges, but none between judgments *tied* by a procedural edge."""
        left_out: set[tuple[str, str]] = set()
        for from_id, cited_ecli in pending:
            to_id = ecli_to_id.get(cited_ecli)
            if not to_id:
                continue
            if (from_id, to_id) in tied:
                left_out.add((from_id, to_id))
                continue
            from_coll, from_key = from_id.split("/", 1)
            to_coll, to_key = to_id.split("/", 1)
            from_node = Node(collection=from_coll, key=from_key, props={})
            to_node = Node(collection=to_coll, key=to_key, props={})
            edges.add_doc(
                self._make_edge_doc(
                    from_node=from_node,
                    to_node=to_node,
                    relation=RELATION_REFERS_TO,
                    source=SEMANTIC_SOURCE,
                    confidence=CONFIDENCE,
                    meta={
                        "cited_ecli": cited_ecli,
                        **self._places.get((from_id, cited_ecli), {}),
                    },
                    status=EDGE_STATUS_CANONIEK,
                )
            )
        logger.info(
            "Left out %d citations between judgments tied by a procedural edge.",
            len(left_out),
        )
