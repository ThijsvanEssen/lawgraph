"""The words of a Kamerstuk as ``semantic tk`` reads them, and where a citation stands — pure.

The linker reads a paper as one text: its title, its text (``normalize tk-content``) and its
footnotes, which ``text`` does not hold, one per line. :class:`PaperText` keeps where each of
those parts lies in what is read, so a citation found there is placed back in what
``/api/documents/{key}`` serves: in ``title``, in ``text`` (with the section it stands in) or in
one of ``footnotes`` (by its ``id``), with the offsets of the citation in that part.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lawgraph.core.citations import coerce_text, make_snippet

PLACE_TITLE = "title"
PLACE_TEXT = "text"
PLACE_FOOTNOTE = "footnote"


def footnote_id(index: int) -> str:
    """The id of the footnote at *index* of ``props.footnotes``: ``fn-1`` for the first. A
    label repeats in a paper (a legacy paper numbers its footnotes per page)."""
    return f"fn-{index + 1}"


def section_at(sections: Iterable[Any], offset: int) -> str | None:
    """The id of the innermost of *sections* (``props.sections``, in document order, a child
    inside its parent) whose span holds *offset* of ``text``: the last that does."""
    inner = None
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        begin, finish = section.get("char_start"), section.get("char_end")
        if (
            isinstance(begin, int)
            and isinstance(finish, int)
            and begin <= offset < finish
        ):
            inner = section.get("id")
    return str(inner) if inner else None


@dataclass(frozen=True)
class _Part:
    """One part of what is read: ``read[start:start + len(text)]`` is *text*, which stands
    in what is served from *lead* on."""

    place: str  # PLACE_*
    start: int
    text: str
    lead: int = 0  # characters of the served value before *text* (stripped whitespace)
    index: int | None = None  # of a footnote: its place in ``props.footnotes``
    label: str | None = None  # of a footnote: its number as printed


@dataclass(frozen=True)
class PaperText:
    """What the linker reads of a paper, and where each part of it is served."""

    text: str
    parts: tuple[_Part, ...]
    sections: tuple[Mapping[str, Any], ...] = ()

    @classmethod
    def of(cls, props: Mapping[str, Any]) -> PaperText:
        """The title, the text and the footnotes of *props*, one per line; a part without
        words is left out."""
        builder = _Builder()
        for place in (PLACE_TITLE, PLACE_TEXT):
            value = props.get(place)
            builder.add(place, str(value) if value is not None else "")
        builder.add_footnotes(props.get("footnotes") or [])
        sections = props.get("sections") or []
        return cls(
            text="\n".join(builder.fragments),
            parts=tuple(builder.parts),
            sections=tuple(s for s in sections if isinstance(s, Mapping)),
        )

    def place(
        self, start: int | None, end: int | None
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Where ``text[start:end]`` stands in what is served, and the snippet around it in
        that part alone: ``{part, start, end}`` with ``part`` ``title``, ``text`` or
        ``footnote`` and the offsets in it, of ``text`` with ``section_id`` (the innermost
        section it stands in), of a footnote with ``footnote`` (as printed) and
        ``footnote_id``. ``(None, None)`` for a citation that runs from one part into the
        next."""
        if start is None or end is None:
            return None, None
        part = next(
            (
                p
                for p in self.parts
                if p.start <= start and end <= p.start + len(p.text)
            ),
            None,
        )
        if part is None:
            return None, None
        local = (start - part.start + part.lead, end - part.start + part.lead)
        found: dict[str, Any] = {"part": part.place, "start": local[0], "end": local[1]}
        if part.place == PLACE_TEXT:
            section = section_at(self.sections, local[0])
            if section:
                found["section_id"] = section
        if part.place == PLACE_FOOTNOTE and part.index is not None:
            if part.label:
                found["footnote"] = part.label
            found["footnote_id"] = footnote_id(part.index)
        return found, make_snippet(" " * part.lead + part.text, local)


class _Builder:
    """The fragments joined by a newline, and the parts with where each starts."""

    def __init__(self) -> None:
        self.fragments: list[str] = []
        self.parts: list[_Part] = []
        self._length = 0  # of "\n".join(fragments)

    def _next_start(self) -> int:
        return self._length + (1 if self.fragments else 0)

    def _append(self, fragment: str) -> None:
        self._length = self._next_start() + len(fragment)
        self.fragments.append(fragment)

    def add(self, place: str, value: str) -> None:
        stripped = coerce_text(value)
        if not stripped:
            return
        lead = len(value) - len(value.lstrip())
        self.parts.append(_Part(place, self._next_start(), stripped, lead))
        self._append(stripped)

    def add_footnotes(self, footnotes: Sequence[Any]) -> None:
        """The footnotes as one fragment, a newline between two."""
        notes = [
            (index, note)
            for index, note in enumerate(footnotes)
            if isinstance(note, Mapping)
        ]
        block = "\n".join(str(note.get("text") or "") for _, note in notes)
        stripped = coerce_text(block)
        if not stripped:
            return
        start, lead, position = self._next_start(), len(block) - len(block.lstrip()), 0
        for index, note in notes:
            text = str(note.get("text") or "")
            offset = position - lead
            if text and offset >= 0:
                self.parts.append(
                    _Part(
                        PLACE_FOOTNOTE,
                        start + offset,
                        text,
                        index=index,
                        label=coerce_text(note.get("number")),
                    )
                )
            position += len(text) + 1
        self._append(stripped)
