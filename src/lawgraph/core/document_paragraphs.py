"""The alineas of a Kamerstuk: each line of its text with a lasting id, what kind of line it is,
and the number a reader cites it by ("Kamerstukken II 2026/27, 37020, nr. 57, alinea 4").

The text of a Kamerstuk (``core/document_xml.py``) has a line per heading, paragraph, list item
or table row. An alinea is a line of its text, numbered from 1 in document order; not numbered:

- ``head``: the head of the stuk, its title (with a note on it) and, before 2010, its date;
- ``heading``: a heading;
- ``formula``: of a motion (``core/motion_dictum.py``), the formula around what it holds:
  "De Kamer, gehoord de beraadslaging," that opens it, and from "en gaat over tot de orde
  van de dag" on (with the names under it).

A table is one alinea: its lines (``table``: its title and its rows) share a number. Every other
line is ``body``.

The id is ``p-`` and the first 8 hex of the SHA-1 of the line (``text_id``, as a paragraph of
a judgment without a number has), with ``_<n>`` for its n-th occurrence of the same line: it
follows the text, so it stays when a line before it comes or goes. The number is positional.
The source gives no page: the XML of a Kamerstuk has no page breaks.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from lawgraph.core.judgment_paragraphs import text_id
from lawgraph.core.motion_dictum import closing_formula, is_opening


class DocumentLineKind(StrEnum):
    """What a line of a Kamerstuk is (see the module docstring)."""

    HEAD = "head"
    HEADING = "heading"
    FORMULA = "formula"
    TABLE = "table"
    BODY = "body"


@dataclass(frozen=True)
class DocumentLine:
    """A line of the text of a Kamerstuk as its XML makes it."""

    text: str
    heading: bool = False
    head: bool = False  # of the head of the stuk: its title, before 2010 its date
    table: int | None = None  # of the n-th table: its title or a row


def _formula(lines: Sequence[DocumentLine]) -> set[int]:
    """The lines of the formula of a motion: its opening formula, the first lines after the
    head ("De Kamer," "gehoord de beraadslaging,"), and from its closing formula on. A text
    that does not open so has none: a paper that quotes a motion does not end there."""
    opening: set[int] = set()
    for at, line in enumerate(lines):
        if line.head:
            continue
        if not is_opening(line.text):
            break
        opening.add(at)
    if not opening:
        return opening
    closing = closing_formula([line.text for line in lines])
    return opening | set(range(len(lines) if closing is None else closing, len(lines)))


def _kind(line: DocumentLine, formula: bool) -> DocumentLineKind:
    if line.head:
        return DocumentLineKind.HEAD
    if line.heading:
        return DocumentLineKind.HEADING
    if formula:
        return DocumentLineKind.FORMULA
    return DocumentLineKind.BODY if line.table is None else DocumentLineKind.TABLE


def document_paragraphs(lines: Sequence[DocumentLine]) -> list[dict[str, Any]]:
    """Each of *lines* (the text is them joined by a newline) as ``{id, number, kind,
    char_start, char_end}``: its offsets into the text, ``number`` null for a line that is no
    alinea."""
    formula = _formula(lines)
    seen: dict[str, int] = {}
    number = 0
    table: int | None = None  # the table of the last alinea
    start = 0
    paragraphs: list[dict[str, Any]] = []
    for at, line in enumerate(lines):
        kind = _kind(line, at in formula)
        if kind == DocumentLineKind.BODY or (
            kind == DocumentLineKind.TABLE and line.table != table
        ):
            number += 1
        table = line.table if kind == DocumentLineKind.TABLE else None
        base = text_id(line.text)
        seen[base] = seen.get(base, 0) + 1
        paragraphs.append(
            {
                "id": base if seen[base] == 1 else f"{base}_{seen[base]}",
                "number": number
                if kind in (DocumentLineKind.BODY, DocumentLineKind.TABLE)
                else None,
                "kind": kind.value,
                "char_start": start,
                "char_end": start + len(line.text),
            }
        )
        start += len(line.text) + 1
    return paragraphs
