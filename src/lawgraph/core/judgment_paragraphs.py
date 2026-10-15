"""The paragraphs of a Rechtspraak judgment: its kop, its numbered considerations and
headings, its table of contents and signature, its footnotes, and the id of each paragraph
in a deep link. Pure: no I/O, no store."""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from lawgraph.core.dutch_names import INITIAL
from lawgraph.core.judgment_metadata import LINE_BREAK, judgment_bodies
from lawgraph.core.xml import (
    after_nonspace,
    child_named,
    collapse_ws,
    first_named,
    iter_named,
    local_name,
    text_of,
)

# ── <uitspraak> structure ────────────────────────────────────────────────────
#
# A judgment numbers its considerations (overwegingen): "5.3" is the third paragraph of the
# fifth section, cited as "rov. 5.3". The XML writes the number as ``<nr>`` in a
# ``<paragroup>`` (a numbered unit, nested as deep as the numbering goes) or in the
# ``<title>`` of a ``<section>``; many courts put it in front of the text of a ``<para>``
# instead ("1.    Bij het besluit ..."). Both are read as the printed number of a paragraph.
#
# Before the first section heading stands the kop: the court, the case number, the date and
# the parties. Courts write it in an ``<uitspraak.info>``, in loose paragraphs, in
# bridgeheads or in sections whose titles are party names; it is read line by line, whatever
# holds the lines.


class ParagraphKind(StrEnum):
    """The kind of a paragraph of a judgment (``judgment_text``)."""

    HEADING = "heading"
    SUBHEADING = "subheading"
    BODY = "body"
    SIGNATURE = "signature"
    TOC = "toc"  # a line of a table of contents: no consideration, no heading


def heading_kind(depth: int) -> ParagraphKind:
    """The kind of a heading at *depth*: a ``heading`` at the top, a ``subheading`` in a
    section."""
    return ParagraphKind.HEADING if depth == 0 else ParagraphKind.SUBHEADING


# "5.3 text", "12. text", "4.100. text": digits, a dot or a dotted number, then a space. A
# number alone ("1 februari 2013") is not one: a date opens a sentence too; nor is an amount
# ("1.500 euro"): a part of three digits needs the closing dot.
_LEADING_NUMBER = re.compile(
    r"^(\d{1,3}(?:\.\d{1,2})+\.?|\d{1,3}(?:\.\d{1,3})+\.|\d{1,3}\.)\s+(?=\S)"
)
_NOT_TEXT = {"title", "footnote", "nr"}
_BLOCKS = {"para", "parablock", "paragroup", "list", "li", "table", "al"}
# The elements that print a line of their own: paragraphs, bridgeheads (a bold line), the
# titles of sections and the rows of a table.
_LINE_ELEMENTS = {"para", "bridgehead", "title", "row"}

