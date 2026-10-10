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
from dataclasses import dataclass, replace
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    RELATION_INTRODUCES,
)
from lawgraph.core.bill_parts import (
    BillPart,
    amendment_changes,
    heading_law,
    heading_parts,
    part_letters,
)
from lawgraph.core.citations import (
    ARTICLE_HEAD_RE,
    DutchCitationExtractor,
    parse_article_numbers,
)
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

# How a section came to name an article, and whether the dossier changed that article. The
# confidence is the share a hand check found right: 10 random edges per kind in lawgraph_small
# (2026-09-29). A change of the article by the dossier corroborates what the paper says; a
# heading that names an article the dossier did not change mostly names an article of another
# law than the one it is taken for (the heading says "Wft", the dossier changes Boek 2 BW).
#
# ``own_number``: in a new law the toelichting of "Artikel 5" is about article 5 of that law.
# The heading is the whole evidence, and it is a convention; 10 of 10 right.
MATCH_OWN_NUMBER = "own_number"
# ``heading_target``: the heading itself says which article it explains ("Artikel I, onderdeel
# B (artikel 1a)", "Onderdeel A (artikel 3 van de Woningwet)"): the author's own statement.
# 10 of 10 right where the dossier changed the article, about 3 of 10 where it did not.
MATCH_HEADING_TARGET = "heading_target"
# ``body_named_law``: the text under the heading says "artikel N van de <Law>" and the law is
# one the dossier changed. The text may also refer to an article it does not explain, but the
# article must be one the dossier changed as well; 6 or 7 of 10 right.
MATCH_BODY_NAMED_LAW = "body_named_law"
# ``inferred_law``: an article number without a law ("de wijziging van artikel 2"), of the law
# the enclosing heading names or of the only law the dossier changes; only the opening of the
# text is read, and the article must be one the dossier changed: 8 of 10 right.
MATCH_INFERRED_LAW = "inferred_law"
# ``bill_part``: the heading names an onderdeel of the bill ("Artikel I, onderdeel B"), and
# the bill says which article that onderdeel changes (``core/bill_parts.py``); the article
# must be one the dossier changed. 10 of 10 right on the server's texts of 14 dossiers
# (2026-10-10; lawgraph_small has no bill texts).
MATCH_BILL_PART = "bill_part"
# ``amendment``: an adopted amendment changes the article, and its Toelichting says why; the
# article must be one the dossier changed. 8 of 8 right: every adopted amendment with a link
# in 15 dossiers on the server (2026-10-10).
MATCH_AMENDMENT = "amendment"

# The confidence of each kind of match where the dossier changed the article.
CONFIDENCE_OF_MATCH = {
    MATCH_OWN_NUMBER: 0.95,
    MATCH_HEADING_TARGET: 0.95,
    MATCH_BODY_NAMED_LAW: 0.65,
    MATCH_INFERRED_LAW: 0.8,
    MATCH_BILL_PART: 0.9,
    MATCH_AMENDMENT: 0.9,
}
# ... and where it did not: only a stated match points at an article the dossier left alone.
CONFIDENCE_UNCHANGED = {
    MATCH_OWN_NUMBER: 0.95,
    MATCH_HEADING_TARGET: 0.3,
}

# What a match rests on, in words.
_RESTS_ON = {
    MATCH_AMENDMENT: "het aangenomen amendement wijzigt het artikel; dit is zijn toelichting",
    MATCH_BILL_PART: (
        "de kop '{heading}' noemt een onderdeel van het wetsvoorstel, en dat wijzigt het "
        "artikel"
    ),
    MATCH_OWN_NUMBER: "de kop '{heading}' is een artikel van de nieuwe wet",
    MATCH_HEADING_TARGET: "de kop '{heading}' noemt het artikel",
    MATCH_BODY_NAMED_LAW: "de tekst onder de kop '{heading}' noemt het artikel met zijn wet",
    MATCH_INFERRED_LAW: (
        "de tekst onder de kop '{heading}' noemt het artikelnummer; de wet is die van de "
        "kop of de enige die het dossier wijzigt"
    ),
}
# The most of a heading an explanation quotes.
_HEADING_CHARS = 80

