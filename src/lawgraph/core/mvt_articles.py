"""Which article of a law a section of an explanatory memorandum explains, pure.

The artikelsgewijs part of a memorandum (``props.sections`` of a Document, see
``core/kamerstuk_xml.py``) has a heading per article of the bill and a toelichting under it. What
that toelichting is about is written in the paper: in a new law the article of the bill *is* the
article of the law; in a law that changes other laws, the words say which article of which law
("Artikel I, onderdeel B (artikel 1a)", "artikel 2 van de Tijdelijke wet Klimaatfonds").
``find_references`` reads the words; ``explained_targets`` matches them with what the dossier
changed, which the graph records.

A section that names no article of a law the dossier is about has no reference: the dossier-level
edges of ``semantic tk-mvt`` are all the graph knows for it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    RELATION_INTRODUCES,
)
from lawgraph.core.citations import DutchCitationExtractor
from lawgraph.core.kamerstuk_xml import (
    KIND_ARTICLE,
    KIND_PARAGRAPH,
    KIND_PART,
    OF_NAMED_LAW,
    OF_SELF,
    OF_UNKNOWN,
    SCHEME_ARABIC,
    SCHEME_BOOK_ARTICLE,
)
from lawgraph.core.models import make_node_key

# How a section came to name an article. The confidences are a first estimate, not measured:
# there is no set of labelled sections to calibrate them on.
#
# ``own_number``: in a new law the toelichting of "Artikel 5" is about article 5 of that law.
# The heading is the whole evidence and it is a convention, so it is the surest of the
# structural rules, but a nota van wijziging can insert articles and shift the numbers, and the
# graph does not say so.
MATCH_OWN_NUMBER = "own_number"
CONFIDENCE_OWN_NUMBER = 0.8
# ``heading_target``: the heading itself says which article it explains ("Artikel I, onderdeel
# B (artikel 1a)", "Onderdeel A (artikel 3 van de Woningwet)"): the author's own statement.
MATCH_HEADING_TARGET = "heading_target"
CONFIDENCE_HEADING_TARGET = 0.9
# ``body_named_law``: the text under the heading says "artikel N van de <Law>" and the law is
# one the dossier changed. The text may also refer to an article it does not explain, but the
# article must be one the dossier changed as well.
MATCH_BODY_NAMED_LAW = "body_named_law"
CONFIDENCE_BODY_NAMED_LAW = 0.85
# ``inferred_law``: an article number without a law ("de wijziging van artikel 2"), of the law
# the enclosing heading names or of the only law the dossier changes. Two guesses in a row.
MATCH_INFERRED_LAW = "inferred_law"
CONFIDENCE_INFERRED_LAW = 0.7

CONFIDENCE_OF_MATCH = {
    MATCH_OWN_NUMBER: CONFIDENCE_OWN_NUMBER,
    MATCH_HEADING_TARGET: CONFIDENCE_HEADING_TARGET,
    MATCH_BODY_NAMED_LAW: CONFIDENCE_BODY_NAMED_LAW,
    MATCH_INFERRED_LAW: CONFIDENCE_INFERRED_LAW,
}

# What a heading states, against what a sentence in the body may mention in passing: a target
# that the dossier did not change is still one when the heading names it.
_STATED_MATCHES = frozenset({MATCH_OWN_NUMBER, MATCH_HEADING_TARGET})

# Only the opening of a body is read for an article number without its law: further on the
# numbers are those of provisions that are discussed, not changed.
_OPENING_CHARS = 600

# The sections that explain an article: the heading of one, and what stands under it.
_ARTICLE_KINDS = frozenset({KIND_ARTICLE, KIND_PART, KIND_PARAGRAPH})
_NUMBER_SCHEMES = frozenset({SCHEME_ARABIC, SCHEME_BOOK_ARTICLE})

_BOOK_OF_RE = re.compile(
    r"^(?P<book>boek\s+\d+[a-z]?)\s+van\s+(?:het\s+|de\s+)?(?P<law>.+)$", re.IGNORECASE
)
_LEADING_ARTICLE_RE = re.compile(r"^(?:de|het)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Law:
    """A law the dossier changes, with the names a memorandum calls it by."""

    bwb_id: str
    names: tuple[str, ...]  # title and citation title
    codes: tuple[str, ...] = ()  # the short title ("Awb")


@dataclass(frozen=True)
class Change:
    """An article the dossier changed, as the change edge of the amending publication says."""

    bwb_id: str
    number: str
    article: str  # ``articles/<key>``
    version: str | None  # key of the ArticleVersion the change created
    relation: str

    @property
    def target(self) -> str:
        """The node an edge points at: the version when the change names one."""
        if self.version:
            return f"{COLLECTION_ARTICLE_VERSIONS}/{self.version}"
        return self.article


@dataclass(frozen=True)
class Reference:
    """A section that names an article of a law."""

    section_id: str
    heading: str
    level: int | None
    char_start: int
    char_end: int
    bwb_id: str
    number: str
    match_type: str

    @property
    def confidence(self) -> float:
        return CONFIDENCE_OF_MATCH[self.match_type]


def number_key(number: str) -> str:
    """An article number as compared: ``1A`` and ``1a.`` are one article."""
    return number.strip(" .").lower()


def _number_keys(number: str) -> list[str]:
    """The numbers an article may be stored under: a book's articles have no book."""
    key = number_key(number)
    return [key, key.split(":", 1)[1]] if ":" in key else [key]


