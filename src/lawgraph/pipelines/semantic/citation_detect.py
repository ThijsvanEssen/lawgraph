"""Shared citation-detection primitives used across semantic pipelines.

This module provides a single source of truth for the ``CitationHit`` dataclass,
helper utilities, and the ``DutchCitationExtractor`` class that all semantic
pipelines use to detect Dutch legal article citations.

Public API
----------
CitationHit
    Unified dataclass for any detected legal citation.
ArticleKind
    ``Literal["article", "instrument"]`` discriminant.
DutchCitationExtractor
    Registry-driven extractor for Dutch article citations in natural-language text.
make_snippet
    Extract surrounding text context around a regex match span.
normalize_code_aliases
    Normalise a ``{alias: identifier}`` mapping to uppercase keys.
format_celex
    Render a numeric CELEX identifier from directive/regulation kind, year and number.
coerce_text
    Safely coerce any value to a stripped non-empty string, or ``None``.
strip_xml
    Strip XML/HTML tags and normalise whitespace for clean regex matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

ArticleKind = Literal["article", "instrument"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SNIPPET_WINDOW = 300
_XML_TAG_RE = re.compile(r"<[^>]+>")

# ---------------------------------------------------------------------------
# CitationHit dataclass
# ---------------------------------------------------------------------------


@dataclass
class CitationHit:
    """A detected reference to an article or instrument found in a document.

    *kind* discriminates between a reference to a specific article (``"article"``)
    and a reference to a whole instrument (``"instrument"``).

    At most one of *bwb_id* / *celex* is populated, identifying the target law.
    For article-level references *article_number* is always set.
    """

    kind: ArticleKind = "article"
    bwb_id: str | None = None
    article_number: str | None = None
    celex: str | None = None
    confidence: float = 0.0
    raw_match: str | None = None
    snippet: str | None = None
    qualifier: str | None = None  # e.g. "derde lid", "eerste en tweede lid"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def make_snippet(text: str, span: tuple[int, int]) -> str:
    """Return a context window of *SNIPPET_WINDOW* chars around *span*."""
    start, end = span
    begin = max(0, start - SNIPPET_WINDOW)
    finish = min(len(text), end + SNIPPET_WINDOW)
    return text[begin:finish].strip()


def normalize_code_aliases(mapping: dict[str, str]) -> dict[str, str]:
    """Normalise a code-alias → BWB/CELEX mapping to uppercase keys and values."""
    normalized: dict[str, str] = {}
    for alias, target in mapping.items():
        if not alias or not target:
            continue
        normalized[alias.strip().upper()] = target.strip().upper()
    return normalized


_KIND_TO_CELEX_LETTER: dict[str, str] = {
    "directive": "L",
    "regulation": "R",
    "decision": "C",
    "framework_decision": "D",
}


def format_celex(
    kind: Literal["directive", "regulation", "decision", "framework_decision"],
    year: str,
    number: str,
) -> str:
    """Render a numeric CELEX identifier.

    Supported kinds and their CELEX sector letters:
    - ``"directive"`` → ``L``
    - ``"regulation"`` → ``R``
    - ``"decision"`` → ``C``
    - ``"framework_decision"`` → ``D``

    Example: ``format_celex("directive", "2010", "64")`` → ``"32010L0064"``
    """
    letter = _KIND_TO_CELEX_LETTER.get(kind, "L")
    padded = 0
    try:
        padded = int(number)
    except ValueError:
        logger.debug("Could not parse CELEX number %r; using 0 as fallback", number)
    return f"3{year}{letter}{padded:04d}"


def _hit_reason(hit: CitationHit) -> str:
    """Derive a short reason label from a CitationHit's populated fields."""
    if hit.bwb_id and hit.article_number:
        return "bwb_article"
    if hit.celex and hit.article_number:
        return "celex_article"
    if hit.bwb_id:
        return "bwb_instrument"
    if hit.celex:
        return "celex_instrument"
    return "unknown"


def coerce_text(value: object) -> str | None:
    """Safely coerce *value* to a stripped non-empty string, or ``None``."""
    if value is None:
        return None
    candidate = str(value).strip()
    return candidate if candidate else None


def strip_xml(text: str) -> str:
    """Remove XML/HTML tags and collapse whitespace for clean regex matching."""
    stripped = _XML_TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", stripped).strip()


# ---------------------------------------------------------------------------
# DutchCitationExtractor — registry-driven article citation detection
# ---------------------------------------------------------------------------