# The matches a range in a heading is read with: the heading's own numbers.
_RANGE_MATCHES = frozenset({MATCH_HEADING_TARGET, MATCH_INFERRED_LAW})

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
_RANGE_RE = re.compile(r"\btot\s+en\s+met\b|\bt/m\b", re.IGNORECASE)


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
    changed: bool = True  # the dossier changed the article (``explained_targets``)
    # "Artikelen 15 tot en met 15l": the last article of a range that begins at ``number``;
    # the articles between are those of the law the dossier changed
    last: str | None = None

    @property
    def confidence(self) -> float:
        if self.changed:
            return CONFIDENCE_OF_MATCH[self.match_type]
        return CONFIDENCE_UNCHANGED[self.match_type]

    @property
    def explanation(self) -> str:
        """What the match rests on: the section, and whether the dossier changed it."""
        heading = " ".join(self.heading.split())
        if len(heading) > _HEADING_CHARS:
            heading = heading[: _HEADING_CHARS - 1] + "…"
        rests_on = _RESTS_ON[self.match_type].format(heading=heading)
        changed = "wijzigt het artikel" if self.changed else "wijzigt het artikel niet"
        return f"{rests_on[:1].upper()}{rests_on[1:]}; het dossier {changed}."


def number_key(number: str) -> str:
    """An article number as compared: ``1A`` and ``1a.`` are one article."""
    return number.strip(" .").lower()


def _number_keys(number: str) -> list[str]:
    """The numbers the article a reference names may be stored under: a book's articles
    have no book (the BW stores 7:658 as 658 in Boek 7); a law numbered per chapter keeps
    it (Awb 11:2)."""
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

    def __init__(
        self,
        sections: Sequence[Mapping[str, Any]],
        bill: Mapping[tuple[str, str], BillPart] | None = None,
    ) -> None:
        self.by_id = {str(s["id"]): s for s in sections}
        self.bill = bill or {}
        first_child: dict[str, int] = {}
        # the heading of an article of the bill before a section, under the same parent
        # ("ARTIKEL II – WETBOEK VAN STRAFRECHT", "Artikel II, onderdeel D")
        self._bill_article: dict[str, Mapping[str, Any]] = {}
        last: dict[str | None, Mapping[str, Any]] = {}
        for section in sections:
            parent = section.get("parent")
            if parent is not None:
                first_child.setdefault(str(parent), int(section["char_start"]))
            parent_key = None if parent is None else str(parent)
            if heading_parts(str(section["heading"])) is not None:
                last[parent_key] = section
            elif parent_key in last:
                self._bill_article[str(section["id"])] = last[parent_key]
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
            before = self._bill_article.get(str(node["id"]))
            if before is not None:
                law = self.bill_article_law(before, registry)
                if law:
                    return law
            parent = node.get("parent")
            node = self.by_id.get(str(parent)) if parent is not None else None
        return registry.sole

    def bill_article_law(
        self, heading: Mapping[str, Any], registry: _Registry
    ) -> str | None:
        """The law the heading of an article of the bill says it changes: the law its
        heading names ("ARTIKEL II – WETBOEK VAN STRAFRECHT"), else the one that article
        of the bill changes."""
        text = str(heading["heading"])
        named = heading_law(text)
        law = registry.resolve(heading.get("law") or named)
        if law:
            return law
        article = heading_parts(text)
        return _bill_article_law(article[0], self.bill, registry) if article else None


def _bill_article_law(
    article: str, bill: Mapping[tuple[str, str], BillPart], registry: _Registry
) -> str | None:
    """The law an article of the bill changes: the one it says it changes ("Het Wetboek van
    Strafvordering wordt als volgt gewijzigd"), else the one its instruction names."""
    for (number, _), part in bill.items():
        if number != article:
            continue
        if part.law:
            return registry.resolve(part.law)
        hits = registry.extractor.extract(part.instruction)
        return next((hit.bwb_id for hit in hits if hit.bwb_id), None)
    return None


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
    named = _named_in_heading(section, registry)
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
            # An Arabic number is the article of the law the heading names ("Artikel 11
            # Sr"), else of the law when the bill is the law; in a bill that changes
            # another law it is the number of the article it changes.
            if number_key(number) in named:
                found.append((named[number_key(number)], number, MATCH_HEADING_TARGET))
            elif own_bwb_id:
                found.append((own_bwb_id, number, MATCH_OWN_NUMBER))
            else:
                law = outline.context_law(section, registry)
                if law:
                    found.append((law, number, MATCH_INFERRED_LAW))
    return found