def article_id(bwb_id: str, number: str) -> str:
    return f"{COLLECTION_ARTICLES}/{make_node_key(bwb_id, number)}"


# ── the laws a dossier changes ───────────────────────────────────────────────


def _name_keys(name: str) -> list[str]:
    """A law name as compared: lower case, single spaces, without its determiner; a book of
    a code as it is titled ("Boek 7 van het Burgerlijk Wetboek" is "Burgerlijk Wetboek Boek 7")."""
    name = re.sub(r"\s+", " ", name).strip(" .,;:\"'“”‘’()")
    keys = [_LEADING_ARTICLE_RE.sub("", name).lower()]
    book = _BOOK_OF_RE.match(name)
    if book:
        keys.append(f"{book['law']} {book['book']}".lower())
    return keys


class _Registry:
    """The names of the laws of one dossier, and the law each one is."""

    def __init__(self, laws: Sequence[Law]) -> None:
        names: dict[str, str] = {}
        ambiguous: set[str] = set()
        for law in laws:
            for name in law.names:
                for key in _name_keys(name):
                    if names.setdefault(key, law.bwb_id) != law.bwb_id:
                        ambiguous.add(key)
        # A name two laws share names neither.
        self.names = {k: v for k, v in names.items() if k not in ambiguous}
        self.codes = {code: law.bwb_id for law in laws for code in law.codes}
        ids = {law.bwb_id for law in laws}
        self.sole = next(iter(ids)) if len(ids) == 1 else None
        self.extractor = DutchCitationExtractor(self.codes, self.names)

    def resolve(self, name: str | None) -> str | None:
        if not name:
            return None
        for key in _name_keys(name):
            if key in self.names:
                return self.names[key]
        return self.codes.get(name.strip().upper())


# ── the sections ─────────────────────────────────────────────────────────────


class _Outline:
    """The sections of a paper: their parents, and where their own text ends."""

    def __init__(self, sections: Sequence[Mapping[str, Any]]) -> None:
        self.by_id = {str(s["id"]): s for s in sections}
        first_child: dict[str, int] = {}
        for section in sections:
            parent = section.get("parent")
            if parent is not None:
                first_child.setdefault(str(parent), int(section["char_start"]))
        self._first_child = first_child

    def own_end(self, section: Mapping[str, Any]) -> int:
        """Where the text of the section itself ends: before the line of its first subsection."""
        child = self._first_child.get(str(section["id"]))
        return int(section["char_end"]) if child is None else child - 1

    def has_children(self, section: Mapping[str, Any]) -> bool:
        return str(section["id"]) in self._first_child

    def context_law(
        self, section: Mapping[str, Any], registry: _Registry
    ) -> str | None:
        """The law the section is about: the one the nearest heading names, else the only one
        the dossier changes. A law that is named and not known is no reason to guess."""
        node: Mapping[str, Any] | None = section
        while node is not None:
            if node.get("law"):
                return registry.resolve(str(node["law"]))
            parent = node.get("parent")
            node = self.by_id.get(str(parent)) if parent is not None else None
        return registry.sole


def _span(
    section: Mapping[str, Any], outline: _Outline, match_type: str
) -> tuple[int, int]:
    """The passage of a section. A heading that names an article speaks for everything under
    it; a sentence in the body speaks for the text before the first subsection."""
    start, end = int(section["char_start"]), int(section["char_end"])
    if match_type not in _STATED_MATCHES and outline.has_children(section):
        return start, outline.own_end(section)
    return start, end


def _body(text: str, section: Mapping[str, Any], outline: _Outline) -> str:
    """The text of a section without its heading line and without its subsections."""
    start, end = int(section["char_start"]), outline.own_end(section)
    newline = text.find("\n", start, end)
    return text[newline + 1 : end] if newline != -1 else ""