# The line that ends the kop: the heading of the first section, numbered or not ("1 Het
# verloop van de procedure", "Procesverloop", "Onderzoek van de zaak", "SAMENVATTING").
_SECTION_HEADING = re.compile(
    r"^(?:\d{1,2}(?:\.\d{1,2})*\.?\s*|[IVX]{1,4}[.)]?\s+|[A-Z][.)]\s*)?(?:"
    r"(?:het\s+)?proces-?verloop|(?:de\s+)?procesgang|(?:het\s+)?cassatieberoep$|"
    r"(?:de\s+)?(?:\w+\s+)?procedure\b|"
    r"(?:het\s+)?(?:verdere?\s+)?verloop\s+van\s+(?:de|het)\b|(?:de\s+)?loop\s+van\s+het\s+geding|"
    r"(?:het\s+)?ontstaan\s+en\s+(?:de\s+)?loop\b|"
    r"(?:het\s+)?onderzoek\s+(?:van\s+de\s+zaak|ter\s+(?:terecht)?zitting|op\s+de\s+)|"
    r"(?:de\s+)?samenvatting|inleiding|overwegingen|(?:de\s+)?beoordeling|"
    r"(?:de\s+)?tenlastelegging|(?:het\s+)?geding\s+in\b|(?:het\s+)?hoger\s+beroep$|"
    r"(?:de\s+)?(?:vaststaande\s+)?feiten\b|(?:het\s+)?geschil\b|"
    r"waar\s+gaat\s+(?:de(?:ze)?\s+zaak|het)\s+over|(?:de\s+)?zaak\s+in\s+het\s+kort|"
    r"verzoek\s+en\s+verweer|(?:de\s+)?uitgangspunten|(?:de\s+)?zitting$|"
    r"(?:het\s+)?vonnis\s+waarvan\s+beroep|(?:de\s+)?beslissing\s+van\s+de\s+kantonrechter|"
    r"(?:het\s+|de\s+)?(?:bestreden|aangevallen)\s+(?:vonnis|arrest|"
    r"(?:eind)?uitspra(?:ak|ken)|beschikking|besluit)|(?:het\s+)?geding$|inhoudsopgave|"
    r"(?:de\s+)?(?:uitspraak|beschikking)\s+van\s+(?:het\s+hof|de\s+rechtbank)$|"
    r"(?:de\s+)?inhoud\s+van\s+het\s+(?:verzoek|klaagschrift|beroep)|"
    r"(?:het\s+|de\s+)?(?:eerdere\s+)?tussen(?:arrest|vonnis|uitspraak|beschikking)$|"
    r"(?:lijst\s+van\s+)?(?:gebruikte\s+)?afkortingen$"
    r")",
    re.IGNORECASE,
)
# The element a conclusion writes its kop in: the kop ends with it, if no heading ends it
# before (a list of abbreviations can close it).
_KOP_ELEMENTS = frozenset({"conclusie.info"})
# The kop names parties, a hundred in a mass claim, but tells no story: text before the
# first heading with more lines of prose than this is no kop (old judgments put their
# first heading late, or not at all).
KOP_MAX_PROSE_LINES = 4
PROSE_LINE_CHARS = 200


def _slug(number: str) -> str:
    """The printed number as written in an id: ``"5.3."`` is ``"5.3"``."""
    return re.sub(r"[^0-9a-z.]", "", number.lower()).strip(".")


def _flat(element: ET.Element) -> str:
    """The text of an element on one line; inline markup stays inside the word."""
    blocks = any(local_name(child.tag) in _BLOCKS for child in element)
    return collapse_ws(text_of(element, " " if blocks else ""))


def _unit_text(
    element: ET.Element, skip: set[int] | frozenset[int] = frozenset()
) -> str:
    """The text of a ``<para>`` or ``<parablock>``: its paragraphs, a blank line between.

    A ``<para>`` holds no other blocks, only inline markup (emphasis, footnote references,
    links); the paragraphs in *skip* were read into the kop.
    """
    paras = list(iter_named(element, "para", "bridgehead"))
    if not paras:
        return _flat(element)
    return "\n\n".join(t for p in paras if id(p) not in skip and (t := _flat(p)))


def _split_number(text: str) -> tuple[str | None, str]:
    """``("5.3", "text")`` for text that opens with a printed number, else ``(None, text)``."""
    match = _LEADING_NUMBER.match(text)
    if not match:
        return None, text
    return match[1].rstrip("."), text[match.end() :]


_DOTTED_NUMBER = re.compile(r"\d+(?:\.\d+)*")


def _number_parts(number: str) -> tuple[int, ...]:
    """``(4, 100)`` for ``"4.100"``: the parts of a printed number, as numbers."""
    return tuple(int(part) for part in number.rstrip(".").split("."))


def _follows(number: str | None, previous: str) -> bool:
    """Is *number* a later consideration of the level of *previous*: ``4.100`` after
    ``4.99`` (part by part, as numbers), not ``5.1`` nor ``4.99.1`` nor ``1``?"""
    if not number or not _DOTTED_NUMBER.fullmatch(previous.rstrip(".")):
        return False
    *head, last = _number_parts(number)
    *previous_head, previous_last = _number_parts(previous)
    return head == previous_head and last > previous_last


def line_elements(element: ET.Element) -> Iterator[ET.Element]:
    """The elements of *element* that print a line (``_LINE_ELEMENTS``), in reading order;
    footnotes left out."""
    for child in element:
        name = local_name(child.tag)
        if name in _LINE_ELEMENTS:
            yield child
        elif name != "footnote":
            yield from line_elements(child)


