"""Semantic pipeline that detects legislative amendment language in TK documents.

A bill (Document) that says it changes an article gets an AMENDS / INTRODUCES /
REPEALS edge to that article with status ``voorgesteld``: the change is proposed,
not yet law. The instrument that eventually enacts it carries the canonical edge,
written by ``bwb_amendments`` from the BWB metadata.

A paper that changes one law changes it wherever its text says so. A paper that changes
several (a verzamelwet) changes each in its own wijzigingsartikel (``ARTIKEL I``,
``ARTIKEL II`` …, the roman ``article`` sections of the paper): the articles a part names go
to the law it names first; a part that names none of the paper's laws changes none of them.

Not to an article of the act the paper's own dossier made (the instrument ``LEGISLATED_IN``
it): the bill, its memorandum, a nota van wijziging and its amendments make that act, they do
not change it. The edges are derived in full on every run; one no longer derived goes.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    EDGE_STATUS_VOORGESTELD,
    RELATION_AMENDS,
    RELATION_INTRODUCES,
    RELATION_REPEALS,
)
from lawgraph.core.citations import CitationHit, make_snippet, strip_xml
from lawgraph.core.kamerstuk_xml import KIND_ARTICLE, SCHEME_ROMAN
from lawgraph.core.logging import get_logger
from lawgraph.core.models import Node, PipelineResult, make_node_key
from lawgraph.db import EdgeWriter
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.queries.semantic import tk as semantic_tk
from lawgraph.pipelines.semantic.base import SemanticPipelineBase
from lawgraph.pipelines.semantic.tk import NamedActs

logger = get_logger(__name__)

SEMANTIC_SOURCE = "amendment-article-linker"

# ---------------------------------------------------------------------------
# Regex patterns for Dutch legislative amendment boilerplate
# ---------------------------------------------------------------------------

# Optional comma-separated lid/onderdeel modifiers between an article number
# and the verb that signals the amendment kind. Matches the Dutch
# wetstechniek conventions used in voorstellen-van-wet:
#   "Artikel 36f, eerste lid, komt te luiden:"
#   "Artikel 36i, eerste lid, onder d, vervalt."
#   "Artikel 5, tweede lid, wordt als volgt gewijzigd:"
# The non-greedy ``{0,3}`` cap on repeats prevents runaway scans without
# losing realistic depth (lid + onderdeel + sub-onderdeel).
_LID_ONDERDEEL = r"(?:\s*,\s+[^,.\n]{1,60}){0,3}\s*,?"

# "Artikel 5 wordt als volgt gewijzigd:" / "Artikel 5, eerste lid, wordt gewijzigd"
_WORDT_GEWIJZIGD = re.compile(
    r"\bArtikel\s+(\d+[a-z]*)"
    + _LID_ONDERDEEL
    + r"\s+(?:van\s+(?:de\s+)?(?:wet|het\s+wetboek|het\s+besluit)"
    + r"\s+[^,\n]{0,60}\s+)?wordt\s+(?:als\s+volgt\s+)?gewijzigd",
    re.IGNORECASE,
)

# "Na artikel 5 wordt een artikel ingevoegd" / "een nieuw artikel 5a ingevoegd"
_WORDT_INGEVOEGD = re.compile(
    r"\b(?:Na|In)\s+artikel\s+(\d+[a-z]*)\s+wordt\s+een\s+(?:nieuw\s+)?artikel\s+(\d+[a-z]*)\s+ingevoegd",
    re.IGNORECASE,
)

# "Artikel 5 vervalt" / "Artikel 5, eerste lid, onder d, vervalt" / "komt te vervallen"
_VERVALT = re.compile(
    r"\bArtikel\s+(\d+[a-z]*)"
    + _LID_ONDERDEEL
    + r"\s+(?:komt\s+te\s+)?verval(?:t|len)\b",
    re.IGNORECASE,
)

# "Artikel 5 komt te luiden:" / "Artikel 36f, eerste lid, komt te luiden:"
_KOMT_TE_LUIDEN = re.compile(
    r"\bArtikel\s+(\d+[a-z]*)" + _LID_ONDERDEEL + r"\s+komt\s+te\s+luiden\b",
    re.IGNORECASE,
)

# "In artikel 5 wordt 'X' vervangen door 'Y'" / "In artikel 5, derde lid, wordt..."
_VERVANGEN_DOOR = re.compile(
    r"\bIn\s+artikel\s+(\d+[a-z]*)" + _LID_ONDERDEEL + r"\s+wordt\b",
    re.IGNORECASE,
)

# Grouped: (pattern, article_group_index, relation, confidence)
_AMENDMENT_PATTERNS: list[tuple[re.Pattern[str], int, str, float]] = [
    (_WORDT_GEWIJZIGD, 1, RELATION_AMENDS, 0.90),
    (_WORDT_INGEVOEGD, 2, RELATION_INTRODUCES, 0.85),
    (_KOMT_TE_LUIDEN, 1, RELATION_AMENDS, 0.85),
    (_VERVALT, 1, RELATION_REPEALS, 0.80),
    (_VERVANGEN_DOOR, 1, RELATION_AMENDS, 0.80),
]


class AmendmentHit(NamedTuple):
    """An article a text says it changes, and how."""

    article_number: str
    relation: str
    confidence: float
    snippet: str


def detect_amendment_citations(text: str) -> list[AmendmentHit]:
    """The articles *text* says it changes, each with a relation once: the surest wording
    that says so."""
    hits: list[AmendmentHit] = []
    seen: set[tuple[str, str]] = set()
    for pattern, article_group, relation, confidence in _AMENDMENT_PATTERNS:
        for match in pattern.finditer(text):
            article_number = match.group(article_group)
            if (article_number, relation) in seen:
                continue
            seen.add((article_number, relation))
            hits.append(
                AmendmentHit(
                    article_number,
                    relation,
                    confidence,
                    make_snippet(text, match.span()),
                )
            )
    return hits


def amendments_per_law(
    props: Mapping[str, Any], laws: Sequence[str], named_acts: NamedActs
) -> dict[str, list[AmendmentHit]]:
    """BWB id -> the articles of that law the paper (*props*: its ``text`` and ``sections``)
    says it changes, for the *laws* it amends (see the module docstring)."""
    if len(laws) == 1:
        return {laws[0]: detect_amendment_citations(strip_xml(str(props["text"])))}
    texts: dict[str, list[str]] = {}
    for part in _wijzigingsartikelen(str(props["text"]), props.get("sections") or ()):
        law = _first_law_named(part, laws, named_acts)
        if law is not None:
            texts.setdefault(law, []).append(part)
    return {
        law: detect_amendment_citations(" ".join(parts)) for law, parts in texts.items()
    }


def _wijzigingsartikelen(text: str, sections: Iterable[Mapping[str, Any]]) -> list[str]:
    """The text of each wijzigingsartikel, from its heading to the next one (a heading
    ``ARTIKEL I, onderdeel B`` right after ``ARTIKEL I`` is still that article); the whole
    text without any."""
    heads = [
        (section["number"], section["char_start"])
        for section in sections
        if section["kind"] == KIND_ARTICLE and section["number_scheme"] == SCHEME_ROMAN
    ]
    starts = [
        start
        for index, (number, start) in enumerate(heads)
        if index == 0 or heads[index - 1][0] != number
    ]
    if not starts:
        return [strip_xml(text)]
    bounds = [*starts, len(text)]
    return [strip_xml(text[start:end]) for start, end in itertools.pairwise(bounds)]


def _first_law_named(
    part: str, laws: Sequence[str], named_acts: NamedActs
) -> str | None:
    """Of *laws*, the one *part* names first; None when it names none of them."""
    named: list[CitationHit] = []
    named_acts.collect_hits(part, named.append)
    first = min(
        (hit for hit in named if hit.bwb_id in laws),
        key=lambda hit: hit.start or 0,
        default=None,
    )
    return first.bwb_id if first else None


class TKAmendmentArticlesSemanticPipeline(SemanticPipelineBase):
    """Detect amendment language and create AMENDS/INTRODUCES/REPEALS edges."""

    def run(self) -> PipelineResult:
        """Scan TK documents for amendment language and create semantic edges."""
        result = PipelineResult()
        amends_index = self._load_amends_instrument_index()
        logger.info(
            "Scanning TK documents for amendment language "
            "(%d with an amended-instrument context).",
            len(amends_index),
        )

        edges = EdgeWriter(self.store, what=None)
        kept: list[str] = []
        acts = semantic_tk.acts_of_dossiers(self.store)
        named_acts = NamedActs(self._load_instrument_aliases())

        documents = self._load_tk_documents(amends_index)
        for document in self._track(documents, "TK documents"):
            own_acts = semantic_tk.own_acts(acts, document.props)
            laws = [
                bwb_id
                for bwb_id in self._laws_of(document, amends_index)
                if f"{COLLECTION_INSTRUMENTS}/{make_node_key(bwb_id)}" not in own_acts
            ]
            if not laws:
                result.skipped += 1
                continue
            for bwb_id, hits in amendments_per_law(
                document.props, laws, named_acts
            ).items():
                for hit in hits:
                    key = make_node_key(bwb_id, hit.article_number)
                    target_node = self._lookup_node(COLLECTION_ARTICLES, key)
                    if target_node is None:
                        logger.debug(
                            "Amendment scanner: no article node found for key=%s — skipping.",
                            key,
                        )
                        continue
                    edge_doc = self._make_edge_doc(
                        from_node=document,
                        to_node=target_node,
                        relation=hit.relation,
                        source=SEMANTIC_SOURCE,
                        confidence=hit.confidence,
                        meta={"reason": "amendment_text", "snippet": hit.snippet},
                        status=EDGE_STATUS_VOORGESTELD,
                    )
                    if edge_doc:
                        edges.add_doc(edge_doc)
                        kept.append(edge_doc["_key"])

        edges.flush_into(result)
        removed = sum(
            semantic_edges.remove_edges_of_source_except(
                self.store, relation, SEMANTIC_SOURCE, kept
            )
            for relation in (RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS)
        )
        logger.info("Removed %d article changes no longer derived.", removed)
        return result

    def _load_tk_documents(self, amends_index: dict[str, list[str]]) -> Iterable[Node]:
        """The TK documents that can hold an amendment: those with a text, and with a law to
        amend (their own ``bwb_id`` or an AMENDS edge). Every other document was read to be
        skipped: 10,085 of 10,085 in a three-week Tweede Kamer."""
        rows = semantic_tk.tk_documents_to_scan_for_amendments(
            self.store, sorted(amends_index)
        )
        for doc in rows:
            yield Node.from_document(COLLECTION_DOCUMENTS, doc)

    def _load_amends_instrument_index(self) -> dict[str, list[str]]:
        """Document id -> the BWB ids of the instruments it AMENDS (``semantic tk-amends``,
        from its title), once for the run."""
        index: dict[str, list[str]] = {}
        for row in semantic_tk.amended_instruments(self.store):
            bucket = index.setdefault(str(row["document_id"]), [])
            bwb_id = str(row["bwb_id"]).strip()
            if bwb_id not in bucket:
                bucket.append(bwb_id)
        return index

    @staticmethod
    def _laws_of(document: Node, amends_index: dict[str, list[str]]) -> list[str]:
        """The BWB ids of the laws *document* amends: its own ``props.bwb_id``, then those
        it AMENDS."""
        own = str(document.props.get("bwb_id") or "").strip()
        amended = amends_index.get(document.node_id or "", [])
        return list(dict.fromkeys(filter(None, [own, *amended])))
