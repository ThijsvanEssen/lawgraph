"""The dictum of a motion: what the Kamer asks or says, as the motion writes it.

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

# The closing formula of a motion.
_CLOSING = re.compile(r"^\s*en\s+gaat\s+over\s+tot\s+de\s+orde\s+van\s+de\s+dag", re.I)
# A line that begins with what the Kamer does: the first line of the dictum.
_OPERATIVE = re.compile(r"^\s*(verzoekt|roept|spreekt|draagt|vraagt)\b", re.I)


def read_dictum(text: str | None) -> str | None:
    """The dictum of the motion *text* (its lines joined by a space, the comma before the
    closing formula left off); None when *text* has no closing formula or no line that
    begins with what the Kamer does."""
    if not text:
        return None
    lines = text.splitlines()
    closing = next((n for n, line in enumerate(lines) if _CLOSING.match(line)), None)
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
