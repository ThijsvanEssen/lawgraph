"""Dossier numbers and suffixes: how the Kamer orders the dossiers of one number.

A Kamerstukdossier is a number plus, where the Kamer gives one, a suffix (``Toevoeging``):
``37035-XXII``, ``21501-31``, ``23908-(R1519)``. Each is a dossier of its own; the dossiers of
one number belong together (the chapters and funds of one budget, the meetings of one Council
series).
"""

from __future__ import annotations

import re

from lawgraph.core.budget_titles import parse_budget_title

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


# ``36600-VIII``, ``23908-(R1519)``: a number and its suffix as the data and the addresses join
# them. A digit after the hyphen (``21501-20``) is part of the number, and is cited so.
_JOINED_SUFFIX = re.compile(r"^(\d+)-([A-Z]+|\([A-Z0-9]+\))$", re.IGNORECASE)


def official_number(label: str) -> str:
    """A dossier number as a citation writes it, its suffix after a space: ``36600 VIII``,
    ``23908 (R1519)``; ``21501-20`` stays. For the text a reader sees, never for an address
    or a key."""
    return _JOINED_SUFFIX.sub(r"\1 \2", label)


# ``33440-(R1990)``: a dossier of a Rijkswet, its number and the number of the Rijkswet.
_RIJKSWET_LABEL = re.compile(r"^(\d+)-\(R\d+\)$", re.IGNORECASE)


def published_number(label: str) -> str:
    """The number of the dossier *label* as the Staatsblad, the BWB and the Verdragenbank
    name it: a Rijkswet's without the number of the Rijkswet (``33440-(R1990)`` is
    ``33440``), any other as it is (``36200-VII``)."""
    match = _RIJKSWET_LABEL.match(label)
    return match.group(1) if match else label


# "Kamerstukken 35 418", "Kamerstukken II 2019/20, 35 419, nr. 9": the dossier a document cites.
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


def dossier_order(number: str | None, suffix: str | None) -> str:
    """A text that sorts the dossiers as the Kamer lists them: by number, then the dossiers
    of one number by ``suffix_sort_key`` (``36264`` < ``36264-I`` < ``37020`` < ``37020-XV``).
    Stored as ``props.order``, so a list sorts on an index."""
    group, value, text = suffix_sort_key(suffix)
    digits = number if number and number.isdigit() else "0"
    return f"{int(digits):08d}.{group}.{value:04d}.{text}"


# "Wijziging van ... (Verzamelwet gegevensbescherming)": the name a bill goes by.
_SHORT_TITLE = re.compile(r"\(([^()]{3,120})\)\s*$")
# Where the act a bill carries out was published, after its short title: "(PbEU 2022, L
# 173)", "(Trb. 2021, 52)", "(Stb. 2019, 12)". No name of the bill.
_PUBLICATION = re.compile(r"\s*\((?:PbEU|PbEG|Trb\.|Stb\.|Stcrt\.)\s[^()]*\)\s*$")


def short_title(title: str | None) -> str | None:
    """The name a dossier goes by: of a budget law its chapter and year
    (``BudgetTitle.short_title``), else the short title in parentheses that ends the title of
    a bill, before where the act it carries out was published (``_PUBLICATION``); None
    without one."""
    budget = parse_budget_title(title)
    if budget and budget.short_title:
        return budget.short_title
    match = _SHORT_TITLE.search(_PUBLICATION.sub("", title or ""))
    return match.group(1).strip() if match else None