def _heading_targets(
    section: Mapping[str, Any],
    outline: _Outline,
    registry: _Registry,
    own_bwb_id: str | None,
) -> list[tuple[str, str, str]]:
    """``(bwb_id, number, match type)`` of the articles the heading says it explains."""
    found: list[tuple[str, str, str]] = []
    law_of_heading = registry.resolve(section.get("law"))
    for ref in section.get("article_refs") or []:
        number, of = str(ref["number"]), ref["of"]
        if of == OF_NAMED_LAW:
            if law_of_heading:
                found.append((law_of_heading, number, MATCH_HEADING_TARGET))
        elif of == OF_UNKNOWN:
            law = outline.context_law(section, registry)
            if law:
                found.append((law, number, MATCH_HEADING_TARGET))
        elif (
            of == OF_SELF
            and section["kind"] == KIND_ARTICLE
            and section.get("number_scheme") in _NUMBER_SCHEMES
            and not section.get("law")  # "Artikel 3 (Woningwet)": 3 is the bill's own
        ):
            # An Arabic number is the article of the law when the bill is the law; in a bill
            # that changes another law it is the number of the article it changes.
            if own_bwb_id:
                found.append((own_bwb_id, number, MATCH_OWN_NUMBER))
            else:
                law = outline.context_law(section, registry)
                if law:
                    found.append((law, number, MATCH_INFERRED_LAW))
    return found


def _body_targets(
    text: str,
    section: Mapping[str, Any],
    outline: _Outline,
    registry: _Registry,
) -> list[tuple[str, str, str]]:
    """``(bwb_id, number, match type)`` of the articles the text under the heading names."""
    body = _body(text, section, outline)
    if not body.strip():
        return []
    found: list[tuple[str, str, str]] = []
    named: set[str] = set()
    for hit in registry.extractor.extract(body):
        if hit.bwb_id and hit.article_number:
            found.append((hit.bwb_id, hit.article_number, MATCH_BODY_NAMED_LAW))
            named.add(number_key(hit.article_number))
    law = outline.context_law(section, registry)
    if law:
        for hit in registry.extractor.extract_bare(body[:_OPENING_CHARS]):
            if hit.article_number and number_key(hit.article_number) not in named:
                found.append((law, hit.article_number, MATCH_INFERRED_LAW))
    return found


def find_references(
    text: str,
    sections: Sequence[Mapping[str, Any]],
    laws: Sequence[Law],
    *,
    own_bwb_id: str | None = None,
) -> list[Reference]:
    """The articles the sections of a memorandum name, in the order of the document.

    *laws* are the laws the dossier changes; *own_bwb_id* is the law the bill makes when it
    makes a new one. A section names an article once: the surest way it does so counts.
    """
    registry = _Registry(laws)
    outline = _Outline(sections)
    best: dict[tuple[str, str, str], Reference] = {}
    for section in sections:
        if section["kind"] not in _ARTICLE_KINDS:
            continue
        targets = _heading_targets(section, outline, registry, own_bwb_id)
        targets += _body_targets(text, section, outline, registry)
        for bwb_id, number, match_type in targets:
            key = (str(section["id"]), bwb_id, number_key(number))
            known = best.get(key)
            if known and known.confidence >= CONFIDENCE_OF_MATCH[match_type]:
                continue
            start, end = _span(section, outline, match_type)
            best[key] = Reference(
                section_id=str(section["id"]),
                heading=str(section["heading"]),
                level=section.get("level"),
                char_start=start,
                char_end=end,
                bwb_id=bwb_id,
                number=number_key(number),
                match_type=match_type,
            )
    return list(best.values())


# ── from what a section names to what the graph has ──────────────────────────


def explained_targets(
    references: Sequence[Reference],
    changes: Sequence[Change],
    article_exists: Callable[[str], bool],
) -> dict[str, list[Reference]]:
    """The references of each node they point at: ``{node id: [references]}``.

    A reference points at the versions and articles the dossier changed with that number, or,
    when the section states the article itself (its heading), at the article when it exists.
    """
    changed: dict[tuple[str, str], list[Change]] = {}
    for change in changes:
        for key in _number_keys(change.number):
            changed.setdefault((change.bwb_id, key), []).append(change)
    explained: dict[str, list[Reference]] = {}
    for reference in references:
        hits = [
            change
            for key in _number_keys(reference.number)
            for change in changed.get((reference.bwb_id, key), [])
        ]
        targets = {change.target for change in hits}
        if not targets and reference.match_type in _STATED_MATCHES:
            candidates = [
                article_id(reference.bwb_id, key)
                for key in _number_keys(reference.number)
            ]
            targets = {c for c in candidates if article_exists(c)}
        for target in sorted(targets):
            explained.setdefault(target, []).append(reference)
    return explained


def is_introduction(changes: Sequence[Change], bwb_id: str) -> bool:
    """Whether the bill is the law: the dossier changed no article of it but to introduce it.

    A law that the dossier amends or repeals articles of is no new law, whatever the dossier
    references of the law say: its memorandum is about the articles of the bill, not of the law.
    """
    of_law = [c for c in changes if c.bwb_id == bwb_id]
    return all(c.relation == RELATION_INTRODUCES for c in of_law)
