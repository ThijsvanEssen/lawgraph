"""The concordance table of an EU act that codifies or recasts others (a bijlage headed
"Concordantietabel"), read from the act's CELLAR HTML as ``retrieve eurlex`` stores it — pure,
no I/O.

The table follows the paragraph whose whole text is its heading ("Concordantietabel",
"CONCORDANTIETABEL") and runs to the next bijlage. Its head row has a column per act: the old
acts by their name ("Verordening (EG) nr. 207/2009", "Richtlijn 82/891/EEG", read as
``eu_citations.named_acts`` reads them), the new act as "Deze richtlijn", "De onderhavige
verordening". A codification of several acts has a column for each (``ConcordanceTable`` per
column); a column whose head names no act ("Toetredingsakte van 2012") places nothing. A head
cell that spans columns names each of them, and the cells of those columns are read as one.
A row is a ``<tr>``; a cell with a paragraph per line (Richtlijn 2006/116/EG) is a row per
line. A row that does not line up places each line of an old act in a place that does not
read: its cells have not as many lines (13 against 14), or it has fewer cells than the head
has columns (a row of 2 cells under 7, Richtlijn (EU) 2017/1132).

A cell holds references as the Official Journal writes them: ``Artikel 9``, ``Artikel 9 bis``,
``Artikelen 1 tot en met 7`` (a run), ``Artikelen 3 en 4``, ``Artikel 8, leden 1 tot en met 4``,
``Artikel 2, punt 8 bis``, ``Artikel 16, leden 1 en 2, en artikel 17, leden 2 en 3``; a
bijlage (``Bijlage I``) and ``—`` (no counterpart) are no article. Of the old act a reference
is an article and its part as written ("leden 1 tot en met 4"); a cell of the old act that
names no article gives no row. Of the new act it is a ``Place``: the article with the leden
it names, a place that is no article (``—``, a bijlage), or one that does not read.

The act also says which acts it repeals ("Verordening (EG) nr. 207/2009 wordt ingetrokken."):
an old act it repeals goes, so an article of it without a row is a gap (``core.succession``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from itertools import zip_longest

from lawgraph.core.eu_citations import named_acts
from lawgraph.core.eurlex_html import parse_html
from lawgraph.core.succession import Place, SourceRow
from lawgraph.core.xml import collapse_ws

# The heading of the table: the whole text of its paragraph.
_HEADING = re.compile(r"concordantietabel(?:len)?", re.IGNORECASE)
# The title of a bijlage, where the table ends.
_ANNEX_TITLE_CLASSES = frozenset({"oj-doc-ti", "doc-ti"})
# The head cell of the new act.
_THIS_ACT = re.compile(r"(?:de\s+)?(?:deze|dit|onderhavige)\b", re.IGNORECASE)
# An article of the act (``div id="art_125"``), and the words of one that repeals others.
_ARTICLE_ID = "art_"
_REPEALS = re.compile(
    r"\b(?:wordt|worden)\b[^.;]{0,160}?\bingetrokken\b", re.IGNORECASE
)
_NONE = frozenset({"", "—", "–", "-", "_", "__"})

# An article number as the Official Journal writes it: "9", "42a", "9 bis", "74 duodecies".
_LATIN = r"(?:bis|ter|quater|[a-z]*ies)"
_NUMBER = rf"\d+[a-z]?(?:\s+{_LATIN})?"
_ARTICLE = re.compile(rf"artikel\s+(?P<number>{_NUMBER})\b\s*,?\s*(?P<part>.*)", re.I)
_RUN = re.compile(
    rf"artikelen\s+(?P<first>{_NUMBER})\s+tot\s+en\s+met\s+(?P<last>{_NUMBER})", re.I
)
_ARTICLES = re.compile(
    rf"artikelen\s+(?P<numbers>{_NUMBER}(?:\s*(?:,|\ben\b)\s*{_NUMBER})+)", re.I
)
_PART_OF_ARTICLE = re.compile(r"(?:lid|leden)\b", re.IGNORECASE)
_ANNEX = re.compile(r"bijlagen?\b", re.IGNORECASE)
# Where a cell names a second reference: ", en artikel 17", ", artikel 11", " en lid 3",
# " en bijlage V".
_NEXT = re.compile(
    r"\s*,?\s*(?:\ben\s+)?(?=\b(?:artikel|artikelen|bijlage|bijlagen)\b)"
    r"|,?\s+en\s+(?=(?:lid|leden)\b)",
    re.IGNORECASE,
)
# The leden a part names: "lid 6", "leden 1 tot en met 4", "leden 1, 2 en 3", "lid 4 bis".
_LEDEN = re.compile(
    rf"(?:lid|leden)\s+(?P<leden>{_NUMBER}(?:\s*(?:,|\ben\b|\btot\s+en\s+met\b)\s*"
    rf"{_NUMBER})*)",
    re.IGNORECASE,
)
# The items of a list: "1, 2 en 3"; "1 tot en met 4" is one.
_LIST = re.compile(r"\s*,\s*|\s+en\s+(?!met\b)")
_LID_RUN = re.compile(rf"({_NUMBER})\s+tot\s+en\s+met\s+({_NUMBER})", re.IGNORECASE)


@dataclass(frozen=True)
class ConcordanceTable:
    """The rows of one old act in a concordance table, or why it places nothing."""

    name: str  # "BIJLAGE III Concordantietabel, Verordening (EG) nr. 207/2009"
    old_act: str | None = None  # its CELEX number: 32009R0207
    repealed: bool = False  # the new act says it repeals the old one
    rows: tuple[SourceRow, ...] = ()
    problem: str | None = None


@dataclass(frozen=True)
class _Reference:
    """One reference of a cell: an article (or the first of a run) and the rest as
    written, or a place that is no article (*article* None)."""

    text: str
    article: str | None
    part: str = ""
    through: str | None = None
    readable: bool = True


@dataclass
class _Column:
    head: str
    act: str | None
    rows: list[SourceRow] = field(default_factory=list)


def read_tables(html: str, source: str) -> list[ConcordanceTable]:
    """The concordance tables of the act's HTML *html* (CELEX *source*), a table per old
    act, in the order of the head; none for an act without one."""
    root = parse_html(html)
    repealed = _repealed(root)
    found: list[ConcordanceTable] = []
    for name, tables in _headed_tables(root):
        if not tables:
            found.append(ConcordanceTable(name, problem="no table in the HTML"))
        for table in tables:
            found += _read(table, name, source, repealed)
    return found


def _repealed(root: ET.Element) -> set[str]:
    """The acts an article of the act says it repeals: named before "wordt/worden …
    ingetrokken" (a recital that says an act should be repealed does not count)."""
    acts: set[str] = set()
    for article in root.iter("div"):
        if not (article.get("id") or "").startswith(_ARTICLE_ID):
            continue
        for paragraph in article.iter("p"):
            text = _text(paragraph)
            if match := _REPEALS.search(text):
                acts.update(named_acts(text[: match.start()]))
    return acts