def _named_in_heading(
    section: Mapping[str, Any], registry: _Registry
) -> dict[str, str]:
    """``{number: bwb_id}`` of the articles a heading names with their law ("Artikel 11
    Sr", "Artikel 4, vijfde lid, Wahv"): a law the dossier changes, by its name or code."""
    if section["kind"] != KIND_ARTICLE or section.get("law"):
        return {}
    return {
        number_key(hit.article_number): hit.bwb_id
        for hit in registry.extractor.extract(str(section["heading"]))
        if hit.bwb_id and hit.article_number
    }


def _range_end(section: Mapping[str, Any]) -> tuple[str, str] | None:
    """``(first, last)`` of a heading that names a range ("Artikelen 15 tot en met 15l")."""
    refs = [r for r in section.get("article_refs") or [] if r.get("of") == OF_SELF]
    if len(refs) != 2 or not _RANGE_RE.search(str(section["heading"])):
        return None
    return number_key(str(refs[0]["number"])), number_key(str(refs[1]["number"]))


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
        for match in ARTICLE_HEAD_RE.finditer(body[:_OPENING_CHARS]):
            for number in parse_article_numbers(match["nums"]):
                if number_key(number) not in named:
                    named.add(number_key(number))
                    found.append((law, number, MATCH_INFERRED_LAW))
    return found


def _bill_targets(
    section: Mapping[str, Any],
    outline: _Outline,
    registry: _Registry,
    text: str,
    bill: Mapping[tuple[str, str], BillPart],
) -> list[tuple[str, str, str]]:
    """``(bwb_id, number, match type)`` of the articles the onderdelen of the bill a section
    explains change: those its heading names ("Artikel II, onderdeel D"), or, for an
    onderdeel under the heading of an article of the bill, its own letters. A section
    without text of its own explains nothing (the article under it does)."""
    named = _bill_onderdelen(section, outline)
    if not named or not _body(text, section, outline).strip():
        return []
    article, letters = named
    found: list[tuple[str, str, str]] = []
    for letter in letters:
        part = bill.get((article, letter))
        if part is None:
            continue
        if part.law:
            law = registry.resolve(part.law)
            if law:
                found += [(law, number, MATCH_BILL_PART) for number in part.numbers]
            continue
        # an article of the bill without onderdelen names its law in its instruction
        for hit in registry.extractor.extract(part.instruction):
            if hit.bwb_id and hit.article_number:
                found.append((hit.bwb_id, hit.article_number, MATCH_BILL_PART))
    return found


def _bill_onderdelen(
    section: Mapping[str, Any], outline: _Outline
) -> tuple[str, tuple[str, ...]] | None:
    """The article of the bill and the onderdelen a section explains."""
    if section["kind"] == KIND_ARTICLE:
        return heading_parts(str(section["heading"]))
    if section["kind"] != KIND_PART or not section.get("number"):
        return None
    parent = outline.by_id.get(str(section.get("parent")))
    named = heading_parts(str(parent["heading"])) if parent else None
    if named is None or named[1] != ("",):
        return None
    return named[0], part_letters(str(section["number"]))


def find_references(
    text: str,
    sections: Sequence[Mapping[str, Any]],
    laws: Sequence[Law],
    *,
    own_bwb_id: str | None = None,
    bill: Mapping[tuple[str, str], BillPart] | None = None,
) -> list[Reference]:
    """The articles the sections of a memorandum name, in the order of the document.

    *laws* are the laws the dossier changes; *own_bwb_id* is the law the bill makes when it
    makes a new one; *bill* the onderdelen of the bill (``core.bill_parts``), which say what
    a heading "Artikel I, onderdeel B" explains. A section names an article once: the
    surest way it does so counts.
    """
    registry = _Registry(laws)
    outline = _Outline(sections, bill)
    best: dict[tuple[str, str, str], Reference] = {}
    for section in sections:
        if section["kind"] not in _ARTICLE_KINDS:
            continue
        targets = _heading_targets(section, outline, registry, own_bwb_id)
        targets += _body_targets(text, section, outline, registry)
        if bill:
            targets += _bill_targets(section, outline, registry, text, bill)
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
        span = _range_end(section)
        if span is None:
            continue
        for bwb_id, number, match_type in targets:
            if match_type in _RANGE_MATCHES and number_key(number) == span[0]:
                known = best[(str(section["id"]), bwb_id, span[0])]
                best[(str(section["id"]), bwb_id, f"{span[0]}..{span[1]}")] = replace(
                    known, match_type=match_type, last=span[1]
                )
    return list(best.values())


