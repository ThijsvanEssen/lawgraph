"""The chamber or division of a court that a judgment's kop names.

The metadata of the Rechtspraak names the court and the area of law, not the chamber; the kop
does, in a line of its own right after the court's name: ``Strafkamer``, ``CIVIELE KAMER``,
``locatie Arnhem, afdeling civiel recht``, ``Team Handel``. Only a line that says so is read;
the composition of the bench (``meervoudige kamer``) is no chamber.
"""

from __future__ import annotations

import re
from typing import Any

# How many lines after the court's name the chamber is looked for in.
KOP_LINES_SEARCHED = 6

_COMPOSITION = re.compile(
    r"^(?:(?:derde|tweede|eerste)\s+)?(?:meervoudige|enkelvoudige)\s+", re.IGNORECASE
)
# "Strafkamer", "CIVIELE KAMER", "Eerste Kamer", "Meervoudige Belastingkamer"
_CHAMBER = re.compile(r"^(?:\w+\s+kamer|\w+kamer)$", re.IGNORECASE)
# "afdeling civiel recht en belastingrecht, team I", after "locatie Arnhem, "
_DIVISION = re.compile(
    r"^(?:locatie\s+[^,]+,\s*)?(afdeling\s+.+|team\s+.+|sector\s+.+)$", re.IGNORECASE
)
_BARE_DIVISION = re.compile(r"^afdeling$", re.IGNORECASE)
_NOT_A_CHAMBER = re.compile(r"^(?:meervoudige|enkelvoudige)\s+kamer$", re.IGNORECASE)


def _written(line: str) -> str:
    """*line* as a name: a line in capitals in lower case, its first letter capital."""
    text = line.strip(" .:;,")
    if text.isupper():
        text = text.lower()
    return text[:1].upper() + text[1:]


def chamber_of_kop(lines: list[str]) -> str | None:
    """The chamber or division the *lines* of a kop name, as written (``Strafkamer``,
    ``Afdeling civiel recht``); None when none of the lines after the court's name does."""
    searched = [
        line.strip() for line in lines[1 : 1 + KOP_LINES_SEARCHED] if line.strip()
    ]
    for position, line in enumerate(searched):
        if _NOT_A_CHAMBER.match(line):
            continue
        if _BARE_DIVISION.match(line) and position + 1 < len(searched):
            # the Raad van State sets "AFDELING" and "BESTUURSRECHTSPRAAK" on two lines
            return _written(f"{line} {searched[position + 1]}")
        found = _DIVISION.match(line)
        if found:
            return _written(found.group(1))
        stripped = _COMPOSITION.sub("", line)
        if _CHAMBER.match(stripped):
            return _written(stripped)
    return None


def chamber_of(paragraphs: list[dict[str, Any]] | None) -> str | None:
    """The chamber of a judgment from its paragraphs: its kop is the first one."""
    for paragraph in paragraphs or []:
        text = paragraph.get("text") if isinstance(paragraph, dict) else None
        if text:
            return chamber_of_kop(text.split("\n"))
    return None