def printed_lines(element: ET.Element) -> list[str]:
    """The lines a line element prints: split at its line breaks; a title or a table row
    is one line, its parts a space apart."""
    sep = " " if local_name(element.tag) in ("title", "row") else ""
    parts = (collapse_ws(part) for part in text_of(element, sep).split(LINE_BREAK))
    return [part for part in parts if part]


def is_section_heading(line: str) -> bool:
    """Does *line* open the first section of a judgment, and so end its kop?"""
    return len(line) <= 90 and bool(_SECTION_HEADING.match(line))


# The containers whose children ``_Sections.walk`` reads one by one: a list in one of them
# stands on its own, not in the text of a paragraph.
_WALKED = frozenset(
    {
        "uitspraak",
        "conclusie",
        "section",
        "parablock",
        "uitspraak.info",
        "conclusie.info",
    }
)


# The mean length of the items of a numbered list whose items are paragraphs (the points
# of a conclusion), not an enumeration ("1.00 STK Telefoontoestel", the goods seized).
LIST_PARAGRAPH_CHARS = 120


def _is_numbered_list(element: ET.Element) -> bool:
    """A list numbered 1, 2, 3 (``numeration="arabic"``) of paragraphs: its items are
    paragraphs with their place as number, where the list stands on its own."""
    if not (
        local_name(element.tag) == "orderedlist"
        and element.get("numeration") == "arabic"
    ):
        return False
    lengths = [
        len(collapse_ws(text_of(item, " ")))
        for item in element
        if local_name(item.tag) == "listitem"
    ]
    return bool(lengths) and sum(lengths) / len(lengths) >= LIST_PARAGRAPH_CHARS


def _numbered_lines(uitspraak: ET.Element) -> set[int]:
    """The ids of the line elements of a numbered unit: a title with its ``<nr>``, a
    ``<paragroup>`` with its ``<nr>``, the items of a numbered list that stands on its own.
    None of them is kop: a kop has no numbers."""
    numbered: set[int] = set()

    def visit(element: ET.Element) -> None:
        for child in element:
            name = local_name(child.tag)
            has_nr = any(local_name(c.tag) == "nr" for c in child)
            if (name in ("title", "paragroup") and has_nr) or (
                _is_numbered_list(child) and local_name(element.tag) in _WALKED
            ):
                numbered.update(id(e) for e in child.iter())
            else:
                visit(child)

    visit(uitspraak)
    return numbered


# The line that names a party in the kop: "hierna: de verdachte", "(hierna: ICAM)".
_NAMES_A_PARTY = re.compile(r"^\(?hierna\b", re.IGNORECASE)
# A line between parties ("en", "tegen", "t e g e n :"): the next one is a party, even when
# the source numbers it as a section ("1 De Fontein B.V.").
_JOINS_PARTIES = re.compile(
    r"^(?:en|tegen|t\s?e\s?g\s?e\s?n|in de zaak van|tussen|en tegen)\s*:?$",
    re.IGNORECASE,
)


def _read_kop(uitspraak: ET.Element) -> tuple[list[str], set[int]]:
    """``(lines, elements)`` of the kop: every line before the first section heading, or
    before the first numbered unit (``_numbered_lines``) once the kop has named a party
    ("hierna: …") or its ``<uitspraak.info>`` is over, and the ids of the elements that
    print them. When no heading ends it, or only after more
    than ``KOP_MAX_PROSE_LINES`` lines of prose, the ``<conclusie.info>`` of a conclusion
    is its kop, and a judgment has none: without headings there is no kop to tell apart.
    """
    info = next((c for c in uitspraak if local_name(c.tag) in _KOP_ELEMENTS), None)
    in_info = {id(e) for e in line_elements(info)} if info is not None else set()
    lines: list[str] = []
    elements: set[int] = set()
    info_kop: tuple[list[str], set[int]] = ([], set())
    prose = 0
    numbered = _numbered_lines(uitspraak)
    for element in line_elements(uitspraak):
        if not info_kop[0] and elements & in_info and id(element) not in in_info:
            info_kop = (list(lines), set(elements))  # the end of the info
        printed = printed_lines(element)
        if printed and is_section_heading(printed[0]):
            return lines, elements
        if (
            id(element) in numbered
            and not (lines and _JOINS_PARTIES.match(lines[-1]))
            and (
                any(_NAMES_A_PARTY.match(line) for line in lines)
                or bool(elements & in_info and id(element) not in in_info)
            )
        ):
            return lines, elements  # the parties are named, or the info is over
        prose += sum(len(line) > PROSE_LINE_CHARS for line in printed)
        if prose > KOP_MAX_PROSE_LINES:
            break
        lines.extend(printed)
        elements.add(id(element))
    return info_kop


