"""The text of an article as blocks to read it by: one per lid, onderdeel or aanhef, with its
anchor — pure, no I/O.

The text of an article is a paragraph a line; its parts (``core.bwb_xml.ArticlePart``) are
spans of it, a lid with onderdelen spanning them too, and the printed numbers ("2.", "a.")
stand between them. A line belongs to the innermost part it overlaps; consecutive lines of
one part are one block. The anchor of a block is the id of that part (``lid-2-onder-a``),
the anchor the explorer gives the place. An anchor repeats where its part goes on after a
part inside it (a line after a list), and a block outside every part has none.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

# The kind of a block outside every part, and of a heading on a line of its own.
OUTSIDE = "tekst"
HEADING = "kop"


class Span(Protocol):
    """A span of the text of an article: a heading."""

    @property
    def start(self) -> int: ...

    @property
    def end(self) -> int: ...


class PartSpan(Span, Protocol):
    """A part of an article as a span of its text."""

    @property
    def id(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def number(self) -> str | None: ...


@dataclass(frozen=True)
class Block:
    """A block of the text: ``text[start:end]``, its printed number (``marker``) before it.

    ``within`` are the anchors of the parts it stands in, the outermost first (``lid-2`` of
    ``lid-2-onder-a``), so a citation of lid 2 marks its onderdelen too."""

    anchor: str | None
    kind: str
    number: str | None
    marker: str | None
    within: tuple[str, ...]
    start: int
    end: int
    # whether the part of the block starts in it (a block that goes on does not)
    opens: bool = True


def _lines(text: str) -> Iterator[tuple[int, int]]:
    """The ``(start, end)`` of each line of *text* that holds more than space."""
    start = 0
    for line in text.split("\n"):
        end = start + len(line)
        if line.strip():
            yield start, end
        start = end + 1


def _innermost(parts: Sequence[PartSpan], start: int, end: int) -> PartSpan | None:
    """The smallest part that overlaps ``text[start:end]``; of two as large the deeper."""
    overlapping = [p for p in parts if p.start < end and p.end > start]
    if not overlapping:
        return None
    return min(overlapping, key=lambda p: (p.end - p.start, -len(p.id)))


def _within(parts: Sequence[PartSpan], part: PartSpan) -> tuple[str, ...]:
    """The anchors of the parts that hold *part*, the outermost first."""
    holding = [
        p
        for p in parts
        if p.id != part.id and p.start <= part.start and p.end >= part.end
    ]
    holding.sort(key=lambda p: (p.start - p.end, len(p.id)))
    return tuple(p.id for p in holding)


def _block(
    text: str, parts: Sequence[PartSpan], start: int, end: int, heading: bool
) -> Block:
    """The block of the line ``text[start:end]``."""
    part = _innermost(parts, start, end)
    within = () if part is None else _within(parts, part)
    if heading:
        inside = within + ((part.id,) if part else ())
        return Block(None, HEADING, None, None, inside, start, end)
    if part is None:
        return Block(None, OUTSIDE, None, None, (), start, end, opens=False)
    if not start <= part.start < end:
        return Block(part.id, part.kind, part.number, None, within, start, end, False)
    marker = text[start : part.start].strip() or None
    return Block(part.id, part.kind, part.number, marker, within, part.start, end)


def _goes_on(last: Block, block: Block) -> bool:
    """Whether *block* is the next line of the block *last*."""
    return (
        not block.opens
        and block.kind != HEADING
        and last.kind != HEADING
        and (last.anchor, last.kind) == (block.anchor, block.kind)
    )


def article_blocks(
    text: str, parts: Sequence[PartSpan], headings: Sequence[Span] = ()
) -> list[Block]:
    """The blocks of the article text *text*, in text order, by its *parts* and the
    *headings* on a line of their own."""
    heads = {(h.start, h.end) for h in headings}
    blocks: list[Block] = []
    for start, end in _lines(text):
        content = text[start:end]
        lead = len(content) - len(content.lstrip())
        heading = (start + lead, start + len(content.rstrip())) in heads
        block = _block(text, parts, start, end, heading)
        if blocks and _goes_on(blocks[-1], block):
            blocks[-1] = replace(blocks[-1], end=end)
            continue
        blocks.append(block)
    return blocks
