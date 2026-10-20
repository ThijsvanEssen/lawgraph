"""Tables in a text, pure: a CALS ``<table>`` read into rows of cells, and the table as a span
of the text it is laid out in.

A table stands in a text one row a line, its cells separated by a tab (an empty cell an
empty string). ``TextTable`` says where it is and what the lines are: how many of them are its
header, how many columns it has and which cells span more than one column or row. The text
of an article (``core.bwb_xml``), of a Kamerstuk (``core.document_xml``) and of a paragraph of
a judgment (``core.judgment_paragraphs``) keep their tables so, and store them as
``props.tables`` (``TextTable.to_dict``).

The BWB, the Kamerstukken of officielebekendmakingen.nl and the judgments of the Rechtspraak
all write a table in CALS: ``<table>`` (``<informaltable>`` in a judgment) with a ``<title>``
and one or more ``<tgroup>``, each with its ``<colspec>``, a ``<thead>``, ``<tbody>`` and
``<tfoot>`` of ``<row>`` of ``<entry>``; ``namest``/``nameend`` and ``morerows`` make a cell
span columns and rows.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from lawgraph.core.xml import child_named, children_named, local_name, words_of


@dataclass(frozen=True)
class CellSpan:
    """A cell of a table that spans more than one column or row (CALS ``namest``/``nameend``,
    ``morerows``): the *cell*-th cell of row *row*, counted from 0."""

    row: int
    cell: int
    cols: int
    rows: int

    def to_dict(self) -> dict[str, int]:
        return {
            "row": self.row,
            "cell": self.cell,
            "cols": self.cols,
            "rows": self.rows,
        }


@dataclass(frozen=True)
class TextTable:
    """A table as a span of a text: one line per row, its cells separated by a tab, an empty
    cell an empty string. A cell spanning more columns or rows is one cell (``spans``); a row
    next to a cell that spans rows has fewer cells.

    ``head_rows`` are the rows of its ``<thead>``, the first of the span; ``columns`` how many
    columns it has (``tgroup@cols``, or its widest row)."""

    start: int
    end: int
    head_rows: int
    columns: int
    spans: tuple[CellSpan, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """JSON-able form stored in ``props.tables``; ``spans`` only where there are any."""
        out: dict[str, Any] = {
            "start": self.start,
            "end": self.end,
            "head_rows": self.head_rows,
            "columns": self.columns,
        }
        if self.spans:
            out["spans"] = [span.to_dict() for span in self.spans]
        return out


def table_heads(
    text: str, tables: Iterable[Mapping[str, Any]]
) -> list[tuple[int, int]]:
    """``(start, end)`` in *text* of the header of each table of *tables* (``props.tables``)
    that has one: its first ``head_rows`` lines. A header names columns; it is no use of a
    term the regulation defines."""
    heads = []
    for table in tables:
        start, end, rows = table.get("start"), table.get("end"), table.get("head_rows")
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and isinstance(rows, int)
            and rows > 0
        ):
            head = "\n".join(text[start:end].split("\n")[:rows])
            heads.append((start, start + len(head)))
    return heads


# ── CALS ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CalsCell:
    """An ``<entry>`` and how many columns and rows it covers."""

    entry: ET.Element
    cols: int = 1
    rows: int = 1


@dataclass(frozen=True)
class CalsRow:
    """A ``<row>``: whether it is of the header (``<thead>``), and its cells."""

    head: bool
    cells: tuple[CalsCell, ...]


@dataclass(frozen=True)
class CalsTable:
    """A CALS table as read: its ``<title>``, its rows in document order and how many
    columns it has."""

    title: ET.Element | None
    rows: tuple[CalsRow, ...]
    columns: int

    def text_table(self, start: int, end: int) -> TextTable:
        """The table laid out from *start* to *end* of a text, a row a line."""
        return TextTable(
            start=start,
            end=end,
            head_rows=sum(1 for row in self.rows if row.head),
            columns=self.columns,
            spans=tuple(
                CellSpan(index, place, cell.cols, cell.rows)
                for index, row in enumerate(self.rows)
                for place, cell in enumerate(row.cells)
                if cell.cols > 1 or cell.rows > 1
            ),
        )


# The parts of a ``tgroup`` that hold rows.
_SECTIONS = ("thead", "tbody", "tfoot")


def _column_numbers(tgroup: ET.Element) -> dict[str, int]:
    """The number of each named column of a ``tgroup`` (``colspec@colname`` → ``colnum``,
    else its place)."""
    numbers: dict[str, int] = {}
    for position, colspec in enumerate(children_named(tgroup, "colspec"), start=1):
        name = colspec.get("colname")
        number = colspec.get("colnum") or ""
        if name:
            numbers[name] = int(number) if number.isdigit() else position
    return numbers


def _cell(entry: ET.Element, columns: Mapping[str, int]) -> CalsCell:
    """An ``entry`` and how many columns and rows it covers."""
    first, last = (
        columns.get(entry.get("namest") or ""),
        columns.get(entry.get("nameend") or ""),
    )
    cols = last - first + 1 if first and last and last > first else 1
    more = entry.get("morerows") or ""
    return CalsCell(entry, cols, 1 + (int(more) if more.isdigit() else 0))


def read_cals(table: ET.Element) -> CalsTable | None:
    """The rows of a CALS ``<table>`` (or ``<informaltable>``); None for one without rows."""
    tgroups = children_named(table, "tgroup")
    rows: list[CalsRow] = []
    for tgroup in tgroups:
        columns = _column_numbers(tgroup)
        for section in tgroup:
            if local_name(section.tag) not in _SECTIONS:
                continue
            head = local_name(section.tag) == "thead"
            for row in children_named(section, "row"):
                cells = tuple(_cell(e, columns) for e in children_named(row, "entry"))
                rows.append(CalsRow(head, cells))
    if not rows:
        return None
    declared = [int(n) for g in tgroups if (n := g.get("cols") or "").isdigit()]
    widest = max(len(row.cells) for row in rows)
    title = child_named(table, "title")
    return CalsTable(
        title if title is not None and words_of(title) else None,
        tuple(rows),
        max([widest, *declared]),
    )


def lay_out[C](
    table: ET.Element,
    read: Callable[[ET.Element], C],
    filled: Callable[[C], bool] = bool,
) -> tuple[CalsTable, list[list[C]]] | None:
    """A CALS table and what *read* makes of each of its cells, per row; without the rows
    none of whose cells is *filled* (a line of nothing, which a court sets under a
    signature; a row all of whose columns cells above it span), a cell spanning rows over
    them spanning the rows left. None for a table without a row left."""
    cals = read_cals(table)
    if cals is None:
        return None
    texts = [[read(cell.entry) for cell in row.cells] for row in cals.rows]
    kept = [
        index
        for index, (row, cells) in enumerate(zip(cals.rows, texts, strict=True))
        if any(filled(cell) for cell in cells) or any(c.rows > 1 for c in row.cells)
    ]
    if not kept:
        return None
    left = set(kept)
    rows = tuple(
        CalsRow(
            cals.rows[index].head,
            tuple(
                replace(cell, rows=len(left & set(range(index, index + cell.rows))))
                for cell in cals.rows[index].cells
            ),
        )
        for index in kept
    )
    return CalsTable(cals.title, rows, cals.columns), [texts[index] for index in kept]
