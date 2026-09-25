"""Dossier numbers and suffixes: how the Kamer orders the dossiers of one number.

A Kamerstukdossier is a number plus, where the Kamer gives one, a suffix (``Toevoeging``):
``37035-XXII``, ``21501-31``, ``23908-(R1519)``. Each is a dossier of its own; the dossiers of
one number belong together (the chapters and funds of one budget, the meetings of one Council
series).
"""

from __future__ import annotations

import re

# A budget chapter is a Roman numeral with at most a letter after it (IIA, IXB). A fund is a
# letter (A, M): L, C and M are funds, never chapter numerals.
_CHAPTER = re.compile(r"^([IVX]+)([A-C])?$")
_ROMAN = {"I": 1, "V": 5, "X": 10}

# What a user types for a dossier: 37035, 37035-XXII, 37035 XXII, 23908-(R1519).
_DOSSIER_QUERY = re.compile(r"^\s*(\d+)(?:\s*[-\s]\s*(\S+))?\s*$")


def _roman_value(numeral: str) -> int:
    total = 0
    for i, char in enumerate(numeral):
        value = _ROMAN[char]
        following = _ROMAN.get(numeral[i + 1], 0) if i + 1 < len(numeral) else 0
        total += -value if value < following else value
    return total


def suffix_sort_key(suffix: str | None) -> tuple[int, int, str]:
    """Orders the dossiers of one number as the Kamer does.

    No suffix first, then numeric suffixes by value (``21501-02`` before ``21501-31``), then
    budget chapters by value with their letter (``I``, ``IIA``, ``IIB``, ``III``, ... ``XXIII``),
    then everything else by its text: the funds (``A``, ``B``, ``M``) and suffixes such as
    ``(R1519)``.
    """
    if not suffix:
        return (0, 0, "")
    if suffix.isdigit():
        return (1, int(suffix), "")
    chapter = _CHAPTER.match(suffix)
    if chapter:
        return (2, _roman_value(chapter.group(1)), chapter.group(2) or "")
    return (3, 0, suffix)


def parse_dossier_query(text: str | None) -> tuple[str, str | None] | None:
    """``(number, suffix or None)`` when *text* names a dossier or a number, else None.

    ``37035`` names every dossier of that number, ``37035-XXII`` (or ``37035 XXII``) one of
    them. The suffix is upper-cased, as the Kamer writes it.
    """
    match = _DOSSIER_QUERY.match(text or "")
    if not match:
        return None
    suffix = match.group(2)
    return match.group(1), suffix.upper() if suffix else None


# "Kamerstukken 35 418", "Kamerstukken II 2019/20, 35 419, nr. 9": the dossier a paper cites.
_CITED_DOSSIER = re.compile(
    r"\bKamerstukken(?:\s+I{1,2})?(?:\s+\d{4}/\d{2,4})?,?\s+(\d{2})\s?(\d{3})\b"
)


def first_reading_dossiers(text: str | None) -> list[str]:
    """The dossiers of the first reading that the memorandum of a second reading of a
    change in the Grondwet refers to for its explanation ("Voor de toelichting verwijzen
    wij naar de met betrekking tot de eerste lezing ... gewisselde stukken (Kamerstukken
    35 418, Kamerstukken II 2019/20, 35 419, nr. 9 ...)"): every dossier a text cites that
    speaks of a first reading, in order; none for another text."""
    if not text or "eerste lezing" not in text.lower():
        return []
    return list(dict.fromkeys(a + b for a, b in _CITED_DOSSIER.findall(text)))
