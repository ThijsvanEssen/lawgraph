"""The text and the section structure of a Kamerstuk XML (KOOP), pure.

A Tweede Kamer paper is published as XML in one of two dialects: ``kamerwrk`` (1995-2009,
flat headings ``tuskop[@letat]``) and ``officiele-publicatie/kamerstuk`` (2010 on, nested
``divisie/kop/{nr,titel}`` and flat ``tussenkop[@kopopmaak]``). Neither has an element for an
article: the artikelsgewijs part of an explanatory memorandum is a run of headings ("Artikel 3",
"Onderdeel B", "Eerste lid") with the paragraphs after them. ``parse_kamerstuk`` flattens the
XML to text, one line per heading, paragraph, list item or table row, and reads the sections
from the headings.

Text: whitespace is collapsed, a footnote is moved out to ``footnotes``, a table row is one line
with tab-separated cells, the metadata and the signature are left out. Sections: every heading
opens one, and it spans its heading, its body and everything nested under it, as offsets into
the text (``text[char_start:char_end]``).

Nothing here raises for a paper it cannot make sense of: XML that is not a Kamerstuk gives an
empty result, a paper without recognisable structure gives the text and no sections.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from lawgraph.core.citations import (
    ARTICLE_NUMBER_PATTERN,
    ARTICLE_NUMBERS_PATTERN,
    parse_article_numbers,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.xml import collapse_ws, local_name

logger = get_logger(__name__)

TEXT_SOURCE = "kst-xml"

DIALECT_LEGACY = "kamerwrk"
DIALECT_MODERN = "officiele-publicatie"

# The most characters of text that are kept. The longest paper seen (a budget) has 1.1 million;
# the cap only stops a runaway paper from making a node too large to write. A paper over it is
# cut at a line and says so (``truncated``); the sections that start beyond the cut are dropped.
MAX_TEXT_CHARS = 2_000_000

# Structure quality of a paper
QUALITY_EXPLICIT = "explicit"  # an artikelsgewijs opener and article headings after it
QUALITY_IMPLICIT = "implicit"  # article headings, no opener
QUALITY_NONE = "none"

# Section kinds
KIND_GENERAL = "algemeen"
KIND_ARTICLEWISE = "artikelsgewijs"
KIND_ARTICLE = "article"
KIND_PART = "onderdeel"
KIND_PARAGRAPH = "lid"
KIND_CHAPTER = "chapter"
KIND_OTHER = "other"

# Number schemes
SCHEME_ARABIC = "arabic"
SCHEME_ROMAN = "roman"
SCHEME_BOOK_ARTICLE = "book_article"  # "3:159n", "1.6.20"
SCHEME_LETTER = "letter"  # "Onderdeel B"

# Whose article a number in a heading is
OF_SELF = "self"  # of the bill the memorandum belongs to
OF_NAMED_LAW = "named_law"  # of the law the heading names (``law`` of the section)
OF_UNKNOWN = "unknown"  # of a law the heading implies and does not name

# ── the XML ──────────────────────────────────────────────────────────────────

# Elements that are no part of the memorandum: the header, the signature, the layout.
_SKIP = frozenset(
    {
        "metadata",
        "kamerstukkop",
        "frontm",
        "dossier",
        "stuknr",
        "datumtekst",
        "ltrlabel",
        "nummer",
        "tekst-sluiting",
        "ondertekening",
        "ondtek",
        "witreg",
        "plaatje",
        "officiele-inhoudsopgave",
        "margetekst",
        "letter",
    }
)
# What stands inside a paragraph and is no text of it: the marker of a legacy footnote (the
# footnote itself is an element of the root; a modern ``noot`` is collected where it stands).
_MARKERS = frozenset({"voetref", "nootref"})
# Inline elements that keep what is on either side of them apart.
_BLOCKISH = frozenset({"al", "al-groep", "lijst", "li", "noot.al"})
# The header of the paper is a ``kop`` of the root; every other ``kop`` is a heading.
_ROOTS = frozenset({DIALECT_LEGACY, DIALECT_MODERN, "kamerstuk"})


@dataclass
class _Line:
    """One line of the text: a heading or a body line."""

    text: str
    heading: bool = False
    depth: int = 0  # the divisie nesting it stands in
    flat: bool = False  # a heading that is no kop of a divisie
    number: str | None = None  # the ``nr`` of a kop, apart from its title
    title: str = ""  # the ``titel`` of a kop


class _Flattener:
    """Walks the XML in document order and collects the lines and the footnotes."""

    def __init__(self) -> None:
        self.lines: list[_Line] = []
        self.footnotes: list[dict[str, str]] = []

    def run(self, root: ET.Element) -> None:
        for child in root:
            self._visit(child, 0, parent=local_name(root.tag))

    def _visit(self, element: ET.Element, depth: int, *, parent: str) -> None:
        name = local_name(element.tag)
        if name in _SKIP:
            return
        if name == "divisie":
            self._divisie(element, depth + 1)
        elif name in ("tussenkop", "tuskop"):
            self._heading(self._inline(element), depth, flat=True)
        elif name == "kop":
            if parent not in _ROOTS:
                self._kop(element, depth, flat=True)
        elif name == "al":
            self._body(self._inline(element))
        elif name == "lijst":
            self._list(element)
        elif name == "table":
            self._table(element)
        elif name == "voetnoot":
            self._legacy_footnote(element)
        elif len(element) == 0:
            self._body(self._inline(element))  # the title of the paper, a caption
        else:
            for child in element:
                self._visit(child, depth, parent=name)

    def _divisie(self, element: ET.Element, depth: int) -> None:
        for child in element:
            if local_name(child.tag) == "kop":
                self._kop(child, depth, flat=False)
            else:
                self._visit(child, depth, parent="divisie")

    def _kop(self, kop: ET.Element, depth: int, *, flat: bool) -> None:
        parts = {
            name: self._inline(child)
            for child in kop
            if (name := local_name(child.tag)) in ("label", "nr", "titel")
        }
        text = collapse_ws(" ".join(p for p in parts.values() if p))
        self._heading(
            text or self._inline(kop),
            depth,
            flat=flat,
            # "Artikel" + "3" is the words of a heading, not a number in front of them
            number=None if "label" in parts else parts.get("nr") or None,
            title=parts.get("titel", ""),
        )

    def _heading(
        self,
        text: str,
        depth: int,
        *,
        flat: bool,
        number: str | None = None,
        title: str = "",
    ) -> None:
        if text:
            self.lines.append(
                _Line(text, True, depth, flat, number, title if number else text)
            )

    def _body(self, text: str) -> None:
        if text:
            self.lines.append(_Line(text))

    def _list(self, element: ET.Element) -> None:
        for item in element:
            if local_name(item.tag) != "li":
                continue
            number = next(
                (self._inline(c) for c in item if local_name(c.tag) == "li.nr"), ""
            )
            body = self._inline(item, skip={"li.nr", "lijst"})
            self._body(collapse_ws(f"{number} {body}"))
            for nested in item:
                if local_name(nested.tag) == "lijst":
                    self._list(nested)

    def _table(self, element: ET.Element) -> None:
        for node in element.iter():
            name = local_name(node.tag)
            if name == "title":
                self._body(self._inline(node))
            elif name == "row":
                cells = [
                    self._inline(cell)
                    for cell in node
                    if local_name(cell.tag) == "entry"
                ]
                if any(cells):
                    self.lines.append(_Line("\t".join(cells)))

    def _legacy_footnote(self, element: ET.Element) -> None:
        text = self._inline(element)
        if text:
            self.footnotes.append({"number": element.get("nr") or "", "text": text})

    def _inline(self, element: ET.Element, *, skip: set[str] | None = None) -> str:
        """The collapsed text of *element*, without footnotes and their markers."""
        parts: list[str] = []
        self._collect(element, parts, skip or set(), top=True)
        return collapse_ws("".join(parts))

    def _collect(
        self,
        element: ET.Element,
        parts: list[str],
        skip: set[str],
        *,
        top: bool = False,
    ) -> None:
        name = local_name(element.tag)
        if not top:
            if name == "noot":
                self._footnote(element)
                return
            if name in _MARKERS or name in skip:
                return
        block = name in _BLOCKISH
        parts.append(" " if block else "")
        parts.append(element.text or "")
        for child in element:
            self._collect(child, parts, skip)
            parts.append(child.tail or "")
        parts.append(" " if block else "")

    def _footnote(self, element: ET.Element) -> None:
        number = ""
        body: list[str] = []
        for child in element:
            if local_name(child.tag) == "noot.nr":
                number = self._inline(child)
            else:
                body.append(self._inline(child))
        text = collapse_ws(" ".join(body))
        if text:
            self.footnotes.append({"number": number, "text": text})


# ── headings ─────────────────────────────────────────────────────────────────

# A Roman number (Artikel II, Artikel XIV): upper case only, so "Artikel is" is no number;
# one letter may follow ("IIA").
_ROMAN_CORE = r"(?-i:(?=[IVXL])L?X{0,3}(?:IX|IV|V?I{0,3}))"
_ROMAN_NUM = rf"(?:{_ROMAN_CORE}(?-i:[A-Z])?)"
# A wijzigingswet that runs out of Roman numbers goes on with letters ("Artikel N").
_LETTER_NUM = rf"(?:{_ROMAN_NUM}|(?-i:[A-Z]{{1,2}}))"
_LETTER_LIST = rf"{_LETTER_NUM}(?:\s*(?:,|en|tot en met|t/m)\s*{_LETTER_NUM})*"

# "Artikel 3", "Artikelen 3 en 4", "Artikel II", "Artikel I, onderdeel B (artikel 1a)",
# "ARTIKEL II (Huisvestingswet 2014)", "Ad artikel 3": the numbers, then what follows them.
_ARTICLE_RE = re.compile(
    r"^(?:(?:de|ad|nieuwe?|wijziging(?:en)?(?:\s+van)?)\s+)?(?:artikel(?:en)?|art\.)\s+"
    rf"(?:(?P<arabic>{ARTICLE_NUMBERS_PATTERN})|(?P<letters>{_LETTER_LIST}))(?![\w])(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
# The heading that opens the article-by-article part.
_ARTICLEWISE_RE = re.compile(
    r"artikel(?:s)?gewij[sz]|toelichting\s+(?:op\s+de|per|bij\s+de)\s+artikelen?\b"
    r"|^artikelen[\s.:]*$",
    re.IGNORECASE,
)
_GENERAL_RE = re.compile(r"^(?:algemeen|algemene)\b", re.IGNORECASE)
# What ends the article-by-article part besides a heading of its own level.
_AFTER_RE = re.compile(
    r"^(?:bijlage|bijlagen|transponeringstabel|ondertekening|overzicht)\b",
    re.IGNORECASE,
)
# "Onderdeel B", "Ad a.", and the bare letters a wijzigingswet numbers its onderdelen with:
# "C", "A, B, D en F", "A, onderdelen 1 en 3, B".
_PART_LETTERS = r"(?:onderde(?:el|len)\s+)?(?-i:[A-Z]{1,2}|\d{1,2})"
_PART_RE = re.compile(
    r"^onderde(?:el|len)\s+(?P<n>[A-Za-z]{1,2}|\d{1,2})(?![\w])"
    r"|^(?:ad|onder)\s+(?P<ad>[A-Za-z]{1,2}|\d{1,2})(?![\w])"
    rf"|^(?P<letters>{_PART_LETTERS}(?:\s*(?:,|en|t/m|tot en met)\s*{_PART_LETTERS})*)\s*\.?$",
    re.IGNORECASE,
)
_ORDINALS = {
    "eerste": "1",
    "tweede": "2",
    "derde": "3",
    "vierde": "4",
    "vijfde": "5",
    "zesde": "6",
    "zevende": "7",
    "achtste": "8",
    "negende": "9",
    "tiende": "10",
}
_ORDINAL = rf"(?:{'|'.join(_ORDINALS)}|\d{{1,2}}e)"
_PARAGRAPH_RE = re.compile(
    rf"^(?P<ord>{_ORDINAL})(?:\s*(?:,|en)\s*{_ORDINAL})*\s+lid\b"
    r"|^lid\s+(?P<n>\d{1,2}[a-z]?)\b|^leden\s+(?P<first>\d{1,2})"
    r"|^ad\s+(?P<ad>\d{1,2}[a-z]?)(?![\w])",
    re.IGNORECASE,
)
_CHAPTER_RE = re.compile(
    rf"^(?P<word>hoofdstuk|afdeling|paragraaf|titel|deel|boek)\s+"
    rf"(?P<n>{_ROMAN_NUM}|\d+[a-z]?(?:\.\d+)*)(?![\w])",
    re.IGNORECASE,
)
_HIGH_CHAPTERS = frozenset({"hoofdstuk", "titel", "deel", "boek"})
# A number in front of a heading: "1.", "1.1.", "II.2", "II.", "A". A bare letter must be
# followed by a dot or by a capitalised word ("A ARTIKELGEWIJZE").
_PREFIX_RE = re.compile(
    rf"^(?:§\s*)?(?:(?P<dotted>(?:{_ROMAN_CORE}|\d+)(?:\.\d+)+)\.?\s+"
    r"|(?P<arabic>\d+)[.)]?\s+"
    rf"|(?P<roman>{_ROMAN_CORE})(?:[.)]\s*|\s+)"
    r"|(?P<letter>(?-i:[A-Z]))(?:[.)]\s*|\s+(?=(?-i:[A-Z]{2}))))"
)
_LAW_WORD_RE = re.compile(
    r"wet|besluit|regeling|verordening|verdrag|richtlijn|reglement|\bboek\s+\d"
    r"|\b(?:Awb|BW|Sr|Sv|Rv)\b",
    re.IGNORECASE,
)
# One way through a run of ", …" parts: each part is a comma and what follows up to the next
# one, so no two parts can share a character (a `\s*` next to a class that holds spaces too
# made the number of ways to split a long line explode: minutes on one paper).
_LAW_OF_RE = re.compile(
    r"^\s*(?:,[^,()]{1,40})*\s*van\s+(?:de|het)\s+(?P<law>[^,.;()]{3,80})",
    re.IGNORECASE,
)
# A heading is short; the words after its numbers that name a law are at its start.
_LAW_OF_REACH = 400
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_PAREN_ARTICLE_RE = re.compile(
    rf"^\s*artikel(?:en)?\s+(?P<nums>{ARTICLE_NUMBERS_PATTERN})(?![\w])(?P<tail>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_ROMAN_ONLY_RE = re.compile(rf"^{_ROMAN_NUM}$")
_ARABIC_ONLY_RE = re.compile(rf"^{ARTICLE_NUMBER_PATTERN}$", re.IGNORECASE)
_MAX_RANGE = 100


@dataclass
class _Heading:
    """What the words of a heading say it is."""

    kind: str = KIND_OTHER
    number: str | None = None
    scheme: str | None = None
    refs: list[dict[str, str]] = field(default_factory=list)
    law: str | None = None
    high_chapter: bool = (
        False  # Hoofdstuk / Titel / Deel / Boek, against Afdeling / Paragraaf
    )
    top: bool = False  # numbered "II." or "C.": a part of the paper, not of a part
    printed: tuple[str | None, str | None] = (None, None)  # the number in front of it


def _scheme(number: str) -> str | None:
    if _ARABIC_ONLY_RE.match(number):
        return SCHEME_BOOK_ARTICLE if re.search(r"[.:]", number) else SCHEME_ARABIC
    if _ROMAN_ONLY_RE.match(number):
        return SCHEME_ROMAN
    if re.fullmatch(r"[A-Za-z]{1,2}", number):
        return SCHEME_LETTER
    return None


def _expand(numbers: list[str]) -> list[str]:
    """A range of plain numbers ("1 tot en met 3") as every number in it."""
    if (
        len(numbers) == 2
        and all(n.isdigit() for n in numbers)
        and 0 < int(numbers[1]) - int(numbers[0]) < _MAX_RANGE
    ):
        return [str(n) for n in range(int(numbers[0]), int(numbers[1]) + 1)]
    return numbers


def _article_numbers(match: re.Match[str]) -> list[str]:
    if match["arabic"]:
        return _expand(parse_article_numbers(match["arabic"]))
    parts = re.split(r"\s*(?:,|\ben\b|tot en met|t/m)\s*", match["letters"])
    return [part.strip() for part in parts if part.strip()]


def _law_name(text: str) -> str | None:
    name = re.sub(r"\s+", " ", text).strip(" .,;:")
    name = re.sub(r"^(?:van\s+)?(?:(?:de|het)\s+)?", "", name, flags=re.IGNORECASE)
    return name if name and _LAW_WORD_RE.search(name) else None


def _law_and_refs(rest: str, own: list[str]) -> tuple[list[dict[str, str]], str | None]:
    """The references and the law another law that the words after the numbers name."""
    refs = [{"number": n, "of": OF_SELF} for n in own]
    law: str | None = None
    direct = _LAW_OF_RE.match(rest[:_LAW_OF_REACH])
    if direct and _law_name(direct["law"]):
        law = _law_name(direct["law"])
        refs = [{"number": n, "of": OF_NAMED_LAW} for n in own]
    for inner in _PAREN_RE.findall(rest):
        article = _PAREN_ARTICLE_RE.match(inner)
        if article:
            named = _law_name(article["tail"])
            of = OF_NAMED_LAW if named else OF_UNKNOWN
            numbers = _expand(parse_article_numbers(article["nums"]))
            refs.extend({"number": n, "of": of} for n in numbers)
            law = law or named
        elif law is None:
            law = _law_name(inner)
    return refs, law


def _split_number(line: _Line) -> tuple[str | None, str, bool]:
    """``(number, the words of the heading, whether it numbers a part of the paper)``.

    A kop has its number apart; in a flat heading it is in front of the words.
    """
    if line.number is not None:
        return line.number.rstrip("."), line.title, True
    match = _PREFIX_RE.match(line.text)
    if not match or not line.text[match.end() :].strip():
        return None, line.text, False
    number = match["dotted"] or match["arabic"] or match["roman"] or match["letter"]
    return (
        number,
        line.text[match.end() :].strip(),
        not (match["dotted"] or match["arabic"]),
    )


def _numbering_depth(heading: _Heading) -> int:
    """0 for "II." and "C.", the number of dotted parts for "6.1.2", 1 without a number."""
    number = heading.printed[0]
    if number is None:
        return 1
    return 0 if heading.top else number.count(".") + 1


def _classify(number: str | None, core: str, top: bool) -> _Heading:
    """What a heading is, from its own words (not from where it stands)."""
    heading = _Heading(top=top and number is not None)
    if number:
        heading.number, heading.scheme = number, _scheme(number)
        heading.printed = (heading.number, heading.scheme)
    article = _ARTICLE_RE.match(core)
    if article:
        numbers = _article_numbers(article)
        heading.kind = KIND_ARTICLE
        heading.number, heading.scheme = numbers[0], _scheme(numbers[0])
        heading.refs, heading.law = _law_and_refs(article["rest"], numbers)
    elif _ARTICLEWISE_RE.search(core):
        heading.kind = KIND_ARTICLEWISE
    elif part := _PART_RE.match(core):
        heading.kind = KIND_PART
        heading.number = part["n"] or part["ad"] or part["letters"]
        heading.scheme = SCHEME_ARABIC if heading.number[0].isdigit() else SCHEME_LETTER
        heading.refs, heading.law = _law_and_refs(core, [])
    elif paragraph := _PARAGRAPH_RE.match(core):
        heading.kind = KIND_PARAGRAPH
        heading.number = _paragraph_number(paragraph)
        heading.scheme = SCHEME_ARABIC
        heading.refs, heading.law = _law_and_refs(core, [])
    elif chapter := _CHAPTER_RE.match(core):
        heading.kind = KIND_CHAPTER
        heading.number, heading.scheme = chapter["n"], _scheme(chapter["n"])
        heading.high_chapter = chapter["word"].lower() in _HIGH_CHAPTERS
    return heading


def _paragraph_number(match: re.Match[str]) -> str | None:
    ordinal = (match["ord"] or "").lower()
    if ordinal in _ORDINALS:
        return _ORDINALS[ordinal]
    if ordinal:  # "2e"
        return ordinal[:-1]
    return match["n"] or match["first"] or match["ad"]


# ── sections ─────────────────────────────────────────────────────────────────

# Where the parts of the article-by-article part stand under its opener; a lower rank is a
# higher place in the outline. Outside of it a heading has the rank its nesting gives it: a
# kop of a divisie its depth, a flat heading a rank between its divisie and the next one.
_CHAPTER_RANK = 10
_SUBCHAPTER_RANK = 20
_BEFORE_ARTICLES_RANK = 25
_ARTICLE_RANK = 30
_PART_RANK = 40
_UNDER_ARTICLE_RANK = 45
_PARAGRAPH_RANK = 50
_DEPTH_RANK = 100
_FLAT_RANK = 50


@dataclass(frozen=True)
class Section:
    """One heading of the paper with the text under it (see the module docstring)."""

    id: str
    heading: str
    level: int
    kind: str
    number: str | None
    number_scheme: str | None
    article_refs: list[dict[str, str]]
    law: str | None
    parent: str | None
    char_start: int
    char_end: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "heading": self.heading,
            "level": self.level,
            "kind": self.kind,
            "number": self.number,
            "number_scheme": self.number_scheme,
            "article_refs": [dict(ref) for ref in self.article_refs],
            "law": self.law,
            "parent": self.parent,
            "char_start": self.char_start,
            "char_end": self.char_end,
        }


@dataclass(frozen=True)
class ParsedKamerstuk:
    """A Kamerstuk XML as the pipeline stores it."""

    text: str = ""
    sections: list[Section] = field(default_factory=list)
    footnotes: list[dict[str, str]] = field(default_factory=list)
    dialect: str | None = None
    structure_quality: str = QUALITY_NONE
    budget: bool = False
    truncated: bool = False


@dataclass
class _Planned:
    """A heading with its place in the outline, before it has a parent and offsets."""

    line: int
    text: str
    heading: _Heading
    rank: int
    parent: int | None = None
    level: int = 1
    end_line: int = 0


class _Outline:
    """Settles the kind and the rank of every heading, in document order.

    The paper is in a part of its own: before anything (``front``), in the general part
    (``general``), in the article-by-article part after its opener (``articlewise``) or among
    article headings that have no opener (``implicit``), or past it (``after``, a bijlage).
    """

    def __init__(self) -> None:
        self.part = "front"
        self.base = 0  # the rank of the opener, or of what stands in for it
        self.article_seen = False
        self.planned: list[_Planned] = []

    def add(self, index: int, line: _Line) -> None:
        number, core, top = _split_number(line)
        heading = _classify(number, core, top)
        generic = self._generic_rank(line, heading, core)
        self._step(heading, core, line, generic)
        self.planned.append(
            _Planned(index, line.text, heading, self._rank(heading, line, generic))
        )

    @staticmethod
    def _generic_rank(line: _Line, heading: _Heading, core: str) -> int:
        if not line.flat:
            return _DEPTH_RANK * line.depth
        depth = _numbering_depth(heading)
        if heading.printed[0] is None and (
            heading.kind == KIND_ARTICLEWISE or _GENERAL_RE.match(core)
        ):
            depth = 0  # "ALGEMEEN" and "ARTIKELSGEWIJZE TOELICHTING" head a part like "I." does
        return _DEPTH_RANK * line.depth + _FLAT_RANK + 10 * depth

    def _in_region(self) -> bool:
        return self.part in ("articlewise", "implicit")

    def _step(self, heading: _Heading, core: str, line: _Line, generic: int) -> None:
        """Move the state on and settle the kind (an article heading anywhere is one)."""
        kind = heading.kind
        if kind == KIND_ARTICLEWISE:
            self.part, self.base, self.article_seen = "articlewise", generic, False
        elif kind == KIND_ARTICLE:
            if not self._in_region():
                self.part, self.base = "implicit", generic - _ARTICLE_RANK
            self.article_seen = True
        elif kind in (KIND_PART, KIND_PARAGRAPH):
            if not (self._in_region() and self.article_seen):
                # "Onderdeel A" outside of an article is a heading like any other
                heading.kind = KIND_OTHER
                heading.number, heading.scheme = heading.printed
                heading.refs, heading.law = [], None
        elif kind == KIND_OTHER and self._ends_region(core, line, generic, heading):
            self.part = "after"
        if heading.kind == KIND_OTHER:
            if self.part == "front" and _GENERAL_RE.match(core):
                self.part = "general"
            if self.part == "general":
                heading.kind = KIND_GENERAL

    def _ends_region(
        self, core: str, line: _Line, generic: int, heading: _Heading
    ) -> bool:
        if not self._in_region():
            return False
        if _AFTER_RE.match(core):
            return True
        if self.part == "implicit" or generic > self.base:
            return False
        return not line.flat or heading.top

    def _rank(self, heading: _Heading, line: _Line, generic: int) -> int:
        if not self._in_region():
            return generic
        kind, base = heading.kind, self.base
        if kind == KIND_ARTICLEWISE:
            return generic
        ranks = {
            KIND_ARTICLE: _ARTICLE_RANK,
            KIND_PART: _PART_RANK,
            KIND_PARAGRAPH: _PARAGRAPH_RANK,
            KIND_CHAPTER: _CHAPTER_RANK if heading.high_chapter else _SUBCHAPTER_RANK,
        }
        if kind in ranks:
            return base + ranks[kind]
        if line.flat:
            return base + (
                _UNDER_ARTICLE_RANK if self.article_seen else _BEFORE_ARTICLES_RANK
            )
        return max(generic, base + _CHAPTER_RANK)


def _sections(lines: list[_Line], starts: list[int], total: int) -> list[Section]:
    """The sections of *lines* (``starts``: where each line begins in the text)."""
    outline = _Outline()
    for index, line in enumerate(lines):
        if line.heading:
            outline.add(index, line)
    planned = outline.planned

    stack: list[int] = []  # positions in ``planned``, the open sections
    for position, item in enumerate(planned):
        item.end_line = len(lines)
        while stack and planned[stack[-1]].rank >= item.rank:
            planned[stack.pop()].end_line = item.line
        if stack:
            item.parent = stack[-1]
            item.level = planned[stack[-1]].level + 1
        stack.append(position)

    def ident(position: int | None) -> str | None:
        return None if position is None else f"s-{position + 1}"

    return [
        Section(
            id=f"s-{position + 1}",
            heading=item.text,
            level=item.level,
            kind=item.heading.kind,
            number=item.heading.number,
            number_scheme=item.heading.scheme,
            article_refs=item.heading.refs,
            law=item.heading.law,
            parent=ident(item.parent),
            char_start=starts[item.line],
            char_end=(starts[item.end_line] - 1)
            if item.end_line < len(lines)
            else total,
        )
        for position, item in enumerate(planned)
    ]


def _structure_quality(sections: list[Section]) -> str:
    articles = [s for s in sections if s.kind == KIND_ARTICLE]
    if not articles:
        return QUALITY_NONE
    opener = next((s for s in sections if s.kind == KIND_ARTICLEWISE), None)
    if opener is not None and any(s.char_start > opener.char_start for s in articles):
        return QUALITY_EXPLICIT
    return QUALITY_IMPLICIT


# ── budget papers ────────────────────────────────────────────────────────────

_BUDGET_TITLE_RE = re.compile(
    r"begrotingsstaten|begroting van (?:de )?(?:uitgaven|inkomsten|ontvangsten)|slotwet"
    r"|jaarverslag|suppletoire begroting|rijksbegroting|voorjaarsnota|najaarsnota"
    r"|miljoenennota",
    re.IGNORECASE,
)
_BUDGET_NUMBER_RE = re.compile(r"^\d[\d ]*\s+[IVX]+[A-Z]?$")


def _is_budget(root: ET.Element) -> bool:
    """A budget or annual report: its numbered articles are policy articles, not law articles.

    Recognised by the chapter that follows the dossier number (the modern
    ``begrotingshoofdstuk``, "27 400 XV" in the legacy header) or by a dossier title that says
    so.
    """
    for header in root.iter():
        name = local_name(header.tag)
        if name == "begrotingshoofdstuk":
            return True
        if name not in ("dossier", "onderw"):
            continue
        for node in header.iter():
            text = collapse_ws("".join(node.itertext()))
            kind = local_name(node.tag)
            if kind == "nummer" and _BUDGET_NUMBER_RE.match(text):
                return True
            if kind in ("titel", "naam") and _BUDGET_TITLE_RE.search(text):
                return True
    return False


# ── the entry point ──────────────────────────────────────────────────────────


def parse_kamerstuk(
    xml: str, *, max_chars: int | None = MAX_TEXT_CHARS
) -> ParsedKamerstuk:
    """The text, sections and footnotes of a Kamerstuk XML; never raises.

    XML that cannot be read, or whose root is neither dialect, gives an empty result. A paper
    without headings that make sense gives its text and no sections.
    """
    try:
        root = ET.fromstring(xml.lstrip("﻿"))
    except ET.ParseError:
        return ParsedKamerstuk()
    dialect = local_name(root.tag)
    if dialect not in (DIALECT_LEGACY, DIALECT_MODERN):
        return ParsedKamerstuk()
    try:
        return _parse(root, dialect, max_chars, structure=True)
    except Exception:  # a paper that is odd in a way nobody expected still has its text
        logger.warning("Kamerstuk XML could not be structured; keeping the text only.")
    try:
        return _parse(root, dialect, max_chars, structure=False)
    except Exception:
        return ParsedKamerstuk()


def _parse(
    root: ET.Element, dialect: str, max_chars: int | None, *, structure: bool
) -> ParsedKamerstuk:
    flattener = _Flattener()
    flattener.run(root)
    lines, truncated = _cut(flattener.lines, max_chars)
    starts, total = _offsets(lines)
    sections = _sections(lines, starts, total) if structure else []
    return ParsedKamerstuk(
        text="\n".join(line.text for line in lines),
        sections=sections,
        footnotes=flattener.footnotes,
        dialect=dialect,
        structure_quality=_structure_quality(sections),
        budget=_is_budget(root) if structure else False,
        truncated=truncated,
    )


def _cut(lines: list[_Line], max_chars: int | None) -> tuple[list[_Line], bool]:
    """The lines that fit in *max_chars* of text (whole lines only)."""
    if max_chars is None:
        return lines, False
    used = 0
    for index, line in enumerate(lines):
        used += len(line.text) + (1 if index else 0)
        if used > max_chars:
            return lines[:index], True
    return lines, False


def _offsets(lines: list[_Line]) -> tuple[list[int], int]:
    """Where each line starts in the text, and the length of the text."""
    starts: list[int] = []
    position = 0
    for line in lines:
        starts.append(position)
        position += len(line.text) + 1
    return starts, max(position - 1, 0)