def kop_lines(root: ET.Element) -> list[str]:
    """The lines of the kop of the first ``<uitspraak>`` or ``<conclusie>`` (see
    ``_read_kop``)."""
    uitspraak = next(iter(judgment_bodies(root)), None)
    return _read_kop(uitspraak)[0] if uitspraak is not None else []


# The footnotes a paragraph refers to (``<footnote-ref linkend>``) and where their markers
# stand, until the paragraphs are named: the characters other than whitespace of the
# elements the paragraph is read from, and per marker its ``linkend`` and how many of them
# come before it.
_Marks = tuple[str, list[tuple[str, int]]]


@dataclass
class _Entry:
    """A paragraph as read, before it is named (``_name``)."""

    number: str | None
    kind: ParagraphKind
    text: str
    marks: _Marks
    # the kind of heading a paragraph set like one (``_may_be_heading``) is, if
    # ``_promote_headings`` makes it one
    candidate: ParagraphKind | None = None


class _Sections:
    """The paragraphs of an ``<uitspraak>``, in reading order."""

    def __init__(self, kop: set[int]) -> None:
        self.entries: list[_Entry] = []  # named once all are read (_name)
        self._kop = kop  # the elements read into the kop

    def add(
        self,
        kind: ParagraphKind,
        number: str | None,
        text: str,
        source: Sequence[ET.Element] = (),
        candidate: ParagraphKind | None = None,
    ) -> None:
        """One paragraph; *source* the elements it is read from, whose footnote references
        it keeps (``_Entry.marks``)."""
        # "6.16." as a list prints it: the number is 6.16
        number = number.rstrip(".") if number else number
        if not text and not number:
            return
        if number and not _slug(number):
            number = None
        marks = _footnote_marks(source)
        self.entries.append(_Entry(number, kind, text, marks, candidate))

    def unnumbered(
        self, kind: ParagraphKind, text: str, source: Sequence[ET.Element] = ()
    ) -> None:
        """A paragraph that may open with its number."""
        number, rest = _split_number(text)
        self.add(kind, number, rest, source)

    def walk(self, container: ET.Element, depth: int = 0) -> None:
        """Every child of an ``<uitspraak>``, a ``<section>`` or a ``<paragroup>``."""
        for child in container:
            name = local_name(child.tag)
            if id(child) in self._kop:
                continue
            if name == "section":
                self.section(child, depth)
            elif name == "paragroup":
                self.paragroup(child, depth)
            elif name in ("uitspraak.info", "conclusie.info", "parablock"):
                # the kop, when a court writes the judgment in it, or a run of paragraphs
                self.walk(child, depth)
            elif name == "bridgehead":
                text = _flat(child)
                self.add(_heading_kind(depth, text), None, text, [child])
            elif _is_numbered_list(child):
                self.numbered_list(child)
            elif name not in _NOT_TEXT:  # para, al and any other body element
                text = _unit_text(child, self._kop)
                if _may_be_heading(child, text):
                    self.add(
                        ParagraphKind.BODY, None, text, [child], heading_kind(depth)
                    )
                else:
                    self.unnumbered(ParagraphKind.BODY, text, [child])

    def numbered_list(self, items: ET.Element) -> None:
        """A numbered list that stands on its own: each item a paragraph, its place in the
        list its number (the source prints 1, 2, 3 and writes none)."""
        place = 0
        for item in items:
            if local_name(item.tag) != "listitem":
                continue
            place += 1
            self.add(
                ParagraphKind.BODY, str(place), _unit_text(item, self._kop), [item]
            )

    def section(self, section: ET.Element, depth: int) -> None:
        title = child_named(section, "title")
        if title is not None and id(title) not in self._kop:
            number = collapse_ws(text_of(first_named(title, "nr"))) or None
            text = collapse_ws(text_of(title, " "))
            if number and text.startswith(number):
                text = text[len(number) :].strip()
            kind = _heading_kind(depth, text) if number is None else heading_kind(depth)
            self.add(kind, number, text, [title])
        self.walk(section, depth + 1)

    def paragroup(self, group: ET.Element, depth: int) -> None:
        """A numbered unit: its own paragraphs are one entry, nested units follow."""
        nr = child_named(group, "nr")
        number = collapse_ws(text_of(nr)) or None
        if number is None:
            self.walk(group, depth)
            return
        own: list[tuple[ET.Element, str]] = []  # each with its text
        for child in group:
            name = local_name(child.tag)
            if name in ("paragroup", "section"):
                self.flush(number, own, depth)
                (self.paragroup if name == "paragroup" else self.section)(child, depth)
            elif name not in _NOT_TEXT and id(child) not in self._kop:
                text = _unit_text(child, self._kop)
                # a court that writes its next considerations inside the unit (4.100 in
                # the unit of 4.99): each ends the one before
                printed, _ = _split_number(text)
                if printed and _follows(printed, number):
                    self.flush(number, own, depth)
                    number = printed
                own.append((child, text))
        self.flush(number, own, depth)

    def flush(self, number: str, own: list[tuple[ET.Element, str]], depth: int) -> None:
        """The own paragraphs of a numbered unit, each with its text, as one; a heading
        they end with ("faalt." and then "Slotsom" in italics) is a paragraph of its own
        after it."""
        texts = [(child, text) for child, text in own if text]
        own.clear()
        if texts:  # the number a unit's text opens with, when it is the unit's own
            printed, rest = _split_number(texts[0][1])
            if printed == number.rstrip("."):
                texts[0] = (texts[0][0], rest)
        heading = None
        if len(texts) > 1 and _is_heading_line(texts[-1][0]):
            heading = texts.pop()
        if texts:
            self.add(
                ParagraphKind.BODY,
                number,
                "\n\n".join(text for _, text in texts),
                [child for child, _ in texts],
            )
        if heading:
            self.add(heading_kind(depth), None, heading[1], [heading[0]])


