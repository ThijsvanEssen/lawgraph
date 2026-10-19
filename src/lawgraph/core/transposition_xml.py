"""The transposition tables in the XML of a Kamerstuk: a table of the memorie van toelichting
(or of its bijlage) that places the articles of an old law in a new one.

A ``<table>`` is one when its title, a heading it stands under or the ``<tussenkop>`` right
before it names a transposition or concordance table (``TABLE_WORDS``). Its columns are read
in one of two layouts:

* a head row with a column per law, ``Artikel <law>``: the first is the old law, the second
  the new; the table names the old law in its title (``h. Transponeringstabel Waterwet``),
  else its column does (``Artikel Wabo``). The Omgevingswet's tables (kst-34986-3,
  Bijlage 2) are such::

      Onderwerp | Artikel Wabo | Artikel Omgevingswet | Toelichting

* two columns under the heading ``Huidig naar nieuw``: the current and the new text of one
  law, the old in the first column. The new Wetboek van Strafvordering's second table
  (kst-36636-3) is such; its half ``Nieuw naar huidig`` is not read.

Each cell holds one or more references as the source writes them (``8.2.26, vierde lid``,
``2.1 en 2.2``, ``5.8 t/m 5.14``, ``2.31, eerste lid, onder a``), apart by a comma, ``en``, a
semicolon or a paragraph of their own; in the new law's cell also a division (``afdeling
15.2``, ``bijlage A``), a place that is no article. A cell of the new law that does not read
as such is a place that is no article when it has no figure (``–``, ``niet overgenomen``),
and does not read otherwise (``5.33 jo. 16.15``, ``Komt terug in 13.1``). A row whose old
cell names only a part (``onder a``, ``Tweede lid``) continues the reference above it, and
its new cell, when it names only a part too, the new reference above; a cell over more rows
(``morerows``) holds for each. An old cell that is no reference (``§ 2.3``) is a row of an
article the old law does not have. Nothing is corrected: ``core.succession`` checks every row
against the text of the laws.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from lawgraph.core.qualifiers import ORDINAL, parse_qualifier
from lawgraph.core.succession import Place, SourceRow
from lawgraph.core.xml import collapse_ws, local_name

# The words that name such a table, in a title or a heading.
TABLE_WORDS = (
    "transponeringstabel",
    "transponeringstabellen",
    "concordantietabel",
    "concordantietabellen",
)
_NAMES_A_TABLE = re.compile(
    r"(?:transponerings|concordantie)tabel(?:len)?", re.IGNORECASE
)
# A title "h. Transponeringstabel Waterwet": the law after the words.
_TITLE_LAW = re.compile(
    r"^(?:[a-z]\.\s+)?(?:transponerings|concordantie)tabel(?:len)?\s+(?P<law>.+)$",
    re.IGNORECASE,
)
_COLUMN_LAW = re.compile(r"^artikel(?:en)?\s+(?P<law>.+)$", re.IGNORECASE)
_OLD_TO_NEW = re.compile(r"^huidig\s+naar\s+nieuw\b", re.IGNORECASE)
_NEW_TO_OLD = re.compile(r"^nieuw\s+naar\s+huidig\b", re.IGNORECASE)

# ── a cell ───────────────────────────────────────────────────────────────────

_NUMBER = r"\d+[a-z]*(?:[.:]\d+[a-z]*)*"
_ORDINALS = rf"{ORDINAL}(?:\s*(?:,|\ben\b|\btot en met\b|\bt/m\b)\s*{ORDINAL})*"
_SUB = r"(?:[a-z]{1,2}|\d{1,2}\s*°)(?![\w°])"
_QUALIFIER = (
    rf"(?:{_ORDINALS}\s+(?:lid|leden)\b"
    rf"|{_ORDINALS}\s+(?:vol)?zin(?:nen)?\b"
    rf"|(?:aanhef(?:\s+en)?\s+)?(?:onder(?:deel|delen)?|sub)\s+{_SUB}"
    rf"(?:\s*(?:,|\ben\b|\bt/m\b|\btot en met\b)\s*{_SUB})*"
    r"|aanhef\b)"
)
_QUALIFIERS = rf"(?:\s*,?\s*{_QUALIFIER})*"
_REFERENCE = re.compile(
    rf"(?:artikel(?:en)?\s+)?(?P<number>{_NUMBER})(?P<qualifier>{_QUALIFIERS})",
    re.IGNORECASE,
)
# A cell that names only a part ("onder a", "Tweede lid"): of the reference above it.
_PART_ONLY = re.compile(rf"\s*,?\s*{_QUALIFIER}{_QUALIFIERS}", re.IGNORECASE)
_RUN = re.compile(rf"\s*(?:t/m|tot en met|[–-])\s*(?P<last>{_NUMBER})", re.IGNORECASE)
_SEPARATOR = re.compile(r"\s*[,;]?\s*(?:\ben\b\s*)?", re.IGNORECASE)
# A division of a law, or a list of them: "afdeling 15.2", "afdelingen 16.3, 16.8 en 23.1",
# "§ 2.5.1", "bijlage A bij 1.1", "hoofdstuk 13 en 15": a place that is no article.
_DIVISIONS = re.compile(
    rf"(?:boek|hoofdstuk(?:ken)?|afdeling(?:en)?|§|paragra(?:af|fen)|titel|bijlage)\s*"
    rf"(?:[A-Z]\b|{_NUMBER})?(?:\s+bij\s+{_NUMBER})?"
    rf"(?:\s*(?:,|\ben\b)\s*(?:§\s*)?{_NUMBER}(?![\w.:]))*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Reference:
    """An article or a run of articles with the part the source names, as it writes it; or
    a division (``article`` None)."""

    text: str  # "8.2.26, vierde lid"
    article: str | None  # "8.2.26"
    part: str = ""  # "vierde lid"; empty for the whole article
    leden: tuple[str, ...] = ()
    through: str | None = None  # "5.14" of "5.8 t/m 5.14"


def references(text: str, *, divisions: bool = False) -> list[Reference] | None:
    """The references of a cell, in its order; with *divisions* a division of the law is
    one too. None when the cell does not read as references."""
    text = collapse_ws(text)
    found: list[Reference] = []
    position = 0
    while position < len(text):
        if found:
            separator = _SEPARATOR.match(text, position)
            if separator is None or separator.end() == position:
                return None
            position = separator.end()
        reference = _reference(text, position, divisions)
        if reference is None:
            return None
        found.append(reference[0])
        position = reference[1]
    return found or None


def _reference(
    text: str, position: int, divisions: bool
) -> tuple[Reference, int] | None:
    """The reference at *position* of *text* and where it ends."""
    match = _REFERENCE.match(text, position)
    if match is None:
        division = _DIVISIONS.match(text, position) if divisions else None
        if division is None:
            return None
        return Reference(division[0], None), division.end()
    end = match.end()
    run = _RUN.match(text, end)
    if run is not None:
        end = run.end()
    part = _part(match["qualifier"])
    return (
        Reference(
            text[position:end],
            match["number"],
            part,
            () if run else parse_qualifier(part).leden,
            run["last"] if run else None,
        ),
        end,
    )


def _part(qualifier: str) -> str:
    return qualifier.strip().lstrip(",").strip()


def _continued(base: Reference, text: str) -> Reference:
    """The reference of a cell that names only a part (*text*) under the cell of *base*."""
    part = ", ".join(p for p in (base.part, _part(text)) if p)
    return Reference(
        f"{base.text}, {_part(text)}", base.article, part, parse_qualifier(part).leden
    )


def places(text: str) -> list[Place]:
    """The places a cell of the new law gives: its references (an article, a run of them,
    a division), or the one place that is no article (no figure in it) or does not read."""
    text = collapse_ws(text)
    found = references(text, divisions=True)
    if found is not None:
        return [_place(r) for r in found]
    if not text:
        return []
    return [Place(text, None, (), readable=not re.search(r"\d", text))]


def _place(reference: Reference) -> Place:
    return Place(
        reference.text, reference.article, reference.leden, through=reference.through
    )


# ── a table ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class XmlTable:
    """A transposition table of a Kamerstuk: its name, the laws it names (None: the old law
    is the current text of the new law, the new law the one its dossier enacted), and its rows;
    or why it is not read (``problem``)."""

    name: str
    old_law: str | None
    new_law: str | None
    rows: tuple[SourceRow, ...] = ()
    problem: str | None = None


def read_tables(xml: str, source: str) -> list[XmlTable]:
    """The transposition tables of the Kamerstuk XML *xml* (identifier *source*), in order;
    none for XML that does not read."""
    try:
        root = ET.fromstring(xml.lstrip("﻿"))
    except ET.ParseError:
        return []
    tables: list[XmlTable] = []
    _walk(root, (), tables, source)
    return tables


def _walk(
    element: ET.Element, headings: tuple[str, ...], tables: list[XmlTable], source: str
) -> None:
    """Every table under *element*, with the headings it stands under."""
    own = headings
    before = ""  # the tussenkop right before a table
    for child in element:
        name = local_name(child.tag)
        if name == "kop":
            own = (*headings, _text(child))
        elif name == "tussenkop":
            before = _text(child)
            continue
        elif name == "table":
            table = _table(child, (*own, before), source)
            if table is not None:
                tables.append(table)
        else:
            _walk(child, own, tables, source)
        before = ""


def _table(
    element: ET.Element, headings: tuple[str, ...], source: str
) -> XmlTable | None:
    title = _text(element.find("title"))
    if not any(_NAMES_A_TABLE.search(h) for h in (title, *headings) if h):
        return None
    name = title or " – ".join(h for h in headings if h)
    head = [
        (entry.get("colname") or "", _text(entry))
        for row in element.iter("row")
        if _in_head(element, row)
        for entry in row.findall("entry")
    ]
    columns = [
        (column, match["law"])
        for column, text in head
        if (match := _COLUMN_LAW.match(text))
    ]
    if len(columns) >= 2:
        titled = _TITLE_LAW.match(title)
        old_law = titled["law"] if titled else columns[0][1]
        return XmlTable(
            name,
            old_law,
            columns[1][1],
            _rows(element, columns[0][0], columns[1][0], source),
        )
    direction = headings[-1] if headings else ""
    if _NEW_TO_OLD.match(direction):
        return None
    if _OLD_TO_NEW.match(direction):
        return XmlTable(name, None, None, _rows(element, "col1", "col2", source))
    return XmlTable(name, None, None, problem="no column of an old and of a new law")


def _in_head(table: ET.Element, row: ET.Element) -> bool:
    return any(row in head.findall("row") for head in table.iter("thead"))


def _rows(table: ET.Element, old: str, new: str, source: str) -> tuple[SourceRow, ...]:
    """Each place of each row of the body, under the references of its old column. A cell
    that spans more rows (``morerows``) holds for each; one that spans columns (a heading of
    the table) is no row."""
    reader = _RowReader(source)
    spanning: dict[str, tuple[str, int]] = {}
    for number, row in enumerate(
        (r for body in table.iter("tbody") for r in body.findall("row")), start=1
    ):
        cells = {column: text for column, (text, _) in spanning.items()}
        spanning = {c: (t, n - 1) for c, (t, n) in spanning.items() if n > 1}
        for entry in row.findall("entry"):
            if entry.get("namest") and entry.get("namest") != entry.get("nameend"):
                continue
            column, text = entry.get("colname") or "", _text(entry, " ")
            cells[column] = text
            more = int(entry.get("morerows") or 0)
            if more > 0:
                spanning[column] = (text, more)
        if cells.get(old) and cells.get(new):
            reader.read(cells[old], cells[new], f"rij {number}")
    return tuple(reader.rows)


class _RowReader:
    """The rows of a table in order: a row whose old cell names only a part ("onder a")
    continues the reference above it, in both columns."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.rows: list[SourceRow] = []
        # the last reference of an old and of a new cell of its own
        self._old: Reference | None = None
        self._new: Reference | None = None

    def read(self, old: str, new: str, where: str) -> None:
        olds = self._olds(old)
        continued = olds is not None and self._old is not None and _is_part(old)
        if continued and self._new is not None and _is_part(new):
            news = [_place(_continued(self._new, new))]
        elif _is_part(new):
            news = [Place(collapse_ws(new), None, (), readable=False)]
        else:
            news = places(new)
            if not continued:
                found = references(new)
                self._new = found[-1] if found else None
        if olds is None:
            olds = [Reference(collapse_ws(old), collapse_ws(old))]
        self.rows += [
            SourceRow(o.article or o.text, o.part, n, where, self.source, o.through)
            for o in olds
            for n in news
        ]

    def _olds(self, old: str) -> list[Reference] | None:
        if _is_part(old):
            return [_continued(self._old, old)] if self._old is not None else None
        found = references(old)
        self._old = found[-1] if found else None
        return found


def _is_part(text: str) -> bool:
    return bool(_PART_ONLY.fullmatch(collapse_ws(text)))


def _text(element: ET.Element | None, separator: str = "") -> str:
    """The text of *element*, its paragraphs (``<al>``) apart by *separator*."""
    if element is None:
        return ""
    paragraphs = element.findall("al")
    if paragraphs and separator:
        return collapse_ws(separator.join("".join(p.itertext()) for p in paragraphs))
    return collapse_ws(" ".join(element.itertext()))
