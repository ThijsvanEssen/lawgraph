"""Semantic pipeline: the Kamerstukken a document names, as edges between the documents.

The Kamer files a letter that carries out a motion as a case of its own; its subject names the
motion: "Uitvoering van de motie van het lid Vliegenthart c.s. over … (Kamerstuk
25424-795)" (``core.document_refs``). Each document the subject (else the title) names by
dossier and number gets an edge when it is in the graph, found by its ``dossier_number``,
``dossier_suffix`` and ``sequence``: ``ANSWERS`` from a letter of the government (``Brief
regering``) to a motion, ``REFERS_TO`` otherwise (a list of questions about a letter, the
decision note of a letter, an inbreng on it). ``meta.basis`` is ``subject``; ``meta.text``
of a ``REFERS_TO`` the reference as written, of an ``ANSWERS`` the whole subject with
``meta.reference`` the reference as written.

A letter of the government also names the motions it answers in its text and its footnotes:
"Uw Kamer heeft met de motie van het lid Kathmann¹ …" with the footnote "Kamerstuk 36 764,
nr. 28", or "de motie-Kathmann (36764, nr. 31)" (``document_refs.motion_documents``). Each
such document that is a motion gets ``ANSWERS`` too, unless the subject names it: ``meta.basis``
``text`` or ``footnote``, ``meta.text`` the line or the footnote it stands in (of a long
line the 400 characters around the reference),
``meta.reference`` the reference, confidence 0.9.

With ``--since`` the documents fetched since then, and those whose text was (the poll, the
nightly run); without it every document, and an edge no longer derived goes (the weekly run).
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
from lawgraph.core.document_refs import DocumentRef, cited_documents, motion_documents
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult, make_node_key, node_id
from lawgraph.core.provenance import BASIS_FOOTNOTE, BASIS_SUBJECT, BASIS_TEXT
from lawgraph.core.time import describe_since, iso_timestamp
from lawgraph.core.tk_records.dossiers import dossier_label
from lawgraph.core.tk_records.kinds import KIND_GOVERNMENT_LETTER, is_motion
from lawgraph.core.xml import collapse_ws
from lawgraph.db import EdgeWriter
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.semantic import tk as semantic_tk
from lawgraph.sources.addresses import edge_source

from .base import EXACT_CONFIDENCE, SemanticPipelineBase

logger = get_logger(__name__)

EDGE_SOURCE = edge_source(__name__)
# An answer read from the text: sure of the motion, less of what the letter does with it.
TEXT_CONFIDENCE = 0.9
RELATIONS = (RELATION_ANSWERS, RELATION_REFERS_TO)

DocumentKey = tuple[str, str, int]  # dossier number, suffix ("" for none), sequence


@dataclass(frozen=True)
class NamedInText:
    """A document the text (a line) or a footnote of a letter names."""

    letter: str
    ref: DocumentRef
    basis: str
    place: str


def relation_of(source_kind: str | None, target_kind: str | None) -> str:
    """``ANSWERS`` from a letter of the government to a motion, else ``REFERS_TO``."""
    if source_kind == KIND_GOVERNMENT_LETTER and is_motion(target_kind):
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


def _key(ref: DocumentRef) -> DocumentKey:
    return (ref.number, (ref.suffix or "").upper(), ref.sequence)


class TKCitedPapersSemanticPipeline(SemanticPipelineBase):
    """``ANSWERS`` and ``REFERS_TO`` to the Kamerstukken a document's subject names, and
    ``ANSWERS`` to the motions a letter of the government names in its text."""

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        result = PipelineResult()
        ids = self._fetched_since(since)
        logger.info("Kamerstukken named in subjects (since=%s).", describe_since(since))
        dossiers = semantic_tk.dossier_labels(self.store)

        def is_dossier(number: str, suffix: str | None) -> bool:
            return dossier_label(number, suffix) in dossiers

        named: list[tuple[dict[str, Any], DocumentRef]] = []
        for row in self._track(
            semantic_tk.documents_naming_kamerstukken(self.store, ids), "papers"
        ):
            named += [(row, ref) for ref in cited_documents(row["subject"], is_dossier)]

        in_text = self._named_in_text(ids, is_dossier)
        found = {
            (row["number"], row["suffix"], int(row["sequence"])): row
            for row in semantic_tk.documents_by_number(
                self.store,
                sorted(
                    {_key(ref) for _, ref in named} | {_key(n.ref) for n in in_text}
                ),
            )
        }
        edges = EdgeWriter(self.store, what=None, remembers=True)
        written = self._write(named, found, edges)
        written += self._write_answers_in_text(in_text, named, found, edges)
        edges.flush_into(result)
        removed = self._remove_stale(edges, ids)
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
        """The ids of the documents of the Tweede Kamer fetched since *since*, or whose text
        was; ``None`` for every document."""
        since_iso = iso_timestamp(since)
        if since_iso is None:
            return None
        return sorted(
            {
                node_id(COLLECTION_DOCUMENTS, make_node_key(str(guid)))
                for guid in raw_queries.tk_document_ids_fetched_since(
                    self.store, since_iso
                )
            }
            | {
                node_id(COLLECTION_DOCUMENTS, key)
                for key in raw_queries.tk_documents_with_xml_fetched_since(
                    self.store, since_iso
                )
            }
        )

    def _named_in_text(
        self, ids: list[str] | None, is_dossier: Callable[[str, str | None], bool]
    ) -> list[NamedInText]:
        """The documents each letter of the government names in its text and footnotes."""
        named: list[NamedInText] = []
        for row in self._track(
            semantic_tk.letters_naming_motions(self.store, KIND_GOVERNMENT_LETTER, ids),
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
                    for ref in motion_documents(place, is_dossier)
                ]
        return named

    def _write(
        self,
        named: Iterable[tuple[dict[str, Any], DocumentRef]],
        found: dict[DocumentKey, dict[str, Any]],
        edges: EdgeWriter,
    ) -> Counter[str]:
        """Queue an edge for every document named that is in the graph; how many of each
        relation and how many not found."""
        written: Counter[str] = Counter()
        for row, ref in named:
            target = found.get(_key(ref))
            if target is None:
                written["not found"] += 1
                continue
            source_id, target_id = str(row["id"]), str(target["id"])
            if source_id == target_id:
                continue
            relation = relation_of(row.get("kind"), target.get("kind"))
            meta = {"basis": BASIS_SUBJECT, "text": ref.text}
            if relation == RELATION_ANSWERS:
                # the whole subject, what the letter says it does with the motion, and in it
                # the reference as written
                meta.update(text=row["subject"], reference=ref.text)
            edges.add(
                source_id,
                target_id,
                relation,
                source=EDGE_SOURCE,
                confidence=EXACT_CONFIDENCE,
                meta=meta,
            )
        written.update({r: n for r in RELATIONS if (n := edges.written(r))})
        return written

    def _write_answers_in_text(
        self,
        in_text: list[NamedInText],
        named: list[tuple[dict[str, Any], DocumentRef]],
        found: dict[DocumentKey, dict[str, Any]],
        edges: EdgeWriter,
    ) -> Counter[str]:
        """Queue ``ANSWERS`` from a letter to each motion its text or footnotes name that
        its subject does not, once per letter and motion (the first place it is named);
        how many."""
        by_subject = {
            (str(row["id"]), _key(ref)) for row, ref in named if _key(ref) in found
        }
        done: set[tuple[str, DocumentKey]] = set()
        for item in in_text:
            target = found.get(_key(item.ref))
            pair = (item.letter, _key(item.ref))
            if (
                target is None
                or pair in by_subject
                or pair in done
                or target["id"] == item.letter
                or not is_motion(target.get("kind"))
            ):
                continue
            done.add(pair)
            edges.add(
                item.letter,
                str(target["id"]),
                RELATION_ANSWERS,
                source=EDGE_SOURCE,
                confidence=TEXT_CONFIDENCE,
                meta={
                    "basis": item.basis,
                    "text": passage(item.place, item.ref.text),
                    "reference": item.ref.text,
                },
            )
        return Counter({f"{RELATION_ANSWERS} from the text": len(done)})

    @staticmethod
    def _remove_stale(edges: EdgeWriter, ids: list[str] | None) -> int:
        """Remove the edges of this step no longer derived: of the documents *ids*, or of
        every document when it is ``None``."""
        if ids is None:
            return sum(
                edges.remove_stale_of_source(relation, EDGE_SOURCE)
                for relation in RELATIONS
            )
        return sum(
            edges.remove_stale(relation, EDGE_SOURCE, ids) for relation in RELATIONS
        )