# A heading a numbered unit ends with is no longer than this.
HEADING_LINE_CHARS = 80

# A line of text the source sets as a title or a bold line: a phrase of a quoted record
# ("[verdachte] ,", "is niet verschenen.", "met bevel tot oproeping …,") or the opening of a
# quote ("‘Ontvankelijkheid van het hoger beroep"). A heading opens with no quotation mark
# nor bracket and ends with no comma; one in small letters ("in de hoofdzaak") ends in no
# punctuation either and is more than a word like "en".
_QUOTE_OPENS = ("‘", "“", "„", "'", '"', "[", "«")
_PHRASE_ENDS = (".", ",", ";", "!", "?")


def is_text_line(text: str) -> bool:
    """Is *text*, set as a heading, a line of text (a phrase, a quote) instead?"""
    text = text.strip()
    if not text:
        return False
    if text.startswith(_QUOTE_OPENS) or text.endswith((",", ";")):
        return True
    return text[0].islower() and (text.endswith(_PHRASE_ENDS) or len(text) <= 3)


def _heading_kind(depth: int, text: str) -> ParagraphKind:
    """The kind of a title or a bold line without a number: a heading by its depth, or
    ``body`` when it is a line of text (``is_text_line``)."""
    if is_text_line(text):
        return ParagraphKind.BODY
    return heading_kind(depth)


def _footnote_marks(source: Sequence[ET.Element]) -> _Marks:
    """The characters other than whitespace of *source*, in reading order, and per
    ``<footnote-ref>`` in it its ``linkend`` and how many of them come before it; none
    (``("", [])``) without a reference, the many paragraphs that have none."""
    pieces: list[str] = []
    refs: list[tuple[str, int]] = []  # per reference, how many pieces come before it

    def read(element: ET.Element) -> None:
        if local_name(element.tag) == "footnote-ref":
            if linkend := element.get("linkend"):
                refs.append((linkend, len(pieces)))
        pieces.append(element.text or "")
        for child in element:
            read(child)
            pieces.append(child.tail or "")

    for element in source:
        read(element)
    if not refs:
        return "", []
    words = _nonspace("".join(pieces))
    return words, [
        (linkend, len(_nonspace("".join(pieces[:at])))) for linkend, at in refs
    ]


