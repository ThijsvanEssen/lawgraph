"""A transposition table: the table the government sends with a recodification (a bijlage of
the memorie van toelichting) that places each article of the old law in the new one.

The layout read is that of blg-1081574 (the new Wetboek van Strafvordering): a PDF in two
halves, "nieuw-huidig" and "huidig-nieuw". Every page of the half read has the heading
``Huidig <old law> Nieuw <new law>``; under it each article of the old law (``Artikel
126ffa``), then a line per part of it with its place in the new law::

    Artikel 126ffa
    1. 2.8.6, 1
    2. 2.8.6, 1
    a. Besluit B2
    4. 2.8.6, 2

A part is a lid (``1.``), an onderdeel (``a.``) or a subonderdeel (``1°.``); a line without one
belongs to the part above it, or to the whole article. A heading of the old law (``Titel VE.
Verkennend onderzoek``, over one or more lines) ends an article. The other half, and a
document without such a heading, is no table: ``read_table`` gives None.

A place (``places``) is one of the ``;``-separated items of a line: an article of the new law
with the leden it names (``2.8.6, 1``; ``algemene regeling 2.1.10``, the general rule that
covers it), a place that is no article as the source writes it (``vervallen``, ``Besluit B2``,
``bepaling over gegevensverwerking``), or an item that is not readable (``1,5,2, 6``). Nothing
is corrected: what does not read is marked, and the check against the text of the new law
(``core.succession``) decides what holds.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from pypdf import PdfReader

from lawgraph.core.succession import Place, SourceRow
from lawgraph.core.xml import collapse_ws

# The heading of every page of the half "huidig-nieuw": the old law, then the new one.
_HEADING = re.compile(r"^Huidig (?P<old>.+?) Nieuw (?P<new>.+?)\s*$")
# The heading of a page of the other half.
_OTHER_HALF = re.compile(r"^Nieuw .+ Huidig .+$")
_PAGE_NUMBER = re.compile(r"^Pagina \d+\s*$")
_ARTICLE = re.compile(r"^Artikel\s+(\S+)\s*$")
# A division of the old law: "Titel VE. ...", "Eerste Boek. ...", "Tweede afdeeling ...".
_DIVISION = re.compile(
    r"^(?:[A-Z][a-z]+(?:de|ste)\s+(?:Boek|Titel|[Aa]fdee?ling|Hoofdstuk)"
    r"|(?:Titel|TITEL|Boek|Afdee?ling|Hoofdstuk)\s+[IVXLC]+[A-Za-z]*\b)"
)
_LID = re.compile(r"^(\d+[a-z]?)\.\s+(.+)$")
_ONDERDEEL = re.compile(r"^([a-z]{1,2})\.\s+(.+)$")
_SUB = re.compile(r"^(\d+)\s*[°⁰º]\.?\s+(.+)$")

# An article of the new law, the general rule that covers it before it: "2.8.6, 1",
# "algemene regeling (1.4.8)".
_PLACE = re.compile(
    r"^(?P<general>algemene regeling\s+)?\(?(?P<article>\d+\.\d+\.\d+[a-z]*)\)?"
    r"(?:\s*,\s*(?P<rest>.*?))?\s*$"
)
# What may follow the article: leden, onderdelen, subonderdelen and a sentence.
_LID_TOKEN = re.compile(r"\d+")
_OTHER_TOKEN = re.compile(r"[a-z]{1,2}|\d+\s*[°⁰º]|\d+e zin")
_TOKENS = re.compile(r"\s*,\s*|\s*\ben\b\s*")
# Something that reads as a number of the new law: one that is no article is not read.
_LOOKS_LIKE_A_NUMBER = re.compile(r"\d+\s*[.,]\s*\d+\s*[.,]\s*\d+")


@dataclass(frozen=True)
class Placement:
    """A line of the table: a part of the old article (``2 a``; empty: the whole) and its
    place in the new law as the source writes it."""

    part: str
    text: str


@dataclass
class OldArticle:
    """An article of the old law with its lines, and the page of the PDF it starts on."""

    number: str
    page: int
    placements: list[Placement] = field(default_factory=list)


@dataclass(frozen=True)
class Table:
    """The half "huidig-nieuw" of a table: the names of the two laws and the articles."""

    old_law: str
    new_law: str
    articles: tuple[OldArticle, ...]


def pdf_pages(data: bytes) -> list[str]:
    """The text of each page of the PDF *data*, as its text layer gives it."""
    return [page.extract_text() for page in PdfReader(io.BytesIO(data)).pages]


def read_table(pages: list[str]) -> Table | None:
    """The half "huidig-nieuw" of the table on *pages*; None when no page has its heading."""
    laws: tuple[str, str] | None = None
    body: list[tuple[str, int]] = []
    for number, text in enumerate(pages, start=1):
        lines = text.splitlines()
        heading = next(
            (i for i, line in enumerate(lines) if _HEADING.match(line)), None
        )
        if heading is None:
            continue
        match = _HEADING.match(lines[heading])
        assert match is not None
        laws = laws or (match["old"].strip(), match["new"].strip())
        body += [
            (line, number)
            for line in lines[heading + 1 :]
            if line.strip() and not _PAGE_NUMBER.match(line.strip())
        ]
    if laws is None:
        return None
    reader = _Reader()
    for line, number in _joined(body):
        reader.read(line, number)
    return Table(laws[0], laws[1], tuple(reader.articles))


def _joined(body: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """*body* with each line that runs on joined to the next: one that ends in a space
    (the text layer keeps it), before a line that is no article, division or labelled part
    ("…; algemene regeling " + "2.1.9; Besluit B2"). A space is collapsed."""
    joined: list[tuple[str, int]] = []
    runs_on = False
    for line, number in body:
        text = collapse_ws(line)
        if runs_on and joined and not _starts_anew(text):
            joined[-1] = (f"{joined[-1][0]} {text}", joined[-1][1])
        else:
            joined.append((text, number))
        runs_on = line != line.rstrip()
    return joined


def _starts_anew(line: str) -> bool:
    return bool(
        _ARTICLE.match(line)
        or _DIVISION.match(line)
        or _OTHER_HALF.match(line)
        or any(p.match(line) for p in (_SUB, _LID, _ONDERDEEL))
    )


class _Reader:
    """The lines of the half: an article and its part go on over a page."""

    def __init__(self) -> None:
        self.articles: list[OldArticle] = []
        self._article: OldArticle | None = None
        # the lid, onderdeel and subonderdeel of the line read last
        self._part: list[str | None] = [None, None, None]

    def read(self, line: str, page: int) -> None:
        if _OTHER_HALF.match(line):
            return
        if match := _ARTICLE.match(line):
            self._article = OldArticle(match[1], page)
            self.articles.append(self._article)
            self._part = [None, None, None]
        elif _DIVISION.match(line):
            self._article = None  # its lines up to the next article are its heading
        elif self._article is not None:
            text = self._labelled(line)
            part = " ".join(p for p in self._part if p)
            self._article.placements.append(Placement(part, text))

    def _labelled(self, line: str) -> str:
        """The place of *line*; its label (if any) is the part it is of."""
        for level, pattern, label in (
            (2, _SUB, "{}°"),
            (0, _LID, "{}"),
            (1, _ONDERDEEL, "{}"),
        ):
            if match := pattern.match(line):
                self._part = [*self._part[:level], label.format(match[1])]
                self._part += [None] * (3 - len(self._part))
                return match[2].strip()
        return line


def places(text: str) -> list[Place]:
    """The places of one line of the table, in its order."""
    return [_place(item.strip()) for item in text.split(";") if item.strip()]


def _place(item: str) -> Place:
    match = _PLACE.match(item)
    if match:
        rest = match["rest"] or ""
        tokens = [t for t in _TOKENS.split(rest) if t]
        if all(_LID_TOKEN.fullmatch(t) or _OTHER_TOKEN.fullmatch(t) for t in tokens):
            return Place(
                item,
                match["article"],
                tuple(t for t in tokens if _LID_TOKEN.fullmatch(t)),
                general=bool(match["general"]),
            )
    elif not _LOOKS_LIKE_A_NUMBER.search(item) and re.search(r"[A-Za-z]", item):
        return Place(item, None, ())
    return Place(item, None, (), readable=False)


def source_rows(table: Table) -> list[SourceRow]:
    """Each place of each line of *table*, with the page it is on."""
    return [
        SourceRow(article.number, placement.part, one, f"p. {article.page}")
        for article in table.articles
        for placement in article.placements
        for one in places(placement.text)
    ]
