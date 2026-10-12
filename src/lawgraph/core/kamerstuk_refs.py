"""The Kamerstukken a subject names: "(Kamerstuk 25424-795)", taken apart.

The Kamer gives a letter that carries out a motion its own case; the subject names the
motion in its standard form: "Uitvoering van de motie van het lid Vliegenthart c.s. over …
(Kamerstuk 25424-795)". The forms read here::

    Kamerstuk 25424-795                  dossier, paper
    Kamerstuk 36945-XIV-1                dossier with its suffix (a budget chapter), paper
    Kamerstuk 21501-02-3465              a numeric suffix, when that dossier exists
    Kamerstuk 35261-13-15-16             several papers of one dossier
    Kamerstuk 29 507, nr. 146            the number spaced, "nr."
    Kamerstuk 36 200 XVI, nr. 12         the suffix spaced
    Kamerstuk 36441, nrs. 38 en 39       several papers
    Kamerstukken II 2025/26, 36600-XV, nr. 5
    Kamerstuk 36222-8 en Kamerstuk 36222-9, Kamerstuk 36600-VII en 36600-VI

A dossier without a paper (``Kamerstuk 37020-XIV``) and a paper of the Eerste Kamer by its
letter (``37035-M``) name no paper of the Tweede Kamer and are left out, and so is the paper
an amended motion or amendment replaces ("ter vervanging van Kamerstuk 29826-322"): that is
``REVISES`` (``Zaak.VervangenVanuit``), not a reference. Pure: *is_dossier*
says which ``(number, suffix)`` is a dossier, so ``21501-02-3465`` is paper 3465 of
``21501-02`` and ``35261-13-15`` papers 13 and 15 of ``35261``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# "Kamerstuk", "Kamerstukken II 2025/26,", "kamerstuknummer"
_KEYWORD = re.compile(
    r"\bkamerstuk(?:ken|nummer)?\b(?:\s+I{1,2}\b)?\s*,?(?:\s*\d{4}/\d{2,4}\s*,?)?\s*",
    re.IGNORECASE,
)
# One dossier and the papers named with it, right where the keyword (or "en") leaves off.
_REFERENCE = re.compile(
    r"""
    (?P<number>\d{2}\s?\d{3})(?![\d/])
    (?P<chain>(?:-(?:[A-Z]{1,6}|\d{1,4})(?![\dA-Za-z(]))*)
    (?:\s+(?P<spaced>[IVXL]{1,6}[AB]?)(?![\w-]))?
    (?:\s*,?\s*(?i:nrs?)\.?\s*(?P<nrs>\d{1,4}(?:\s*(?:,|\ben\b)\s*\d{1,4})*)(?![\d/]))?
    (?P<more>(?:\s*(?:,|\ben\b)\s*\d{1,4}(?![\d/\-]))*)
    """,
    re.VERBOSE,
)
# "ter vervanging van": the paper a motion or amendment replaces
_REPLACES = re.compile(r"vervanging\s+van\s*$", re.IGNORECASE)
# Another dossier after the first: ", 36600-VI", " en Kamerstuk 36222-9".
_NEXT = re.compile(r"\s*(?:,|;|\ben\b)\s*(?:(?i:kamerstuk(?:ken)?)\s*)?")
_NUMBER = re.compile(r"\d{1,4}")


@dataclass(frozen=True)
class PaperRef:
    """Paper *sequence* (ondernummer) of the dossier *number*-*suffix*, as *text* names it."""

    number: str
    suffix: str | None
    sequence: int
    text: str


def _papers(
    match: re.Match[str], is_dossier: Callable[[str, str | None], bool]
) -> list[PaperRef]:
    number = re.sub(r"\s", "", match["number"])
    chain = [t for t in match["chain"].split("-") if t]
    suffix: str | None = None
    if match["spaced"] and not chain:
        suffix = match["spaced"]
    elif chain and not chain[0].isdigit():
        suffix = chain.pop(0)
    elif chain and is_dossier(number, chain[0]):
        # "21501-02": the dossier 21501-02, not paper 2 of 21501
        suffix = chain.pop(0)
    if any(not token.isdigit() for token in chain):
        return []  # "37035-M-A": a paper of the Eerste Kamer by its letter
    numbers = [
        *chain,
        *_NUMBER.findall(match["nrs"] or ""),
        *(_NUMBER.findall(match["more"] or "") if chain or match["nrs"] else []),
    ]
    text = match.group(0).strip()
    return [
        PaperRef(number, suffix, int(n), text)
        for n in dict.fromkeys(numbers)
        if int(n) > 0
    ]


def cited_papers(
    text: str | None, is_dossier: Callable[[str, str | None], bool]
) -> list[PaperRef]:
    """Every Kamerstuk with a paper number that *text* names after "Kamerstuk", in order,
    each once."""
    text = text or ""
    found: list[PaperRef] = []
    for keyword in _KEYWORD.finditer(text):
        if _REPLACES.search(text, 0, keyword.start()):
            continue
        position = keyword.end()
        while match := _REFERENCE.match(text, position):
            found += _papers(match, is_dossier)
            following = _NEXT.match(text, match.end())
            if following is None:
                break
            position = following.end()
    return list(dict.fromkeys(found))