def _nonspace(text: str) -> str:
    """*text* without its whitespace."""
    return "".join(text.split())


def _marker_at(text: str, words: str, before: int) -> int | None:
    """Where a footnote marker stands in *text*, the paragraph as read: after its
    *before* th character other than whitespace of *words*, the characters of the
    elements it is read from. The paragraph may lack what opens them (a number it
    printed); when it is not the rest of them, the place is not known (None)."""
    own = _nonspace(text)
    skipped = len(words) - len(own)
    if skipped < 0 or words[skipped:] != own or before < skipped:
        return None
    return after_nonspace(text, before - skipped)


# What a heading does not hold (``_may_be_heading``): a year, a "label : value", an amount,
# a page of the case file ("Dossierpagina 100037"), the initials of a name ("J.C.
# Kranenburg" under a judgment).
_NOT_IN_A_HEADING = re.compile(
    r"\b\d{4}\b|\s:\s|:$|€|^dossierpagina\b"
    rf"|\b(?:[A-Z]{{1,2}}|{INITIAL})\.(?:[A-Z]{{1,2}}\.)*\s",
    re.IGNORECASE,
)


def _may_be_heading(element: ET.Element, text: str) -> bool:
    """Is *element*, a plain paragraph, set like a heading: one line of at most
    ``HEADING_LINE_CHARS``, opening with a capital, no number in front, ending in no
    punctuation ("Procesverloop", "Toetsingskader", "Het hoger beroep van [appellant]")?"""
    return (
        local_name(element.tag) == "para"
        and 0 < len(text) <= HEADING_LINE_CHARS
        and "\n" not in text
        and text[0].isupper()
        and _split_number(text)[0] is None
        and not text.endswith((".", ",", ";", ":", "?", "!", "”", '"', "’", "'"))
        and not _NOT_IN_A_HEADING.search(text)
    )


def _is_heading_line(element: ET.Element) -> bool:
    """Is *element* a heading set as a paragraph: one short line, all of it in emphasis,
    that ends in no punctuation ("Slotsom" in italics)?"""
    paras = [p for p in iter_named(element, "para") if _flat(p)]
    if len(paras) != 1 or (paras[0].text or "").strip():
        return False
    children = list(paras[0])
    text = _flat(paras[0])
    return (
        bool(children)
        and all(
            local_name(c.tag) == "emphasis" and not (c.tail or "").strip()
            for c in children
        )
        and len(text) <= HEADING_LINE_CHARS
        and not text.endswith((".", ",", ";", ":", "?", "!", "”", '"'))
    )


def _unquote_headings(entries: list[_Entry]) -> None:
    """A run of numbered headings that goes back in the numbering, after which the
    numbering goes on where it was ("6", then "3 Proceskosten" and "4 Beslissing", then
    "7"): the headings of a decision the text quotes, whose sections the XML closes the
    text's own section with. They are text of the quote: a ``body`` paragraph, the number
    in front of its text. Numbering that starts again (1, 2, 1, 2, 3) is left as it is."""
    last = 0  # the last number of the text's own headings
    run: list[_Entry] = []
    for entry in entries:
        number = entry.number or ""
        if entry.kind != ParagraphKind.HEADING or not number.isdigit():
            continue
        if int(number) <= last:
            run.append(entry)
            continue
        if run and int(number) == last + 1 != int(run[-1].number or 0) + 1:
            for quoted in run:
                quoted.kind = ParagraphKind.BODY
                quoted.text = f"{quoted.number} {quoted.text}"
                quoted.number = None
        run, last = [], int(number)


# The signature of the Parket at the end of a conclusion: "De Procureur-Generaal bij de",
# "Hoge Raad der Nederlanden", "A-G" (or "Advocaat-Generaal", "Plv.").
_SIGNATURE_OPENS = re.compile(r"^de\s+procureur-generaal\b", re.IGNORECASE)
SIGNATURE_OPENING_CHARS = 80
SIGNATURE_LINE_CHARS = 40
SIGNATURE_MAX_LINES = 4