# ── adopted amendments ───────────────────────────────────────────────────────


def _toelichting(sections: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The section that explains an amendment: the one headed "Toelichting"."""
    for section in sections:
        if str(section["heading"]).strip(" .:").lower() == "toelichting":
            return section
    return None


def _amendment_law(
    instructions: Sequence[str],
    bill_articles: Sequence[str],
    registry: _Registry,
    bill: Mapping[tuple[str, str], BillPart],
) -> str | None:
    """The law an amendment changes: through the article of the bill it names ("In artikel
    II"), else the law its instructions name."""
    for article in bill_articles:
        law = _bill_article_law(article, bill, registry)
        if law:
            return law
    for instruction in instructions:
        for hit in registry.extractor.extract(instruction):
            if hit.bwb_id:
                return hit.bwb_id
    return None


def amendment_references(
    text: str,
    sections: Sequence[Mapping[str, Any]],
    laws: Sequence[Law],
    changes: Sequence[Change],
    bill: Mapping[tuple[str, str], BillPart],
) -> list[Reference]:
    """The articles an adopted amendment changes, each explained by its Toelichting.

    What it changes is read from the text before the Toelichting (``amendment_changes``);
    the law through the article of the bill it names, else from its instructions, else it
    is the one law of the dossier that changed that number. Without a Toelichting the
    amendment explains nothing."""
    toelichting = _toelichting(sections)
    if toelichting is None:
        return []
    start, end = int(toelichting["char_start"]), int(toelichting["char_end"])
    changed = amendment_changes(text[:start])
    registry = _Registry(laws)
    law = _amendment_law(changed.instructions, changed.bill_articles, registry, bill)
    references = []
    for number in changed.numbers:
        bwb_id = law or _only_law_that_changed(number, changes)
        if bwb_id is None:
            continue
        references.append(
            Reference(
                section_id=str(toelichting["id"]),
                heading=str(toelichting["heading"]),
                level=toelichting.get("level"),
                char_start=start,
                char_end=end,
                bwb_id=bwb_id,
                number=number_key(number),
                match_type=MATCH_AMENDMENT,
            )
        )
    return references


def _only_law_that_changed(number: str, changes: Sequence[Change]) -> str | None:
    """The law of the dossier that changed an article of this number, when only one did."""
    laws = {c.bwb_id for c in changes if number_key(c.number) == number_key(number)}
    return next(iter(laws)) if len(laws) == 1 else None


# ── from what a section names to what the graph has ──────────────────────────


def explained_targets(
    references: Sequence[Reference],
    changes: Sequence[Change],
    article_exists: Callable[[str], bool],
) -> dict[str, list[Reference]]:
    """The references of each node they point at: ``{node id: [references]}``.

    A reference points at the versions and articles the dossier changed with that number, or,
    when the section states the article itself (its heading), at the article when it exists;
    the reference then says the dossier did not change it (``changed``).
    """
    # a change by the number the law stores the article under: a reference may leave out
    # the book (``_number_keys``), the store does not (Awb 11:2 is no article 2)
    changed: dict[tuple[str, str], list[Change]] = {}
    for change in changes:
        changed.setdefault((change.bwb_id, number_key(change.number)), []).append(
            change
        )
    explained: dict[str, list[Reference]] = {}
    for reference in references:
        if reference.last is not None:
            inside = [
                c
                for c in changes
                if c.bwb_id == reference.bwb_id
                and _order(reference.number) < _order(c.number) < _order(reference.last)
            ]
            for target in sorted({c.target for c in inside}):
                explained.setdefault(target, []).append(reference)
            continue
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
            reference = replace(reference, changed=False)
        for target in sorted(targets):
            explained.setdefault(target, []).append(reference)
    return explained


def _order(number: str) -> list[tuple[int, str]]:
    """An article number as it is ordered in its law: 14l, 15, 15a, 15l, 16; 6:1:2."""
    return [(int(n), s) for n, s in re.findall(r"(\d+)([a-z]*)", number_key(number))]


def is_introduction(changes: Sequence[Change], bwb_id: str) -> bool:
    """Whether the bill is the law: the dossier changed no article of it but to introduce it.

    A law that the dossier amends or repeals articles of is no new law, whatever the dossier
    references of the law say: its memorandum is about the articles of the bill, not of the law.
    """
    of_law = [c for c in changes if c.bwb_id == bwb_id]
    return all(c.relation == RELATION_INTRODUCES for c in of_law)