# Article number: plain (140), with letter suffix (36e, 189a), with colon-parts (6:162)
_ART_NUM_PAT = r"\d+(?::\d+)*[a-z]*"

# Ordinal words used in "lid" qualifiers
_ORDINALS_PAT = (
    r"eerste|tweede|derde|vierde|vijfde|zesde|zevende" r"|achtste|negende|tiende|\d+e"
)

# One "lid" item: "derde lid", "eerste en tweede lid", "eerste of tweede lid"
_LID_ITEM_PAT = (
    rf"(?:{_ORDINALS_PAT})" rf"(?:\s+(?:en|of)\s+(?:{_ORDINALS_PAT}))?" r"\s+lid(?:en)?"
)

# Sub-article qualifier: "aanhef", "onderdeel a", "sub b"
_SUB_ITEM_PAT = (
    r"aanhef(?:\s+en\s+(?:sub|onderdeel)\s+[a-z\d°]+)?"
    r"|(?:sub|onderdeel)\s+[a-z\d°]+"
)

# Full qualifier: zero or more comma-separated lid/sub items
# Matches: "", ", derde lid", ", eerste lid, onderdeel a", etc.
_QUALIFIER_PAT = rf"(?:\s*,\s*(?:{_LID_ITEM_PAT}|{_SUB_ITEM_PAT}))*"

# Article number groups
# Range: "2 tot en met 5"
_ART_RANGE_PAT = rf"{_ART_NUM_PAT}\s+tot\s+en\s+met\s+{_ART_NUM_PAT}"
# Enumeration: "36e", "36e en 36f", "282a, 282b en 282c"
_ART_ENUM_PAT = (
    rf"{_ART_NUM_PAT}"
    rf"(?:\s*,\s*{_ART_NUM_PAT})*"
    rf"(?:\s+(?:en|of)\s+{_ART_NUM_PAT})?"
)
# Range takes priority over enum to avoid "2 tot" being parsed as just "2"
_ART_NUMS_PAT = rf"(?:{_ART_RANGE_PAT}|{_ART_ENUM_PAT})"

# Bare "artikel X" pattern (no law code) — for low-confidence fallback detection
_BARE_ARTIKEL_PAT = re.compile(
    rf"\b(?:artikel(?:en)?|art\.)\s+(?P<nums>{_ART_NUMS_PAT})\b",
    re.IGNORECASE,
)


def _parse_article_nums(raw: str) -> list[str]:
    """Split a raw article-number string into individual article numbers.

    Handles ranges (``2 tot en met 5`` → ``["2", "5"]``), enumerations
    (``36e en 36f`` → ``["36e", "36f"]``), and simple numbers.
    Ranges return only start/end — the caller decides whether to expand.
    """
    raw = raw.strip()
    range_m = re.match(
        rf"^({_ART_NUM_PAT})\s+tot\s+en\s+met\s+({_ART_NUM_PAT})$",
        raw,
        re.IGNORECASE,
    )
    if range_m:
        return [range_m.group(1), range_m.group(2)]
    parts = re.split(r"\s*,\s*|\s+(?:en|of)\s+", raw, flags=re.IGNORECASE)
    result = [
        p.strip()
        for p in parts
        if p.strip() and re.fullmatch(_ART_NUM_PAT, p.strip(), re.IGNORECASE)
    ]
    return result or [raw]