def _mark_signature(entries: list[_Entry]) -> None:
    """The closing lines of a conclusion that sign it: from the last short line that opens
    with "De Procureur-Generaal" to the end, when no more than ``SIGNATURE_MAX_LINES``
    short lines without a number follow it (a bold "AG" is read as a heading); kind
    ``signature``."""
    tail: list[_Entry] = []
    for entry in reversed(entries):
        text = entry.text
        if entry.number:
            return
        if len(text) <= SIGNATURE_OPENING_CHARS and _SIGNATURE_OPENS.match(text):
            for signed in [entry, *tail]:
                signed.kind = ParagraphKind.SIGNATURE
            return
        if len(text) > SIGNATURE_LINE_CHARS or len(tail) == SIGNATURE_MAX_LINES:
            return
        tail.append(entry)


# More plain lines set like headings in a row are a list (abbreviations, names), no
# headings: "Overwegingen" and then "Inleiding" are two.
MAX_HEADINGS_IN_A_ROW = 2


def _promote_headings(entries: list[_Entry]) -> None:
    """Plain paragraphs set like a heading (``_may_be_heading``), at most
    ``MAX_HEADINGS_IN_A_ROW`` in a row, are headings when text follows them: a ``body``
    paragraph with a number, longer than ``HEADING_LINE_CHARS`` or opening what follows
    (ending with a colon). A short line at the end (a name under a judgment) stays text."""
    at = 0
    while at < len(entries):
        run = at
        while run < len(entries) and entries[run].candidate is not None:
            run += 1
        if run == at:
            at += 1
            continue
        after = entries[run] if run < len(entries) else None
        if (
            run - at <= MAX_HEADINGS_IN_A_ROW
            and after is not None
            and after.kind == ParagraphKind.BODY
            and (
                after.number
                or len(after.text) > HEADING_LINE_CHARS
                or after.text.endswith(":")
            )
        ):
            for entry in entries[at:run]:
                entry.kind = entry.candidate or entry.kind
        at = run


# The heading of a table of contents ("Inhoudsopgave", "Inhoud").
_TOC_HEADING = re.compile(r"^inhoud(?:sopgave)?:?$", re.IGNORECASE)
# The lines a table of contents has at most before the heading it lists first, and the
# length of one: a longer paragraph is text, and ends it.
TOC_MAX_LINES = 80
TOC_LINE_CHARS = 200


def _mark_toc(entries: list[_Entry]) -> None:
    """A table of contents: its heading, then its lines up to the first heading, the first
    paragraph of text (longer than ``TOC_LINE_CHARS``) or the line it listed first, where
    the text begins ("1 Overzicht" as a numbered paragraph). Its numbered lines are no
    considerations (``rov-1`` …), its lines kind ``toc``."""
    start = next(
        (at for at, e in enumerate(entries) if _TOC_HEADING.match(e.text.strip())),
        None,
    )
    if start is None:
        return
    lines: list[_Entry] = []
    for entry in entries[start + 1 : start + 1 + TOC_MAX_LINES]:
        if (
            entry.kind in (ParagraphKind.HEADING, ParagraphKind.SUBHEADING)
            or len(entry.text) > TOC_LINE_CHARS
            or (lines and _same_line(entry, lines[0]))  # the text begins
        ):
            break
        lines.append(entry)
    else:
        return  # no heading follows: no table of contents
    if sum(1 for e in lines if e.number) < 2:
        return
    if entries[start].kind == ParagraphKind.BODY:
        entries[start].kind = ParagraphKind.HEADING
    for entry in lines:
        entry.kind = ParagraphKind.TOC


def _same_line(one: _Entry, other: _Entry) -> bool:
    return one.number == other.number and one.text.strip() == other.text.strip()


def text_id(text: str) -> str:
    """The id of a paragraph without a number: ``p-`` and the first 8 hex of the SHA-1 of
    its text, its whitespace collapsed. It follows the text, not the position, so a
    paragraph keeps its deep link when another one before it comes or goes."""
    digest = hashlib.sha1(collapse_ws(text).encode(), usedforsecurity=False)
    return f"p-{digest.hexdigest()[:8]}"


