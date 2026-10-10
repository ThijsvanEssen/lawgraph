"""Which articles each onderdeel of a bill changes, read from the text of the bill, pure.

A bill that changes laws has an ARTIKEL per law, each with its onderdelen::

    ARTIKEL II
    Het Wetboek van Strafvordering wordt als volgt gewijzigd:
    D
    Na artikel 125o wordt een artikel ingevoegd, luidende:
    Artikel 125p

The memorandum explains it per onderdeel ("Artikel II, onderdeel D"), and often without
saying which article that is: the bill says it. ``bill_parts`` reads that from the text of
the bill (``props.text`` of the Voorstel van wet); ``core/mvt_articles.py`` matches it with
the headings of the memorandum (``heading_parts``) and with what the dossier changed.

The numbers are those of the bill as it was sent: the memorandum explains that text, so its
letters are the bill's. An onderdeel that inserts articles changes the articles under its
headings; any other the articles its instruction names before what it quotes or inserts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lawgraph.core.citations import ARTICLE_HEAD_RE, parse_article_numbers

# "ARTIKEL II", "Artikel IIA": an article of a bill, Roman (an article of a law is Arabic).
_ROMAN = r"(?-i:[IVXLC]+[A-Z]?)"
_BILL_ARTICLE_RE = re.compile(rf"^(?:ARTIKEL|Artikel)\s+(?P<n>{_ROMAN})\.?$")
# "Het Wetboek van Strafvordering wordt als volgt gewijzigd:"
_CHANGES_LAW_RE = re.compile(
    r"^(?:het|de)\s+(?P<law>.+?)\s+wordt\s+als\s+volgt\s+gewijzigd\s*[.:]?$",
    re.IGNORECASE,
)
# "A", "Ua", "AA": the letter of an onderdeel, on a line of its own.
_PART = r"(?-i:[A-Z]{1,2}[a-z]{0,2})"
_PART_RE = re.compile(rf"^(?P<p>{_PART})\.?$")
# "Artikel 125p", "Artikel 7:658a", "Artikel 3.4": the heading of an article the bill writes.
_HEADING_RE = re.compile(
    r"^Artikel\s+(?P<n>\d+(?-i:[a-z]*)(?:[.:]\d+(?-i:[a-z]*))*)\.?$"
)
# What follows the instruction's own reference: a quotation, or the new text after a colon
# (the colon of "3:57" is part of the number).
_QUOTED_RE = re.compile(r"«|:(?!\d)")

# "Artikel II, onderdeel D", "Artikel I onderdelen C, D en E", "ARTIKEL III": the article of
# the bill and its onderdelen a heading of a memorandum names.
_PART_LIST = rf"{_PART}(?:\s*(?:,|en|tot\s+en\s+met|t/m)\s*{_PART})*"
_RANGE_RE = re.compile(
    rf"(?P<first>{_PART})\s*(?:tot\s+en\s+met|t/m)\s*(?P<last>{_PART})", re.IGNORECASE
)
_HEADING_PARTS_RE = re.compile(
    rf"^artikel\s+(?P<article>{_ROMAN})(?![\w])"
    rf"(?:\s*,?\s*onderde(?:el|len)\s+(?P<parts>{_PART_LIST})(?![\w]))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BillPart:
    """An onderdeel of an article of a bill ("" for an article without onderdelen)."""

    article: str  # "II"
    part: str  # "D"; "" when the article has none
    law: str | None  # what the article says it changes: "Wetboek van Strafvordering"
    numbers: tuple[str, ...]  # the articles of that law the onderdeel changes
    instruction: str  # its first line, up to what it quotes: it may name the law itself


def _instruction(line: str) -> str:
    """The first line of an onderdeel up to what it quotes or inserts."""
    match = _QUOTED_RE.search(line)
    return (line[: match.start()] if match else line).strip()


def _numbers(instruction: str, lines: list[str]) -> tuple[str, ...]:
    """The articles an onderdeel changes: those it writes under a heading, else those its
    instruction names."""
    headings = [m["n"] for line in lines if (m := _HEADING_RE.match(line))]
    if headings:
        return tuple(dict.fromkeys(headings))
    found: list[str] = []
    for match in ARTICLE_HEAD_RE.finditer(instruction):
        found.extend(parse_article_numbers(match["nums"]))
    return tuple(dict.fromkeys(found))


def _part(article: str, part: str, law: str | None, lines: list[str]) -> BillPart:
    instruction = _instruction(lines[0]) if lines else ""
    return BillPart(article, part, law, _numbers(instruction, lines[1:]), instruction)


def bill_parts(text: str) -> dict[tuple[str, str], BillPart]:
    """The onderdelen of a bill by ``(article, letter)``, in the order of the text; an
    article without onderdelen is ``(article, "")``. A text without ARTIKEL I has none."""
    parts: dict[tuple[str, str], BillPart] = {}
    lines = [line.strip() for line in text.split("\n")]
    starts = [i for i, line in enumerate(lines) if _BILL_ARTICLE_RE.match(line)]
    for n, start in enumerate(starts):
        article = _BILL_ARTICLE_RE.match(lines[start])["n"]  # type: ignore[index]
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        body = [line for line in lines[start + 1 : end] if line]
        changes = _CHANGES_LAW_RE.match(body[0]) if body else None
        if not changes:
            parts[(article, "")] = _part(article, "", None, body)
            continue
        law = changes["law"]
        letters = [i for i, line in enumerate(body) if i and _PART_RE.match(line)]
        for k, at in enumerate(letters):
            letter = _PART_RE.match(body[at])["p"]  # type: ignore[index]
            until = letters[k + 1] if k + 1 < len(letters) else len(body)
            parts[(article, letter)] = _part(article, letter, law, body[at + 1 : until])
    return parts


def heading_parts(heading: str) -> tuple[str, tuple[str, ...]] | None:
    """The article of a bill and its onderdelen a heading names ("" for the article as a
    whole): ``("II", ("H", "I"))`` for "Artikel II, onderdelen H en I"; None for a
    heading that names no article of a bill."""
    match = _HEADING_PARTS_RE.match(heading.strip())
    if not match:
        return None
    if not match["parts"]:
        return match["article"], ("",)
    return match["article"], part_letters(match["parts"])


def heading_law(heading: str) -> str | None:
    """What a heading of an article of a bill says after its number and onderdelen: the
    law it changes in "ARTIKEL II – WETBOEK VAN STRAFRECHT" or "Artikel III (Woningwet)";
    None when it says nothing more."""
    match = _HEADING_PARTS_RE.match(heading.strip())
    if not match:
        return None
    rest = heading.strip()[match.end() :].strip(" \t–—-:,.()")
    return rest or None


def part_letters(listing: str) -> tuple[str, ...]:
    """The onderdelen of a list as a heading writes it: "H en I", "C, D en E",
    "CS tot en met CV" (CS, CT, CU, CV)."""
    letters: list[str] = []
    for item in re.split(r"\s*,\s*|\s+en\s+(?!met\b)", listing.strip()):
        if span := _RANGE_RE.fullmatch(item):
            letters += _letter_range(span["first"], span["last"])
        elif item:
            letters.append(item)
    return tuple(letters)


def _letter_index(letters: str) -> int | None:
    """The place of an onderdeel in A, …, Z, AA, AB, …; None for one with a small letter."""
    if not letters.isupper():
        return None
    if len(letters) == 1:
        return ord(letters) - ord("A")
    return 26 + (ord(letters[0]) - ord("A")) * 26 + ord(letters[1]) - ord("A")


def _letter_of(index: int) -> str:
    if index < 26:
        return chr(ord("A") + index)
    first, second = divmod(index - 26, 26)
    return chr(ord("A") + first) + chr(ord("A") + second)


def _letter_range(first: str, last: str) -> list[str]:
    """The onderdelen from *first* to *last*: "CS tot en met CV" is CS, CT, CU and CV."""
    start, end = _letter_index(first), _letter_index(last)
    if start is None or end is None or end < start:
        return [first, last]
    return [_letter_of(i) for i in range(start, end + 1)]
