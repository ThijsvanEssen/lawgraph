"""Detect references between BWB articles within article texts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_ARTICLE_REFERENCE_PATTERN = re.compile(
    (
        r"\b(?:de\s+)?(?:artikel(?:en)?|art(?:ikel)?\.?)\s+"
        r"(?P<numbers>\d+[a-zA-Z]{0,4}(?:\s*(?:tot\s+en\s+met|tot|en|,|&|-)\s*"
        r"\d+[a-zA-Z]{0,4})*)"
    ),
    re.IGNORECASE,
)
_ARTICLE_NUMBER_PATTERN = re.compile(r"\d+[a-zA-Z]{0,4}")

_DEFAULT_CONFIDENCE = 0.95
_RANGE_CONFIDENCE = 0.8


@dataclass
class ArticleCitationHit:
    """A detected reference from one BWB article to another."""

    start: int
    end: int
    text: str
    bwb_id: str
    article_number: str
    confidence: float


def detect_bwb_article_citations(
    text: str,
    bwb_id: str,
    config: dict[str, Any] | None = None,
) -> list[ArticleCitationHit]:
    """Return citations to other articles that appear in the provided text."""
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

    hits: list[ArticleCitationHit] = []
    seen: set[tuple[int, int, str]] = set()

    for match in _ARTICLE_REFERENCE_PATTERN.finditer(text):
        block_start = match.start("numbers")
        block_end = match.end("numbers")
        block_text = text[block_start:block_end]
        if not block_text:
            continue

        number_matches = list(_ARTICLE_NUMBER_PATTERN.finditer(block_text))
        if not number_matches:
            continue

        for number_match in number_matches:
            article_number = number_match.group(0).strip()
            if not article_number:
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

    hits.sort(key=lambda hit: (hit.start, hit.article_number))
    return hits


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
        return None


def _coerce_confidence(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
