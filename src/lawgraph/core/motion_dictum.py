"""The form of a motion: its opening and closing formula, and its dictum, what the Kamer asks or
says, as the motion writes it.

A motion of the Tweede Kamer has one form: "De Kamer, gehoord de beraadslaging, constaterende
…; overwegende …; verzoekt de regering …, en gaat over tot de orde van de dag." Its dictum is
the lines from the first that begins with what the Kamer does (``verzoekt``, ``roept … op``,
``spreekt uit``, ``draagt … op``, ``vraagt``: of 400 motions with text, 421 such lines began
with ``verzoekt``, 12 with ``roept``, 11 with ``spreekt`` and 1 with ``vraagt``) to the
closing formula, every such line when there are several. The form is the Kamer's own;
nothing is interpreted. A text without the closing formula is no motion (a letter, a note)
and has none.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# The closing formula of a motion.
_CLOSING = re.compile(r"^\s*en\s+gaat\s+over\s+tot\s+de\s+orde\s+van\s+de\s+dag", re.I)
# A line that begins with what the Kamer does: the first line of the dictum.
_OPERATIVE = re.compile(r"^\s*(verzoekt|roept|spreekt|draagt|vraagt)\b", re.I)
# A line of the opening formula, "De Kamer," and "gehoord de beraadslaging," (one line or two),
# and nothing else: a line that goes on with an overweging is one.
_OPENING = re.compile(
    r"\s*(?=\S)(?:de\s+kamer\s*,?\s*)?(?:gehoord\s+de\s+beraadslaging\s*,?\s*)?", re.I
)


def closing_formula(lines: Sequence[str]) -> int | None:
    """Where the closing formula of a motion stands in *lines*; None without one."""
    return next((n for n, line in enumerate(lines) if _CLOSING.match(line)), None)


def is_opening(line: str) -> bool:
    """Whether *line* is (a part of) the opening formula of a motion and nothing more."""
    return _OPENING.fullmatch(line) is not None


def read_dictum(text: str | None) -> str | None:
    """The dictum of the motion *text* (its lines joined by a space, the comma before the
    closing formula left off); None when *text* has no closing formula or no line that
    begins with what the Kamer does."""
    if not text:
        return None
    lines = text.splitlines()
    closing = closing_formula(lines)
    if closing is None:
        return None
    start = next(
        (n for n, line in enumerate(lines[:closing]) if _OPERATIVE.match(line)),
        None,
    )
    if start is None:
        return None
    dictum = " ".join(line.strip() for line in lines[start:closing] if line.strip())
    return dictum.rstrip(" ,;") or None