def _headed_tables(root: ET.Element) -> list[tuple[str, list[ET.Element]]]:
    """Per heading of a concordance table its name (with the title of its bijlage) and the
    tables after it up to the next bijlage, in document order; a table inside a table is
    part of its cell."""
    nested = {
        id(inner)
        for table in root.iter("table")
        for inner in table.iter("table")
        if inner is not table
    }
    found: list[tuple[str, list[ET.Element]]] = []
    annex = ""
    open_: list[ET.Element] | None = None
    for element in root.iter():
        if element.tag == "p":
            text = _text(element)
            if _HEADING.fullmatch(text):
                open_ = []
                found.append((f"{annex} {text}".strip(), open_))
            elif _ANNEX_TITLE_CLASSES & set((element.get("class") or "").split()):
                annex, open_ = text, None
        elif element.tag == "table" and open_ is not None and id(element) not in nested:
            open_.append(element)
    return found


def _read(
    table: ET.Element, name: str, source: str, repealed: set[str]
) -> list[ConcordanceTable]:
    grid = _grid(table)
    head_index = next(
        (i for i, row in enumerate(grid) if any(map(_is_this_act, _heads(row)))), None
    )
    if head_index is None:
        return [ConcordanceTable(name, problem="no column of this act")]
    head = _heads(grid[head_index])
    # a head cell that spans columns is one column, at the first of them
    firsts = [i for i, cell in enumerate(head) if i == 0 or head[i - 1] != cell]
    news = [i for i in firsts if _is_this_act(head[i])]
    columns = {i: _Column(head[i], _one(named_acts(head[i]))) for i in firsts}
    if len(news) != 1 or not any(c.act for c in columns.values()):
        return [ConcordanceTable(name, problem="no column of an old act")]
    new = news[0]
    for number, row in enumerate(grid[head_index + 1 :], start=1):
        cells = _merged(row, head)
        lines = [_lines(cells.get(i, [])) for i in firsts]
        aligned, unread = _aligned(
            lines, firsts.index(new), sum(span for _, span in row), len(head)
        )
        for line_number, line in enumerate(aligned, start=1):
            where = f"rij {number}" + (
                f", regel {line_number}" if len(aligned) > 1 else ""
            )
            cell = dict(zip(firsts, line, strict=True))
            places = [unread] if unread else [_place(r) for r in _references(cell[new])]
            for i, column in columns.items():
                if i != new and column.act:
                    column.rows += [
                        SourceRow(
                            old.article, old.part, place, where, source, old.through
                        )
                        for old in _references(cell[i])
                        if old.article is not None
                        for place in places
                    ]
    return [
        ConcordanceTable(
            f"{name}, {column.head}",
            column.act,
            column.act in repealed,
            tuple(column.rows),
        )
        for i, column in columns.items()
        if i != new and column.act
    ]


def _one(acts: list[str]) -> str | None:
    return acts[0] if len(acts) == 1 else None


