"""A judgment of the courts of the European Union as EUR-Lex holds it — pure, no I/O.

EUR-Lex numbers its case law in sector 6 of CELEX: ``6``, the year the case was brought, a
descriptor of two letters and the number of the case in four digits. The first letter is
the court (``C`` the Court of Justice, ``T`` the General Court, ``F`` the Civil Service
Tribunal), the second the document (``J`` a judgment, ``O`` an order, ``C`` the opinion of
an advocate-general): ``62018CJ0311`` is the judgment in case C-311/18. A case brought
before 1989, when the General Court came, has no letter in its number (``26/63``).

What CELLAR says of a judgment besides its text (``EUClient.judgment_facts``, kept with the
record): its ECLI, its date, its Dutch title and the national decisions of its case. The
title is in parts split by ``#``: the court and the date, the parties, then the subject
("Arrest van het Hof (Grote kamer) van 16 juli 2020.#Data Protection Commissioner tegen
Facebook Ireland Ltd en Maximillian Schrems.#…"). The national decisions are paragraphs, each
with its role in front: ``*A9*`` the decision that referred the questions, ``*A8*`` an
earlier decision of the case, ``*P1*`` a decision after the ruling ("*A9* Rechtbank
Rotterdam, Uitspraak van 20/03/2020 (ROT 19/1249)").

The text, as CELLAR serves it, comes in one of three formats: the XHTML of the judgments
since about 2014 (``p.coj-…``: a numbered paragraph is a table row of its number and its
text), the HTML of the years before (``P.C01Pointnumerote…``: the number, spaces and the
text in one paragraph) and the page of the oldest judgments (the text in ``div#TexteOnly``,
in flat paragraphs). Every paragraph is read in order, and a row of a table as one
paragraph.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from lawgraph.core.case_numbers import Referral
from lawgraph.core.ecli import cited_eclis
from lawgraph.core.eurlex_html import parse_html
from lawgraph.core.judgment_kinds import KIND_CONCLUSIE, JudgmentKind
from lawgraph.core.judgment_paragraphs import ParagraphIds, ParagraphKind
from lawgraph.core.xml import collapse_ws

# Sector 6, the year, the court and the document, the number; a CELEX of a part of a case
# ("62019CJ0311(01)") has its own text.
_CELEX = re.compile(r"^6(\d{4})([CTF])([A-Z])(\d{4})(?:\(\d+\))?$")
# The year the General Court came, and with it the letter in front of a case number.
_FIRST_LETTERED_YEAR = 1989
_KIND_OF_DOCUMENT: dict[str, JudgmentKind] = {
    "J": "arrest",
    "O": "beschikking",
    "C": KIND_CONCLUSIE,
}
# The role of the decision that referred the questions, in the national decisions.
_REFERRING = "*A9*"
# The date and the case numbers of a national decision: "van 20/03/2020 (ROT 19/1249)".
_NATIONAL_DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")

# The markup of a paragraph: a heading, a heading below it, the signature.
_HEADING = re.compile(r"coj-sum-title-1|Titre1|^S40Titre")
_SUBHEADING = re.compile(r"coj-title-grseq|Titre[2-9]")
_SIGNATURE = re.compile(r"signature", re.IGNORECASE)
_HEADING_TAGS = frozenset({"h1", "h2"})
# A paragraph that opens with its number: "1       Het verzoek …" (the years before 2014
# set it apart by no-break spaces).
_NUMBERED = re.compile(r"^(\d{1,4})[\s ]{2,}(\S.*)$", re.DOTALL)
_NUMBER = re.compile(r"^(\d{1,4})\.?$")
# The part of the oldest pages that holds the text.
_TEXT_ONLY = "TexteOnly"


def is_case_law(celex: str | None) -> bool:
    """True for a CELEX number of sector 6: a judgment, order or opinion of a court of the
    Union."""
    return bool(celex) and str(celex).startswith("6")


def case_number(celex: str) -> str | None:
    """The case number of a CELEX number of sector 6: ``C-311/18`` of ``62018CJ0311``,
    ``T-441/21`` of ``62021TJ0441``, ``26/63`` of ``61963CJ0026``; None for another."""
    match = _CELEX.match(celex.upper())
    if match is None:
        return None
    year, court, _, number = match.groups()
    case = f"{int(number)}/{year[2:]}"
    return f"{court}-{case}" if int(year) >= _FIRST_LETTERED_YEAR else case


def decision_kind(celex: str) -> JudgmentKind | None:
    """``arrest``, ``beschikking`` or ``conclusie`` by the document letter of a CELEX number
    of sector 6; None for another document."""
    match = _CELEX.match(celex.upper())
    return _KIND_OF_DOCUMENT.get(match[3]) if match else None


def title_parts(title: str | None) -> list[str]:
    """The parts of a title of CELLAR, without their closing full stop."""
    return [
        collapse_ws(part).rstrip(".").strip()
        for part in (title or "").split("#")
        if part.strip()
    ]


def parties(title: str | None) -> str | None:
    """The parties of a title of CELLAR: ``Data Protection Commissioner tegen Facebook Ireland
    Ltd en Maximillian Schrems``; None for a title without them."""
    parts = title_parts(title)
    return parts[1] if len(parts) > 1 else None


def referrals(national: str | None) -> list[Referral]:
    """The decisions that referred the questions (``*A9*``) in the national decisions CELLAR
    names of a case: by the ECLIs a line names, else by its date and the case numbers in
    the brackets that end it ("Uitspraak van 20/03/2020 (ROT 19/1249)")."""
    found = []
    for line in re.findall(r"<p>(.*?)</p>", national or "", re.DOTALL):
        line = html.unescape(collapse_ws(line))
        if not line.startswith(_REFERRING):
            continue
        eclis = tuple(cited_eclis(line))
        day = _NATIONAL_DATE.search(line)
        numbers = _last_brackets(line)
        if eclis:
            found.append(Referral(eclis=eclis))
        elif day and numbers:
            parts = (part.strip() for part in numbers.split(";"))
            found.append(
                Referral(
                    case_numbers=tuple(part for part in parts if part),
                    date=f"{day[3]}-{day[2]}-{day[1]}",
                )
            )
    return found


def _last_brackets(line: str) -> str | None:
    """What the brackets that end *line* hold, brackets inside them too: ``13/752022-20
    (EAB III)`` of "… van 14/09/2021 (13/752022-20 (EAB III))"."""
    line = line.rstrip()
    if not line.endswith(")"):
        return None
    depth = 0
    for at in range(len(line) - 1, -1, -1):
        depth += {")": 1, "(": -1}.get(line[at], 0)
        if depth == 0:
            return line[at + 1 : -1]
    return None


@dataclass(frozen=True)
class CjeuText:
    """The text of a judgment, every paragraph as printed with a blank line between, and its
    paragraphs ``{id, number, kind, text}`` (``core.judgment_paragraphs.ParagraphIds``)."""

    text: str | None
    paragraphs: list[dict[str, Any]]


def read_judgment(html: str) -> CjeuText:
    """The text and the paragraphs of a judgment from the HTML CELLAR serves of it."""
    root = parse_html(html)
    body = next((div for div in root.iter("div") if div.get("id") == _TEXT_ONLY), root)
    printed: list[str] = []
    ids = ParagraphIds()
    for kind, number, text in _blocks(body):
        printed.append(f"{number} {text}" if number else text)
        ids.add(kind, number, text)
    return CjeuText("\n\n".join(printed) or None, ids.entries)


def _blocks(body: ET.Element) -> Iterator[tuple[str, str | None, str]]:
    """``(kind, number, text)`` of every paragraph and table row of *body*, in order; a
    paragraph of links alone (the contents of the oldest pages) left out."""
    for element in _walk(body):
        if element.tag == "tr":
            cells = [collapse_ws("".join(c.itertext())) for c in element]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue
            first = _NUMBER.match(cells[0])
            if first and len(cells) > 1:
                yield ParagraphKind.BODY, first[1], " ".join(cells[1:])
            else:
                yield ParagraphKind.BODY, None, " ".join(cells)
            continue
        raw = "".join(element.itertext()).strip()
        text = collapse_ws(raw)
        if not text or _only_links(element, text):
            continue
        kind = _kind(element)
        numbered = _NUMBERED.match(raw) if kind == ParagraphKind.BODY else None
        if numbered:
            yield kind, numbered[1], collapse_ws(numbered[2])
        else:
            yield kind, None, text


def _walk(element: ET.Element) -> Iterator[ET.Element]:
    """The paragraphs, headings and table rows under *element* in document order; what is
    inside a row is part of the row, and a paragraph that holds paragraphs is passed
    through."""
    for child in element:
        if child.tag == "tr" or (
            child.tag in ("p", *_HEADING_TAGS) and child.find(".//p") is None
        ):
            yield child
        elif child.tag not in ("head", "script", "style"):
            yield from _walk(child)


def _kind(element: ET.Element) -> str:
    style = element.get("class") or ""
    if element.tag in _HEADING_TAGS or _HEADING.search(style):
        return ParagraphKind.HEADING
    if _SUBHEADING.search(style):
        return ParagraphKind.SUBHEADING
    if _SIGNATURE.search(style):
        return ParagraphKind.SIGNATURE
    return ParagraphKind.BODY


def _only_links(element: ET.Element, text: str) -> bool:
    links = collapse_ws(" ".join("".join(a.itertext()) for a in element.iter("a")))
    return bool(links) and links == text
