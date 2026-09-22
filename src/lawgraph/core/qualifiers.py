"""Which lid, onderdeel or aanhef a citation names — pure, no I/O.

A citation of an article often says where in the article it points: "derde lid",
"eerste en tweede lid", "lid 3", "leden 1 en 2", "onder a", "onderdeel b", "aanhef en
onder c", "eerste lid, onder 2°". :func:`parse_qualifier` reads such a string into a
:class:`Qualifier`, and never raises: text without a qualifier gives an empty one.

The values are written as the ids of article parts (``core.bwb_xml.ArticlePart``) are: a lid
is ``"3"`` (or ``"2a"``), an onderdeel ``"a"`` or ``"2"`` (the degree sign of ``2°`` is left
out, :func:`part_slug`), so ``lid-3`` and ``lid-3-onder-a`` name the parts a qualifier points
at. Ranges are written out (``tweede tot en met vierde lid`` is ``("2", "3", "4")``).

The parser scans a whole string and picks out every phrase it knows, so it reads the raw
qualifier the citation extractor captured (``CitationHit.qualifier``) as well as the text of
a link in a regulation ("artikel 5, eerste lid, onder f, van de Wet digitale overheid").
Sentences ("tweede volzin") are recognised and left out: they are no part of an article.
When a citation pairs different onderdelen with different leden, the lists hold the union.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

# The most a range is written out to; a longer one keeps its two ends only.
_MAX_RANGE = 50

_ORDINALS = {
    "eerste": 1,
    "tweede": 2,
    "derde": 3,
    "vierde": 4,
    "vijfde": 5,
    "zesde": 6,
    "zevende": 7,
    "achtste": 8,
    "negende": 9,
    "tiende": 10,
    "elfde": 11,
    "twaalfde": 12,
    "dertiende": 13,
    "veertiende": 14,
    "vijftiende": 15,
    "zestiende": 16,
    "zeventiende": 17,
    "achttiende": 18,
    "negentiende": 19,
    "twintigste": 20,
}
_ORDINAL = rf"(?:{'|'.join(_ORDINALS)}|\d+(?:e|de|ste))"
_LID_NUMBER = r"\d+[a-z]?(?![A-Za-z0-9:°]|\.\d)"
# Words of two letters or fewer that follow "onder" in ordinary sentences, not an onderdeel.
_NOT_A_PART = "de|het|een|dat|die|deze|in|is|op|of|en|te|er|om|na|nu|ze|zo|bij|uit|van|voor|wie|dan"
_SUB_TOKEN = rf"(?!(?:{_NOT_A_PART})\b)(?:[a-z]{{1,2}}|\d{{1,2}}[°º]?)(?![A-Za-z0-9])"
_SEPARATOR = r"\s*(?:,|\ben\b|\bof\b|\btot en met\b|\bt/m\b|\btot\b)\s*"

_LID_ORDINALS = re.compile(
    rf"\b(?P<items>{_ORDINAL}(?:{_SEPARATOR}{_ORDINAL})*)\s+lid(?:en)?\b", re.IGNORECASE
)
_LID_NUMBERS = re.compile(
    rf"\b(?:lid|leden)\s+(?P<items>{_LID_NUMBER}"
    rf"(?:{_SEPARATOR}(?:lid\s+)?{_LID_NUMBER})*)",
    re.IGNORECASE,
)
_ONDERDELEN = re.compile(
    rf"\b(?:onder(?:deel|delen)?|sub)\s+(?P<items>{_SUB_TOKEN}"
    rf"(?:{_SEPARATOR}(?:onder(?:deel|delen)?\s+|sub\s+)?{_SUB_TOKEN})*)",
    re.IGNORECASE,
)
_AANHEF = re.compile(r"\baanhef\b", re.IGNORECASE)
_SPLIT = re.compile(rf"({_SEPARATOR})", re.IGNORECASE)
_RANGE_WORDS = ("tot en met", "t/m", "tot")


@dataclass(frozen=True)
class Qualifier:
    """The parts of an article a citation names."""

    leden: tuple[str, ...] = ()
    onderdelen: tuple[str, ...] = ()
    aanhef: bool = False

    @property
    def empty(self) -> bool:
        return not (self.leden or self.onderdelen or self.aanhef)

    def to_dict(self) -> dict[str, Any]:
        """The fields as stored on a reference or an edge."""
        return {
            "leden": list(self.leden),
            "onderdelen": list(self.onderdelen),
            "aanhef": self.aanhef,
        }

    @classmethod
    def from_dict(cls, stored: Mapping[str, Any] | None) -> Qualifier:
        """Read :meth:`to_dict` back; missing or malformed fields are left empty."""
        if not isinstance(stored, Mapping):
            return cls()
        return cls(
            leden=_strings(stored.get("leden")),
            onderdelen=_strings(stored.get("onderdelen")),
            aanhef=stored.get("aanhef") is True,
        )


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, (str, int)))


def part_slug(number: str | None) -> str:
    """A printed lid number or onderdeel marker as it is written in part ids and qualifiers.

    ``"a."`` is ``"a"``, ``"1°."`` is ``"1"``, ``"2a"`` stays; a marker without a letter or
    a digit (a dash) is ``""``.
    """
    return re.sub(r"[^a-z0-9]", "", (number or "").lower())


def parse_qualifier(text: str | None) -> Qualifier:
    """Read the leden, onderdelen and aanhef a qualifier (or a whole citation) names."""
    if not text:
        return Qualifier()
    leden = [
        number
        for match in _LID_ORDINALS.finditer(text)
        for number in _items(match["items"], _ordinal_number)
    ] + [
        number
        for match in _LID_NUMBERS.finditer(text)
        for number in _items(match["items"], _lid_number)
    ]
    onderdelen = [
        marker
        for match in _ONDERDELEN.finditer(text)
        for marker in _items(match["items"], _onderdeel)
    ]
    return Qualifier(
        leden=tuple(dict.fromkeys(leden)),
        onderdelen=tuple(dict.fromkeys(onderdelen)),
        aanhef=bool(_AANHEF.search(text)),
    )


def _ordinal_number(word: str) -> str:
    word = word.strip().lower()
    if word in _ORDINALS:
        return str(_ORDINALS[word])
    return re.sub(r"\D+$", "", word)


def _lid_number(token: str) -> str:
    return re.sub(r"^(?:lid|leden)\s+", "", token.strip().lower())


def _onderdeel(token: str) -> str:
    return part_slug(
        re.sub(r"^(?:onder(?:deel|delen)?|sub)\s+", "", token.strip().lower())
    )


def _items(raw: str, normalize: Callable[[str], str]) -> list[str]:
    """The values of a list like ``2, 3 tot en met 5 en 7``, its ranges written out."""
    values: list[str] = []
    range_from: str | None = None
    for piece in _SPLIT.split(raw):
        word = piece.strip().lower()
        if word in _RANGE_WORDS:
            range_from = values[-1] if values else None
        elif word in {",", "en", "of"}:
            range_from = None
        elif word:
            value = normalize(word)
            if range_from is not None:
                values.extend(_between(range_from, value))
                range_from = None
            values.append(value)
    return [value for value in values if value]


def _between(first: str, last: str) -> list[str]:
    """The values strictly between *first* and *last*: numbers and single letters only."""
    if first.isdigit() and last.isdigit():
        low, high = int(first), int(last)
        if 1 < high - low <= _MAX_RANGE:
            return [str(n) for n in range(low + 1, high)]
    elif len(first) == len(last) == 1 and first.isalpha() and last.isalpha():
        low, high = ord(first), ord(last)
        if 1 < high - low:
            return [chr(n) for n in range(low + 1, high)]
    return []
