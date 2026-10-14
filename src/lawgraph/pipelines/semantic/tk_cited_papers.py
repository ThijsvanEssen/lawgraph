"""Semantic pipeline: the Kamerstukken a paper names, as edges between the papers.

The Kamer files a letter that carries out a motion as a case of its own; its subject names the
motion: "Uitvoering van de motie van het lid Vliegenthart c.s. over … (Kamerstuk
25424-795)" (``core.kamerstuk_refs``). Each paper the subject (else the title) names by
dossier and number gets an edge when it is in the graph, found by its ``dossier_number``,
``dossier_suffix`` and ``sequence``: ``ANSWERS`` from a letter of the government (``Brief
regering``) to a motion, ``REFERS_TO`` otherwise (a list of questions about a letter, the
decision note of a letter, an inbreng on it). ``meta.basis`` is ``subject``; ``meta.text``
of an ``ANSWERS`` the whole subject, of a ``REFERS_TO`` the reference as written, and
``meta.reference`` of both the reference as written.

A letter of the government also names the motions it answers in its text and its footnotes:
"Uw Kamer heeft met de motie van het lid Kathmann¹ …" with the footnote "Kamerstuk 36 764,
nr. 28", or "de motie-Kathmann (36764, nr. 31)" (``kamerstuk_refs.motion_papers``). Each
such paper that is a motion gets ``ANSWERS`` too, unless the subject names it: ``meta.basis``
``text`` or ``footnote``, ``meta.text`` the line or the footnote it stands in (of a long
line the 400 characters around the reference),
``meta.reference`` the reference, confidence 0.9.

With ``--since`` the papers fetched since then, and those whose text was (the poll, the
nightly run); without it every paper, and an edge no longer derived goes (the weekly run).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    RELATION_ANSWERS,
    RELATION_REFERS_TO,
)
from lawgraph.core.kamerstuk_refs import PaperRef, cited_papers, motion_papers
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.core.xml import collapse_ws
from lawgraph.db import EdgeWriter, edge_key
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import tk as semantic_tk

from .base import SemanticPipelineBase

logger = get_logger(__name__)

SEMANTIC_SOURCE = "tk-cited-papers"
BASIS = "subject"
BASIS_TEXT = "text"
BASIS_FOOTNOTE = "footnote"
# An answer read from the text: sure of the motion, less of what the letter does with it.
TEXT_CONFIDENCE = 0.9
RELATIONS = (RELATION_ANSWERS, RELATION_REFERS_TO)
# The kind of a letter of the government, and the kinds of a motion start with "Motie"
# ("Motie", "Motie (gewijzigd/nader)").
LETTER_OF_GOVERNMENT = "Brief regering"
MOTION = "Motie"

PaperKey = tuple[str, str, int]  # dossier number, suffix ("" for none), sequence


@dataclass(frozen=True)
class NamedInText:
    """A paper the text (a line) or a footnote of a letter names."""

    letter: str
    ref: PaperRef
    basis: str
    place: str


Kept = dict[str, dict[str, set[str]]]  # relation -> paper -> keys of its edges


def relation_of(source_kind: str | None, target_kind: str | None) -> str:
    """``ANSWERS`` from a letter of the government to a motion, else ``REFERS_TO``."""
    if source_kind == LETTER_OF_GOVERNMENT and (target_kind or "").startswith(MOTION):
        return RELATION_ANSWERS
    return RELATION_REFERS_TO


# The characters of a line kept in ``meta.text``: a paragraph of a letter may be long.
PASSAGE_CHARS = 400


def passage(line: str, reference: str) -> str:
    """*line* in one line, or of a longer one the ``PASSAGE_CHARS`` around *reference*,
    cut at words, with an ellipsis where it was cut."""
    text = collapse_ws(line)
    if len(text) <= PASSAGE_CHARS:
        return text
    at = max(text.find(collapse_ws(reference)), 0)
    start = max(0, min(at - PASSAGE_CHARS // 2, len(text) - PASSAGE_CHARS))
    end = start + PASSAGE_CHARS
    head = "…" if start else ""
    tail = "…" if end < len(text) else ""
    body = text[start:end]
    if start:
        body = body.split(" ", 1)[-1]
    if tail:
        body = body.rsplit(" ", 1)[0]
    return f"{head}{body}{tail}"


def _key(ref: PaperRef) -> PaperKey:
    return (ref.number, (ref.suffix or "").upper(), ref.sequence)


class TKCitedPapersSemanticPipeline(SemanticPipelineBase):
    """``ANSWERS`` and ``REFERS_TO`` to the Kamerstukken a paper's subject names, and
    ``ANSWERS`` to the motions a letter of the government names in its text."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        ids = self._fetched_since(since)
        logger.info("Kamerstukken named in subjects (since=%s).", describe_since(since))
        dossiers = semantic_tk.dossier_labels(self.store)

        def is_dossier(number: str, suffix: str | None) -> bool:
            return f"{number}-{suffix}" in dossiers

        named: list[tuple[dict[str, Any], PaperRef]] = []
        for row in self._track(
            semantic_tk.papers_naming_kamerstukken(self.store, ids), "papers"
        ):
            named += [(row, ref) for ref in cited_papers(row["subject"], is_dossier)]

        in_text = self._named_in_text(ids, is_dossier)
        found = {
            (row["number"], row["suffix"], int(row["sequence"])): row
            for row in semantic_tk.papers_by_number(
                self.store,
                sorted(
                    {_key(ref) for _, ref in named} | {_key(n.ref) for n in in_text}
                ),
            )
        }
        kept, written = self._write(named, found, result)
        self._write_answers_in_text(in_text, named, found, kept, written, result)
        removed = self._remove_stale(kept, ids)
        result.skipped += written["not found"]
        logger.info(
            "Kamerstukken named: %d in %d papers; %s; removed %d.",
            len(named),
            len({row["id"] for row, _ in named}),
            ", ".join(f"{count} {what}" for what, count in sorted(written.items())),
            removed,
        )
        return result

    def _fetched_since(self, since: dt.datetime | None) -> list[str] | None:
        """The ids of the papers of the Tweede Kamer fetched since *since*, or whose text
        was; ``None`` for every paper."""
        since_iso = iso_timestamp(since)
        if since_iso is None:
            return None
        return sorted(
            {
                f"{COLLECTION_DOCUMENTS}/{make_node_key(str(guid))}"
                for guid in raw_queries.tk_document_ids_fetched_since(
                    self.store, since_iso
                )
            }
            | {
                f"{COLLECTION_DOCUMENTS}/{key}"
                for key in raw_queries.tk_papers_with_xml_fetched_since(
                    self.store, since_iso
                )
            }
        )

    def _named_in_text(
        self, ids: list[str] | None, is_dossier: Callable[[str, str | None], bool]
    ) -> list[NamedInText]:
        """The papers each letter of the government names in its text and footnotes."""
        named: list[NamedInText] = []
        for row in self._track(
            semantic_tk.letters_naming_motions(self.store, LETTER_OF_GOVERNMENT, ids),
            "letters",
        ):
            places = [(BASIS_TEXT, line) for line in str(row["text"] or "").split("\n")]
            places += [
                (BASIS_FOOTNOTE, str(note.get("text") or ""))
                for note in row.get("footnotes") or []
                if isinstance(note, dict)
            ]
            for basis, place in places:
                named += [
                    NamedInText(str(row["id"]), ref, basis, place)
                    for ref in motion_papers(place, is_dossier)
                ]
        return named

    def _write(
        self,
        named: Iterable[tuple[dict[str, Any], PaperRef]],
        found: dict[PaperKey, dict[str, Any]],
        result: PipelineResult,
    ) -> tuple[Kept, Counter[str]]:
        """Write an edge for every paper named that is in the graph; the keys kept per
        relation and paper, and how many of each relation and how many not found."""
        kept: Kept = {relation: {} for relation in RELATIONS}
        written: Counter[str] = Counter()
        edges = EdgeWriter(self.store, what=None)
        for row, ref in named:
            target = found.get(_key(ref))
            if target is None:
                written["not found"] += 1
                continue
            source_id, target_id = str(row["id"]), str(target["id"])
            if source_id == target_id:
                continue
            relation = relation_of(row.get("kind"), target.get("kind"))
            # of an answer the whole subject: what the letter says it does with the motion
            text = row["subject"] if relation == RELATION_ANSWERS else ref.text
            edges.add(
                source_id,
                target_id,
                relation,
                source=SEMANTIC_SOURCE,
                confidence=1.0,
                meta={"basis": BASIS, "text": text, "reference": ref.text},
            )
            key = edge_key(source_id, relation, target_id)
            if key not in kept[relation].setdefault(source_id, set()):
                kept[relation][source_id].add(key)
                written[relation] += 1
        edges.flush_into(result)
        return kept, written

    def _write_answers_in_text(
        self,
        in_text: list[NamedInText],
        named: list[tuple[dict[str, Any], PaperRef]],
        found: dict[PaperKey, dict[str, Any]],
        kept: Kept,
        written: Counter[str],
        result: PipelineResult,
    ) -> None:
        """``ANSWERS`` from a letter to each motion its text or footnotes name that its
        subject does not, once per letter and motion (the first place it is named)."""
        by_subject = {
            (str(row["id"]), _key(ref)) for row, ref in named if _key(ref) in found
        }
        edges = EdgeWriter(self.store, what=None)
        done: set[tuple[str, PaperKey]] = set()
        for item in in_text:
            target = found.get(_key(item.ref))
            pair = (item.letter, _key(item.ref))
            if (
                target is None
                or pair in by_subject
                or pair in done
                or target["id"] == item.letter
                or relation_of(LETTER_OF_GOVERNMENT, target.get("kind"))
                != RELATION_ANSWERS
            ):
                continue
            done.add(pair)
            edges.add(
                item.letter,
                str(target["id"]),
                RELATION_ANSWERS,
                source=SEMANTIC_SOURCE,
                confidence=TEXT_CONFIDENCE,
                meta={
                    "basis": item.basis,
                    "text": passage(item.place, item.ref.text),
                    "reference": item.ref.text,
                },
            )
            key = edge_key(item.letter, RELATION_ANSWERS, str(target["id"]))
            kept[RELATION_ANSWERS].setdefault(item.letter, set()).add(key)
            written[f"{RELATION_ANSWERS} from the text"] += 1
        edges.flush_into(result)

    def _remove_stale(self, kept: Kept, ids: list[str] | None) -> int:
        """Remove the edges of this step no longer derived: of the papers *ids*, or of
        every paper when it is ``None``."""
        removed = 0
        for relation, per_paper in kept.items():
            if ids is None:
                removed += semantic_edges.remove_edges_of_source_except(
                    self.store,
                    relation,
                    SEMANTIC_SOURCE,
                    sorted(key for keys in per_paper.values() for key in keys),
                )
            else:
                removed += semantic_edges.remove_edges_from(
                    self.store, relation, SEMANTIC_SOURCE, ids, per_paper
                )
        return removed
