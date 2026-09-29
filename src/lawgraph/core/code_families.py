"""Codes whose books are regulations of their own, from the official abbreviations.

Every book of the Burgerlijk Wetboek is a regulation in the BWB (Boek 6: ``BWBR0005289``),
and the WTI of each lists the abbreviation of the code as well as its own book
(``BW``, ``BW Boek 6``, ``BW6``). ``families_from_wti`` reads the families from those lists: a
code is an abbreviation that two or more regulations list, each of which also lists a book of
it (``<code> Boek <n>``); the book is the ``<n>`` of that abbreviation (``7A`` too).

A citation of the code names the book in front of the colon (``art. 6:162 BW`` is article 162
of book 6), so the code itself never stands for one regulation, whichever books are loaded.

``data/code_families.json`` holds the families ``CODE_FAMILIES`` reads; ``lawgraph
code-families build`` makes it from the stored WTI records (``retrieve bwb``).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "code_families.json"

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


def load_families(path: Path = DATA) -> dict[str, dict[str, str]]:
    """The families of ``data/code_families.json``."""
    families: dict[str, dict[str, str]] = json.loads(path.read_text(encoding="utf-8"))[
        "families"
    ]
    return families


# Code -> book -> BWB id (``BW`` -> ``6`` -> ``BWBR0005289``).
CODE_FAMILIES: dict[str, dict[str, str]] = load_families()