def _name(entries: list[_Entry]) -> list[dict[str, Any]]:
    """*entries* with their ``id`` (see ``judgment_text``)."""
    seen: dict[str, int] = {}
    named = []
    owner: str | None = None  # the numbered consideration a paragraph goes on with
    for entry in entries:
        number, kind = entry.number, entry.kind
        if number and kind == ParagraphKind.BODY:
            base = f"rov-{_slug(number)}"
        elif number and kind in (ParagraphKind.HEADING, ParagraphKind.SUBHEADING):
            base = f"kop-{_slug(number)}"
        else:  # no number, or a line of a table of contents
            base = text_id(f"{number} {entry.text}" if number else entry.text)
        seen[base] = seen.get(base, 0) + 1
        paragraph_id = base if seen[base] == 1 else f"{base}_{seen[base]}"
        paragraph = {
            "id": paragraph_id,
            "number": number,
            "kind": kind,
            "text": entry.text,
        }
        if kind == ParagraphKind.BODY and number:
            owner = paragraph_id
        elif kind == ParagraphKind.BODY and owner:
            paragraph["continues"] = owner
        else:
            owner = None
        named.append(paragraph)
    return named


def judgment_text(
    root: ET.Element,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(paragraphs, footnotes)`` of the first ``<uitspraak>`` (or ``<conclusie>``).

    The paragraphs are ``{id, number, kind, text}`` each. The footnotes are no paragraph:
    ``{label, paragraph_id, text, at}`` each, in their order, ``paragraph_id`` the
    paragraph whose ``<footnote-ref>`` points to it (the first), null when none does, and
    ``at`` where that marker stands in its text (absent when that is not known).

    ``kind`` is ``heading`` (a section or a bridgehead), ``subheading`` (a nested one, or
    the kop), ``body`` or ``signature`` (the closing lines that sign a conclusion,
    ``_mark_signature``). The kop (``_read_kop``), when the judgment has one, is the first
    paragraph: a ``subheading`` of its lines, a blank line between. A numbered unit
    (``<paragroup>``) is one ``body`` paragraph however many ``<para>`` it holds, and each
    nested unit another: the text of "5.3" does not contain "5.3.1". ``number`` is the
    printed number without its closing dot (``"5.3"``), null when the paragraph has none,
    and is not part of ``text``.

    ``id`` names a paragraph in a deep link and is unique in the judgment: ``rov-5.3`` for
    a numbered ``body`` paragraph, ``kop-5`` for a numbered heading, ``p-3f2a9c1e``
    (``text_id``: from its text, not its position) for a paragraph without a number. An id
    that repeats one before it gets ``_<n>``, its occurrence (``rov-1_2``: the judgments of
    some courts number their procedure and their considerations from 1 each).
    """
    uitspraak = next(iter(judgment_bodies(root)), None)
    if uitspraak is None:
        return [], []
    lines, kop = _read_kop(uitspraak)
    sections = _Sections(kop)
    sections.add(ParagraphKind.SUBHEADING, None, "\n\n".join(lines))
    sections.walk(uitspraak)
    _promote_headings(sections.entries)
    _mark_toc(sections.entries)
    _unquote_headings(sections.entries)
    _mark_signature(sections.entries)
    marks = [entry.marks for entry in sections.entries]
    paragraphs = _name(sections.entries)
    referred: dict[str, tuple[str, int | None]] = {}
    for paragraph, (words, refs) in zip(paragraphs, marks, strict=True):
        for footnote_id, before in refs:
            if footnote_id not in referred:
                at = _marker_at(paragraph["text"], words, before)
                referred[footnote_id] = (paragraph["id"], at)
    footnotes = []
    for note in iter_named(uitspraak, "footnote"):
        text = collapse_ws(text_of(note, " "))
        if not text:
            continue
        paragraph_id, at = referred.get(note.get("id") or "", (None, None))
        footnotes.append(
            {
                "label": note.get("label"),
                "paragraph_id": paragraph_id,
                "text": text,
                **({"at": at} if at is not None else {}),
            }
        )
    return paragraphs, footnotes