def _grid(table: ET.Element) -> list[list[tuple[ET.Element, int]]]:
    """The rows of *table* (not of a table inside it), each cell with its colspan."""
    rows: list[list[tuple[ET.Element, int]]] = []
    stack = [table]
    while stack:
        element = stack.pop(0)
        for child in element:
            if child.tag == "tr":
                rows.append(
                    [
                        (cell, max(1, int(cell.get("colspan") or 1)))
                        for cell in child
                        if cell.tag in ("td", "th")
                    ]
                )
            elif child.tag in ("thead", "tbody", "tfoot"):
                stack.append(child)
    return rows


def _heads(row: list[tuple[ET.Element, int]]) -> list[str]:
    """The text of the head cell over each column."""
    return [_text(cell) for cell, span in row for _ in range(span)]


def _merged(
    row: list[tuple[ET.Element, int]], head: list[str]
) -> dict[int, list[ET.Element]]:
    """The cells of *row* by the column of the head they stand under; the columns of one
    head cell (which spans them) as one."""
    by_column: dict[int, list[ET.Element]] = {}
    column = 0
    for cell, span in row:
        first = column
        while first > 0 and first < len(head) and head[first - 1] == head[first]:
            first -= 1
        by_column.setdefault(first, []).append(cell)
        column += span
    return by_column


def _lines(cells: list[ET.Element]) -> list[str]:
    """The lines of the cells (a paragraph each), the cells of one column side by side."""
    per_cell = [[_text(p) for p in cell.iter("p")] or [_text(cell)] for cell in cells]
    if not per_cell:
        return []
    if len(per_cell) == 1:
        return per_cell[0]
    return [
        ", ".join(part for part in parts if part not in _NONE)
        for parts in zip_longest(*per_cell, fillvalue="")
    ]


def _aligned(
    lines: list[list[str]], new: int, width: int, columns: int
) -> tuple[list[list[str]], Place | None]:
    """The rows of a row whose cells may hold a line each, line by line, and the place of
    the new act when the row does not line up: it has another number of cells than the head
    has columns, or its cells with text have not as many lines."""
    counts = {len(cell) for cell in lines if any(cell)}
    rows = [
        [cell[i] if i < len(cell) else "" for cell in lines]
        for i in range(max(counts, default=0))
    ]
    if width != columns:
        text = f"a row of {width} cells under {columns} columns"
    elif len(counts) > 1:
        old = max(len(c) for i, c in enumerate(lines) if i != new and any(c))
        text = f"{len(lines[new])} lines of this act against {old}"
    else:
        return rows, None
    return rows, Place(text, None, (), readable=False)


def _references(cell: str) -> list[_Reference]:
    """The references of a cell, in order: a part that continues the article before it
    ("en lid 3") is of that article."""
    text = collapse_ws(cell)
    if text in _NONE:
        return [_Reference(text, None)]
    found: list[_Reference] = []
    for piece in (p.strip(" ,;") for p in _NEXT.split(text)):
        if not piece:
            continue
        if _PART_OF_ARTICLE.match(piece) and found and found[-1].article:
            found.append(_Reference(piece, found[-1].article, piece))
        else:
            found += _read_piece(piece)
    return found


def _read_piece(piece: str) -> list[_Reference]:
    if match := _RUN.fullmatch(piece):
        return [_Reference(piece, _number(match["first"]), "", _number(match["last"]))]
    if match := _ARTICLES.fullmatch(piece):
        numbers = _LIST.split(match["numbers"])
        return [_Reference(piece, _number(n)) for n in numbers if n]
    if match := _ARTICLE.fullmatch(piece):
        return [_Reference(piece, _number(match["number"]), match["part"].strip())]
    if _ANNEX.match(piece):
        return [_Reference(piece, None)]
    return [_Reference(piece, None, readable=False)]


def _number(text: str) -> str:
    return collapse_ws(text)


def _place(reference: _Reference) -> Place:
    """The place of a reference of the new act, with the leden its part names."""
    if reference.article is None:
        return Place(reference.text, None, (), readable=reference.readable)
    return Place(
        reference.text,
        reference.article,
        _leden(reference.part),
        through=reference.through,
    )


def _leden(part: str) -> tuple[str, ...]:
    """The leden a part names: "leden 1 tot en met 4" is 1, 2, 3 and 4."""
    match = _LEDEN.match(part)
    if not match:
        return ()
    leden: list[str] = []
    for item in _LIST.split(match["leden"]):
        run = _LID_RUN.fullmatch(item)
        if run and run[1].isdigit() and run[2].isdigit():
            leden += [str(n) for n in range(int(run[1]), int(run[2]) + 1)]
        elif item:
            leden.append(collapse_ws(item))
    return tuple(leden)


def _is_this_act(cell: str) -> bool:
    return bool(_THIS_ACT.match(cell)) and not named_acts(cell)


def _text(element: ET.Element) -> str:
    return collapse_ws("".join(element.itertext()))
