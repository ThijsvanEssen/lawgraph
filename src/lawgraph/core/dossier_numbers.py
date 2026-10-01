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
# "Vaststelling van de begrotingsstaten van het Ministerie van Defensie (X) voor het jaar
# 2027", "Wijziging van de begrotingsstaat van het gemeentefonds voor het jaar 2026
# (wijziging samenhangende met de Miljoenennota)": what a budget and a change of it hold.
_BUDGET = re.compile(
    r"^(?P<act>Vaststelling|Wijziging) van de begrotingssta(?:at|ten) (?:van|voor) "
    r"(?:het Ministerie van |het |de )?(?P<name>.+?)"
    r"(?= \(| en (?:de|het) |, (?:de|het) | voor het jaar)"
    r".*?voor het jaar (?P<year>\d{4})"
    r"(?:\s*\(wijziging samenhangende met de (?P<nota>[^()]+)\))?\s*$",
    re.IGNORECASE | re.DOTALL,
)

# "Jaarverslag en slotwet Ministerie van Defensie 2025"
_FINAL_ACT = re.compile(
    r"^Jaarverslag en slotwet (?:(?:het )?Ministerie van )?(?P<name>.+?) (?P<year>\d{4})\s*$",
    re.IGNORECASE,
)


def _budget_title(title: str) -> str | None:
    """``Begroting Defensie 2027``, ``Suppletoire begroting gemeentefonds 2026
    (Miljoenennota)``, ``Slotwet Defensie 2025``: a budget named by its chapter and year, a
    change of it also by the nota it goes with; None for another title."""
    final = _FINAL_ACT.match(title.strip())
    if final:
        return f"Slotwet {final['name'].strip()} {final['year']}"
    match = _BUDGET.match(title.strip())
    if not match:
        return None
    act = (
        "Begroting"
        if match["act"].lower() == "vaststelling"
        else "Suppletoire begroting"
    )
    name = f"{act} {match['name'].strip()} {match['year']}"
    return f"{name} ({match['nota'].strip()})" if match["nota"] else name


def short_title(title: str | None) -> str | None:
    """The name a dossier goes by: of a budget or a change of it its chapter and year
    (``_budget_title``), else the short title in parentheses that ends the title of a bill,
    before where the act it carries out was published (``_PUBLICATION``); None without
    one."""
    budget = _budget_title(title or "")
    if budget:
        return budget
    match = _SHORT_TITLE.search(_PUBLICATION.sub("", title or ""))
    return match.group(1).strip() if match else None
