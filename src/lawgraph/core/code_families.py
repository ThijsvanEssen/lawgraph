"""Codes whose books are regulations of their own, from the official abbreviations.

Every book of the Burgerlijk Wetboek is a regulation in the BWB (Boek 6: ``BWBR0005289``),
and the WTI of each lists the abbreviation of the code as well as its own book
(``BW``, ``BW Boek 6``, ``BW6``). ``families_from_wti`` reads the families from those lists: a
code is an abbreviation that two or more regulations list, each of which also lists a book of
it (``<code> Boek <n>``); the book is the ``<n>`` of that abbreviation (``7A`` too).

A citation of the code names the book in front of the colon (``art. 6:162 BW`` is article 162
of book 6), so the code itself never stands for one regulation, whichever books are loaded.

``data/code_families.json`` holds the families ``CODE_FAMILIES`` reads; ``lawgraph
code-families build`` makes it from the stored WTI records (``retrieve bwb``). Its ``names``
are the names a code goes by besides its abbreviation (``Burgerlijk Wetboek``), which no WTI
lists; a build keeps them.

A code is looked up in any case (``BW``, ``bw``, ``Bw``); an article of a book is cited with
its book (``cited_number``: ``6:162``) and stored with its own number (``native_number``:
``162``).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from lawgraph.config.constants import DATA_DIR

DATA = DATA_DIR / "code_families.json"

# ``BW Boek 7A``: the code and the book, as a WTI writes the book.
_BOOK = re.compile(r"^(?P<code>.+?)\s+Boek\s+(?P<book>\d+[A-Z]?)$", re.IGNORECASE)


def families_from_wti(
    abbreviations_by_id: Mapping[str, Sequence[str]],
) -> dict[str, dict[str, str]]:
    """Code -> book -> BWB id, from the WTI abbreviations of every regulation: a code two or
    more regulations list, each with a book of it. Books in the order of their number."""
    claims = Counter(
        claimed
        for abbreviations in abbreviations_by_id.values()
        for claimed in {a.upper() for a in abbreviations}
    )
    # a code in the spelling most regulations give it (``BW``, not one ``bw``)
    spellings = Counter(
        a for abbreviations in abbreviations_by_id.values() for a in abbreviations
    )
    families: dict[str, dict[str, str]] = defaultdict(dict)
    for regulation_id, abbreviations in sorted(abbreviations_by_id.items()):
        codes = {a.upper() for a in abbreviations}
        for abbreviation in abbreviations:
            match = _BOOK.match(abbreviation.strip())
            if not match:
                continue
            code = match["code"].upper()
            if code in codes and claims[code] >= 2:
                families[code][match["book"].upper()] = regulation_id
    return {
        max(
            (a for a in spellings if a.upper() == code), key=lambda a: (spellings[a], a)
        ): dict(sorted(books.items(), key=lambda b: (int(b[0].rstrip("A")), b[0])))
        for code, books in sorted(families.items())
    }


_DOCUMENT: dict[str, Any] = json.loads(DATA.read_text(encoding="utf-8"))
# Code -> book -> BWB id (``BW`` -> ``6`` -> ``BWBR0005289``).
CODE_FAMILIES: dict[str, dict[str, str]] = _DOCUMENT["families"]
# Code -> the names it goes by besides its abbreviation (``Burgerlijk Wetboek``).
FAMILY_NAMES: dict[str, list[str]] = _DOCUMENT["names"]


def code_of(name: str | None) -> str | None:
    """The code whose abbreviation *name* is, in any case (``bw``: ``BW``); ``None`` for
    none."""
    key = (name or "").strip().casefold()
    return next((code for code in CODE_FAMILIES if code.casefold() == key), None)


def is_code_family(name: str | None) -> bool:
    """Whether *name* is the abbreviation of a code with books, in any case."""
    return code_of(name) is not None


def family_named(name: str | None) -> str | None:
    """The code *name* names: by its abbreviation or by a name it goes by
    (``Burgerlijk Wetboek``), in any case."""
    key = (name or "").strip().casefold()
    return code_of(key) or next(
        (
            code
            for code, names in FAMILY_NAMES.items()
            if key in (n.casefold() for n in names)
        ),
        None,
    )


def _book(bwb_id: str | None) -> tuple[str, str] | None:
    """``(code, book)`` of a regulation that is a book of a code."""
    wanted = (bwb_id or "").upper()
    return next(
        (
            (code, book)
            for code, books in CODE_FAMILIES.items()
            for book, law_id in books.items()
            if law_id.upper() == wanted
        ),
        None,
    )


def family_of(bwb_id: str | None) -> str | None:
    """The code a regulation is a book of (``BW`` for ``BWBR0005289``)."""
    found = _book(bwb_id)
    return found[0] if found else None


def book_of(bwb_id: str | None) -> str | None:
    """The book a regulation is of its code (``6`` for ``BWBR0005289``)."""
    found = _book(bwb_id)
    return found[1] if found else None


def cited_number(bwb_id: str | None, number: str) -> str:
    """The number an article is cited by: ``6:162`` for article 162 of Boek 6. A number
    that names its book already, or of a law that is no book of a code, stays."""
    book = book_of(bwb_id)
    return f"{book}:{number}" if book and ":" not in number else number


def native_number(bwb_id: str | None, number: str) -> str:
    """The number an article has in its own book of a code: ``162`` for ``6:162`` under
    BW Boek 6 (BWBR0005289); ``cited_number`` undone. A number of another book, or of a law
    that is no book of a code (the Awb's ``8:69`` is its own), stays."""
    book = book_of(bwb_id)
    prefix = f"{book}:"
    return (
        number[len(prefix) :] if book and number.upper().startswith(prefix) else number
    )
