"""Identifier patterns shared across sources."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# BWB ids: BWBR + 7 digits for statutes and regulations, BWBV + 7 digits for treaties.
BWB_ID_PATTERN = re.compile(r"\b(BWB[RV]\d{7})\b", re.IGNORECASE)
_BWB_ID_FULL = re.compile(r"BWB[RV]\d{7}", re.IGNORECASE)


def is_bwb_id(value: str) -> bool:
    """True for a complete BWB id (``BWBR0001840``, ``BWBV0001000``)."""
    return bool(_BWB_ID_FULL.fullmatch(value.strip()))


# ---------------------------------------------------------------------------
# CELEX
# ---------------------------------------------------------------------------

# Sector-3 (legislation) CELEX type letters: 3 + year + letter + number.
# R=regulation, L=directive, D=decision, F=framework decision, H=recommendation.
CELEX_KIND_TO_LETTER: dict[str, str] = {
    "regulation": "R",
    "directive": "L",
    "decision": "D",
    "framework_decision": "F",
    "recommendation": "H",
}
CELEX_LETTER_TO_KIND: dict[str, str] = {
    letter: kind for kind, letter in CELEX_KIND_TO_LETTER.items()
}

# Letters accepted when *matching* CELEX ids in text.  Deliberately lenient:
# ``C`` is not a sector-3 legislation type, but earlier code generated it for
# decisions and it may still occur in stored data, so it is still recognised.
_CELEX_MATCH_LETTERS = "CLRDF"

# A CELEX id embedded in free text: sector 3, year, type letter, 4-digit number.
CELEX_PATTERN = re.compile(
    rf"\b3\d{{4}}[{_CELEX_MATCH_LETTERS}]\d{{4}}\b", re.IGNORECASE
)
_CELEX_FULL = re.compile(rf"^3(\d{{4}})([{_CELEX_MATCH_LETTERS}])(\d+)$", re.ASCII)


@dataclass(frozen=True)
class ParsedCelex:
    """A sector-3 CELEX id taken apart.

    *kind* is ``None`` for a letter that is matched leniently but has no
    legislation meaning (``C``).
    """

    year: str
    letter: str
    number: str
    kind: str | None


def parse_celex(value: str) -> ParsedCelex | None:
    """Parse a complete sector-3 CELEX id (case-insensitive), or return ``None``.

    The number part may have any length; use :data:`CELEX_PATTERN` to find ids
    in text (exactly four digits).
    """
    m = _CELEX_FULL.match(value.upper())
    if not m:
        return None
    year, letter, number = m.groups()
    return ParsedCelex(year, letter, number, CELEX_LETTER_TO_KIND.get(letter))


def find_celex_ids(text: str) -> list[str]:
    """Return the numeric CELEX ids found in *text*, upper-cased, in order."""
    return [m.group(0).upper() for m in CELEX_PATTERN.finditer(text)]


# ── KOOP publication ids and id-list cleaning ────────────────────────────────

# Staatsblad / Staatscourant identifiers: ``stb-<year>-<number>``, ``stcrt-...``.
STB_ID_PATTERN = re.compile(r"stb-(\d{4})-(\d+)", re.IGNORECASE)
STCRT_ID_PATTERN = re.compile(r"stcrt-(\d{4})-(\d+)", re.IGNORECASE)
KST_ID_PATTERN = re.compile(r"kst-(\d+(?:-[A-Za-z]+)?)-(\d+[A-Za-z]?)", re.IGNORECASE)


def kamerstuk_identifier(number: str, suffix: str | None, sequence: int | str) -> str:
    """``kst-37020-X-2``: dossier number, its addition (a budget chapter) and the paper number."""
    dossier = f"{number}-{suffix}" if suffix else str(number)
    return f"kst-{dossier}-{sequence}"


def clean_ids(values: Iterable[str | None] | None) -> list[str]:
    """Strip *values*, drop empty/None entries and duplicates; keep first-seen order."""
    if not values:
        return []
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def find_bwb_id(text: str) -> str | None:
    """First BWB id found in *text*, upper-cased, or ``None``."""
    match = BWB_ID_PATTERN.search(text)
    return match.group(1).upper() if match else None


# ---------------------------------------------------------------------------
# ECLI
# ---------------------------------------------------------------------------

# ECLI:<country>:<court>:<year>:<case number>; the case number is alphanumeric and may
# contain dots, underscores or hyphens (ECLI:NL:HR:2005:AU1234, ECLI:CE:ECHR:2019:0101JUD001234510).
_ECLI_BODY = r"ECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:[A-Z0-9]+(?:[._-][A-Z0-9]+)*"
ECLI_PATTERN = re.compile(rf"\b{_ECLI_BODY}\b", re.IGNORECASE)
_ECLI_FULL = re.compile(_ECLI_BODY, re.IGNORECASE)

# ECLI prefix -> judgment source.
ECLI_SOURCES: tuple[tuple[str, str], ...] = (
    ("ECLI:NL:", "rechtspraak"),
    ("ECLI:CE:ECHR:", "echr"),
    ("ECLI:EU:", "cjeu"),
)


def is_ecli(value: str) -> bool:
    """True for a complete ECLI."""
    return bool(_ECLI_FULL.fullmatch(value.strip()))


def find_eclis(text: str | None) -> list[str]:
    """Unique ECLIs in *text*, upper-cased, in order of first appearance."""
    if not text:
        return []
    return list(dict.fromkeys(m.group(0).upper() for m in ECLI_PATTERN.finditer(text)))


def ecli_source(ecli: str | None) -> str | None:
    """Judgment source (``rechtspraak`` / ``echr`` / ``cjeu``) from the ECLI prefix."""
    if not ecli:
        return None
    upper = ecli.upper()
    return next(
        (source for prefix, source in ECLI_SOURCES if upper.startswith(prefix)), None
    )