class DutchCitationExtractor:
    """Extract Dutch legal article citations from natural-language text.

    Patterns handled (``de`` prefix and ``art.`` abbreviation are optional):

    - ``artikel 36e Sr``                                — direct code
    - ``artikel 36e, derde lid, Sr``                    — with lid qualifier
    - ``art. 36e Sr``                                   — abbreviated keyword
    - ``artikelen 36e en 36f Sr``                       — enumeration
    - ``artikelen 2 tot en met 5 Sv``                   — range
    - ``artikel 3 van de Wwft``                         — "van de" + code
    - ``artikel 3 van het Wetboek van Strafvordering``  — "van het" + full name

    The law registry is injected at construction time.  Adding a code alias
    to the domain config automatically makes it detectable without touching
    this class.
    """

    def __init__(
        self,
        code_aliases: dict[str, str],
        name_aliases: dict[str, str] | None = None,
    ) -> None:
        self._code_map: dict[str, str] = {
            k.strip().upper(): v.strip() for k, v in code_aliases.items() if k and v
        }
        # Normalise whitespace in name keys so lookups are whitespace-agnostic.
        self._name_map: dict[str, str] = {
            re.sub(r"\s+", " ", k.strip().lower()): v.strip()
            for k, v in (name_aliases or {}).items()
            if k and v
        }
        self._pattern: re.Pattern[str] | None = (
            self._build_pattern() if (self._code_map or self._name_map) else None
        )

    def _build_pattern(self) -> re.Pattern[str]:
        law_alts: list[str] = []

        # "van de/het [full name]" — try names first (longer, more specific).
        if self._name_map:
            # Spaces in names become \s+ so multi-word names match even across
            # whitespace variants; re.escape handles parentheses and other specials.
            name_alt = "|".join(
                re.escape(n).replace(" ", r"\s+")
                for n in sorted(self._name_map, key=len, reverse=True)
            )
            law_alts.append(rf"van\s+(?:de\s+|het\s+)?(?P<law_name>{name_alt})")

        if self._code_map:
            code_alt = "|".join(
                re.escape(c) for c in sorted(self._code_map, key=len, reverse=True)
            )
            # "van de/het [short code]" — e.g. "van de Wwft"
            law_alts.append(rf"van\s+(?:de\s+|het\s+)?(?P<van_code>{code_alt})\b")
            # Direct code — the most common form
            law_alts.append(rf"(?P<law_code>{code_alt})\b")

        law_part = "|".join(law_alts)

        return re.compile(
            r"(?:de\s+)?"
            r"\b(?:artikel(?:en)?|art\.)\s+"
            rf"(?P<nums>{_ART_NUMS_PAT})"
            rf"(?P<qual>{_QUALIFIER_PAT})"
            r"\s*,?\s*"
            rf"(?:{law_part})",
            re.IGNORECASE,
        )

    def _resolve_law(self, match: re.Match[str]) -> tuple[str | None, str | None]:
        """Return ``(law_id, raw_text)`` from a match, or ``(None, None)``."""
        for group_name, lookup, normalise in (
            ("law_name", self._name_map, lambda s: re.sub(r"\s+", " ", s.lower())),
            ("van_code", self._code_map, str.upper),
            ("law_code", self._code_map, str.upper),
        ):
            try:
                raw = match.group(group_name)
            except IndexError:
                continue
            if raw:
                law_id = lookup.get(normalise(raw))
                if law_id:
                    return law_id, raw
        return None, None

    def extract(self, text: str) -> list[CitationHit]:
        """Return all detected Dutch article citations in *text*."""
        if not text or self._pattern is None:
            return []

        hits: list[CitationHit] = []
        seen: set[tuple[str | None, str | None, str]] = set()

        for match in self._pattern.finditer(text):
            law_id, _raw_code = self._resolve_law(match)
            if not law_id:
                continue

            nums_raw = (match.group("nums") or "").strip()
            article_numbers = _parse_article_nums(nums_raw)
            if not article_numbers:
                continue

            qual = (match.group("qual") or "").strip(", ") or None
            is_bwb = law_id.upper().startswith("BWBR")

            for art_num in article_numbers:
                dedup_key = (
                    law_id if is_bwb else None,
                    None if is_bwb else law_id,
                    art_num,
                )
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                hits.append(
                    CitationHit(
                        kind="article",
                        bwb_id=law_id if is_bwb else None,
                        celex=None if is_bwb else law_id,
                        article_number=art_num,
                        qualifier=qual,
                        confidence=0.95,
                        raw_match=match.group(0),
                        snippet=make_snippet(text, match.span()),
                    )
                )

        return hits

    def extract_bare(
        self,
        text: str,
        *,
        exclude_spans: list[tuple[int, int]] | None = None,
        confidence: float = 0.35,
    ) -> list[CitationHit]:
        """Return bare ``artikel X`` references not already covered by coded hits.

        These carry no ``bwb_id`` / ``celex`` and a low confidence score.
        They are useful for presence detection but should not be used to create
        stub nodes or edges without additional resolution.
        """
        if not text:
            return []
        covered = set(exclude_spans or [])
        hits: list[CitationHit] = []
        seen_nums: set[str] = set()
        for match in _BARE_ARTIKEL_PAT.finditer(text):
            span = match.span()
            if any(not (span[1] <= s or span[0] >= e) for s, e in covered):
                continue
            nums_raw = (match.group("nums") or "").strip()
            for art_num in _parse_article_nums(nums_raw):
                if art_num in seen_nums:
                    continue
                seen_nums.add(art_num)
                hits.append(
                    CitationHit(
                        kind="article",
                        article_number=art_num,
                        confidence=confidence,
                        raw_match=match.group(0),
                        snippet=make_snippet(text, span),
                    )
                )
        return hits
