"""Detect references between BWB articles within article texts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

_LID_QUALIFIER = r"(?:(?:eerste|tweede|derde|laatste|volgende)\s+lid[,\s]*)?"
_ARTICLE_NUMBER_PATTERN = re.compile(r"\d+[a-zA-Z]{0,4}(?:\.\d+)?")
_ARTICLE_REFERENCE_PATTERN = re.compile(
    (
        r"\b(?:de\s+)?(?:artikel(?:en)?|art(?:ikel)?\.?)\s+"
        r"(?P<numbers>\d+[a-zA-Z]{0,4}(?:\.\d+)?(?:\s*(?:tot\s+en\s+met|tot|en|,|&|-)\s*"
        + _LID_QUALIFIER
        + r"\d+[a-zA-Z]{0,4}(?:\.\d+)?)*)"
    ),
    re.IGNORECASE,
)

# Matches "art. 126aa Sv" or "artikel 3.01 Awb" — short mixed-case abbreviation after number.
# Must start uppercase, be 2-5 chars, and not be a common Dutch word (van/de/het/lid/een).
_CROSS_LAW_CODE_PATTERN = re.compile(
    r"\bart(?:ikel)?\.?\s+"
    r"(?P<number>\d+[a-zA-Z]{0,4}(?:\.\d+)?)"
    r"\s+(?P<code>(?!(?:van|de|het|lid|een|als|van)\b)[A-Z][A-Za-z]{1,4})\b(?!\s*\d)",
)

# Matches "art. 3.01 van de Wegenverkeerswet 1994" or "artikel 51 van het Wetboek van Strafrecht".
# Captures everything after "van de/het" up to sentence-ending punctuation or end-of-string.
_CROSS_LAW_VAN_DE_PATTERN = re.compile(
    r"\bart(?:ikel)?\.?\s+"
    r"(?P<number>\d+[a-zA-Z]{0,4}(?:\.\d+)?)"
    r"\s+van\s+(?:de\s+|het\s+)"
    r"(?P<law>[A-Z][^,;.\n\d]{2,80}?)(?=\s*[\d,;.]|\s*$)",
    re.IGNORECASE,
)

_DEFAULT_CONFIDENCE = 0.95
_RANGE_CONFIDENCE = 0.8
_CROSS_LAW_CONFIDENCE = 0.9

# Dutch laws rarely exceed ~1000 articles; anything larger is almost certainly a fine,
# year, or other numeric literal that happens to follow "artikel".
_MAX_ARTICLE_NUMBER = 1999
# Prevent generating thousands of intermediate range hits from bogus ranges.
_MAX_RANGE_SPAN = 200


@dataclass
class ArticleCitationHit:
    """A detected reference from one BWB article to another."""

    start: int
    end: int
    text: str
    bwb_id: str | None
    article_number: str
    confidence: float
    cross_law: bool = field(default=False)


def detect_bwb_article_citations(
    text: str,
    bwb_id: str,
    config: dict[str, Any] | None = None,
) -> list[ArticleCitationHit]:
    """Return citations to other articles that appear in the provided text.

    Detects both within-document references ("de artikelen 105, 174...") and
    explicit cross-law references ("art. 126aa Sv", "art. 3.01 van de Awb").
    Cross-law hits carry the resolved bwb_id when the alias is known, or
    ``bwb_id=None`` when the law name cannot be resolved.
    """
    if not text or not bwb_id:
        return []

    conf_map = config or {}
    default_confidence = _coerce_confidence(
        conf_map.get("confidence_default", _DEFAULT_CONFIDENCE),
        _DEFAULT_CONFIDENCE,
    )
    range_confidence = _coerce_confidence(
        conf_map.get("confidence_range", _RANGE_CONFIDENCE),
        _RANGE_CONFIDENCE,
    )
    code_aliases: dict[str, str] = conf_map.get("code_aliases") or {}
    instrument_aliases: dict[str, str] = conf_map.get("instrument_aliases") or {}

    hits: list[ArticleCitationHit] = []
    seen: set[tuple[int, int, str]] = set()

    # --- explicit cross-law references first (higher specificity) ---
    # "art. 126aa Sv", "artikel 3.01 AWB"
    for match in _CROSS_LAW_CODE_PATTERN.finditer(text):
        resolved = code_aliases.get(match.group("code"))
        _process_cross_law_match(match, resolved, hits, seen)

    # "art. 3.01 van de Wegenverkeerswet 1994"
    for match in _CROSS_LAW_VAN_DE_PATTERN.finditer(text):
        resolved = _resolve_law_name_by_prefix(
            match.group("law").strip(), instrument_aliases
        )
        _process_cross_law_match(match, resolved, hits, seen)

    # --- within-document enumeration references ---
    for match in _ARTICLE_REFERENCE_PATTERN.finditer(text):
        _process_enumeration_block(
            match=match,
            text=text,
            bwb_id=bwb_id,
            default_confidence=default_confidence,
            range_confidence=range_confidence,
            hits=hits,
            seen=seen,
        )

    hits.sort(key=lambda hit: (hit.start, hit.article_number))
    return hits


def _process_cross_law_match(
    match: re.Match[str],
    resolved: str | None,
    hits: list[ArticleCitationHit],
    seen: set[tuple[int, int, str]],
) -> None:
    """Add a cross-law citation hit to *hits* unless already in *seen*."""
    article_number = match.group("number")
    int_val = _parse_article_int(article_number)
    if int_val is not None and int_val > _MAX_ARTICLE_NUMBER:
        return
    hit = ArticleCitationHit(
        start=match.start("number"),
        end=match.end("number"),
        text=article_number,
        bwb_id=resolved,
        article_number=article_number,
        confidence=_CROSS_LAW_CONFIDENCE,
        cross_law=True,
    )
    key = (hit.start, hit.end, article_number.lower())
    if key not in seen:
        seen.add(key)
        hits.append(hit)


def _process_enumeration_block(
    *,
    match: re.Match[str],
    text: str,
    bwb_id: str,
    default_confidence: float,
    range_confidence: float,
    hits: list[ArticleCitationHit],
    seen: set[tuple[int, int, str]],
) -> None:
    """Process one enumeration-reference block and append hits to *hits*."""
    block_start = match.start("numbers")
    block_end = match.end("numbers")
    block_text = text[block_start:block_end]
    if not block_text:
        return

    number_matches = list(_ARTICLE_NUMBER_PATTERN.finditer(block_text))
    if not number_matches:
        return

    for number_match in number_matches:
        article_number = number_match.group(0).strip()
        if not article_number:
            continue
        int_val = _parse_article_int(article_number)
        if int_val is not None and int_val > _MAX_ARTICLE_NUMBER:
            continue
        start = block_start + number_match.start()
        end = block_start + number_match.end()
        hit = ArticleCitationHit(
            start=start,
            end=end,
            text=text[start:end],
            bwb_id=bwb_id,
            article_number=article_number,
            confidence=default_confidence,
        )
        key = (hit.start, hit.end, article_number.lower())
        if key in seen:
            continue
        seen.add(key)
        hits.append(hit)

    for range_hit in _collect_range_hits(
        full_text=text,
        block_text=block_text,
        block_start=block_start,
        number_matches=number_matches,
        bwb_id=bwb_id,
        confidence=range_confidence,
    ):
        key = (range_hit.start, range_hit.end, range_hit.article_number.lower())
        if key in seen:
            continue
        seen.add(key)
        hits.append(range_hit)


def _resolve_law_name_by_prefix(
    name: str, instrument_aliases: dict[str, str]
) -> str | None:
    """Match a law name string against instrument_aliases, longest match first."""
    name_lower = name.lower().strip()
    best: str | None = None
    best_len = 0
    for alias, bwb_id in instrument_aliases.items():
        alias_lower = alias.lower()
        if name_lower.startswith(alias_lower) and len(alias_lower) > best_len:
            best = bwb_id
            best_len = len(alias_lower)
    return best


def _collect_range_hits(
    *,
    full_text: str,
    block_text: str,
    block_start: int,
    number_matches: list[re.Match[str]],
    bwb_id: str,
    confidence: float,
) -> list[ArticleCitationHit]:
    hits: list[ArticleCitationHit] = []
    block_end = block_start + len(block_text)

    for index in range(len(number_matches) - 1):
        current = number_matches[index]
        nxt = number_matches[index + 1]
        connector = block_text[current.end() : nxt.start()]
        if "tot" not in connector.lower():
            continue

        start_value = _parse_article_int(current.group(0))
        end_value = _parse_article_int(nxt.group(0))
        if start_value is None or end_value is None:
            continue

        lower = min(start_value, end_value)
        upper = max(start_value, end_value)
        if upper - lower <= 1:
            continue
        if upper > _MAX_ARTICLE_NUMBER or upper - lower > _MAX_RANGE_SPAN:
            continue

        span_text = full_text[block_start:block_end].strip()
        for intermediate in range(lower + 1, upper):
            hits.append(
                ArticleCitationHit(
                    start=block_start,
                    end=block_end,
                    text=span_text,
                    bwb_id=bwb_id,
                    article_number=str(intermediate),
                    confidence=confidence,
                )
            )

    return hits


def _parse_article_int(value: str) -> int | None:
    match = re.match(r"\d+", value)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        logger.debug("Could not parse article number integer from %r", value)
        return None


def _coerce_confidence(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
