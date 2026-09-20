"""Deterministic semantic classification of article-to-article references.

Pure functions — no store access — so the pattern logic is unit-testable.
Given an article's full text and the character span of a detected citation,
``classify_citation_context`` assigns one of the seven semantic relationship
types based on Dutch legal drafting patterns around the citation.

Confidence convention:
  * 0.9 — trigger phrase directly adjacent to the citation (strong signal)
  * 0.7 — trigger phrase within the context window (weaker signal)
  * 0.5 — no trigger matched; classified as generic cross_reference
Per-pattern values are overridable via LAWGRAPH_CONFIDENCE_<PATTERN> env vars.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lawgraph.config.constants import (
    SEMANTIC_TYPE_CONDITIONAL_REQUIREMENT,
    SEMANTIC_TYPE_CROSS_REFERENCE,
    SEMANTIC_TYPE_DEFINITIONAL_REFERENCE,
    SEMANTIC_TYPE_DELEGATED_DISCRETION,
    SEMANTIC_TYPE_LIMITING_EXCEPTION,
    SEMANTIC_TYPE_PREREQUISITE_PROCEDURE,
    SEMANTIC_TYPE_SCOPE_LIMITATION,
)
from lawgraph.config.settings import get_confidence_override

# How far around the citation we look for trigger phrases.
_ADJACENT_CHARS = 40
_WINDOW_CHARS = 120

CONFIDENCE_ADJACENT = 0.9
CONFIDENCE_WINDOW = 0.7
CONFIDENCE_FALLBACK = 0.5


@dataclass(frozen=True)
class SemanticClassification:
    """Result of classifying one citation span."""

    semantic_type: str
    pattern: str  # name of the matched pattern (for auditing/retraining)
    confidence: float
    explanation: str  # human-readable Dutch justification


# Ordered pattern table: (pattern_name, semantic_type, compiled_regex).
# Order matters — the first match wins, so the more specific / more
# constraining legal patterns come before the generic ones.
_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    # "in afwijking van artikel X", "onverminderd artikel X", ...
    (
        "limiting_exception",
        SEMANTIC_TYPE_LIMITING_EXCEPTION,
        re.compile(
            r"\b(in afwijking van|onverminderd|behoudens|met uitzondering van"
            r"|niettegenstaande|tenzij)\b",
            re.IGNORECASE,
        ),
    ),
    # "als bedoeld in artikel X", "in de zin van artikel X"
    (
        "definitional_reference",
        SEMANTIC_TYPE_DEFINITIONAL_REFERENCE,
        re.compile(
            r"\b(als bedoeld in|bedoeld in|in de zin van|als omschreven in"
            r"|zoals gedefinieerd in|wordt verstaan onder)\b",
            re.IGNORECASE,
        ),
    ),
    # "alleen indien ... artikel X", "mits ... artikel X"
    (
        "conditional_requirement",
        SEMANTIC_TYPE_CONDITIONAL_REQUIREMENT,
        re.compile(
            r"\b(alleen indien|slechts indien|mits|indien wordt voldaan aan"
            r"|indien is voldaan aan|onder de voorwaarden? van|voor zover)\b",
            re.IGNORECASE,
        ),
    ),
    # "met inachtneming van artikel X", "overeenkomstig de procedure van artikel X"
    (
        "prerequisite_procedure",
        SEMANTIC_TYPE_PREREQUISITE_PROCEDURE,
        re.compile(
            r"\b(met inachtneming van|na toepassing van|overeenkomstig( de procedure"
            r"( van)?)?|volgens de procedure van|nadat .{0,60}? is vastgesteld)\b",
            re.IGNORECASE,
        ),
    ),
    # "vermeld in artikel/bijlage X", "aangewezen krachtens artikel X"
    (
        "scope_limitation",
        SEMANTIC_TYPE_SCOPE_LIMITATION,
        re.compile(
            r"\b(vermeld in|genoemd in|opgenomen in|aangewezen (op grond van|krachtens)"
            r"|van toepassing op)\b",
            re.IGNORECASE,
        ),
    ),
    # "Onze Minister kan ... aanwijzen", "bij ministeriële regeling"
    (
        "delegated_discretion",
        SEMANTIC_TYPE_DELEGATED_DISCRETION,
        re.compile(
            r"\b(bij ministeri[eë]le regeling|bij of krachtens|onze minister kan"
            r"|kan bij algemene maatregel van bestuur"
            r"|kunnen (regels|categorie[eë]n) worden (gesteld|aangewezen)"
            r"|kan .{0,60}? (worden )?(aangewezen|aanwijzen))\b",
            re.IGNORECASE,
        ),
    ),
    # explicit "see also" style references
    (
        "cross_reference_explicit",
        SEMANTIC_TYPE_CROSS_REFERENCE,
        re.compile(r"\b(zie ook|vergelijk|zie)\b", re.IGNORECASE),
    ),
)


def _match_in(
    segment: str,
) -> tuple[str, str, re.Match[str]] | None:
    """Return the first (pattern_name, semantic_type, match) in *segment*."""
    for name, semantic_type, regex in _PATTERNS:
        match = regex.search(segment)
        if match is not None:
            return name, semantic_type, match
    return None


def _confidence(pattern: str, default: float) -> float:
    return get_confidence_override(pattern, default)


def classify_citation_context(
    text: str,
    start: int | None,
    end: int | None,
) -> SemanticClassification | None:
    """Classify a citation by the legal drafting patterns surrounding it.

    Returns None when the span is unusable (missing or out of bounds) —
    callers should leave such edges unclassified rather than guessing.
    """
    if not text or start is None or end is None:
        return None
    if start < 0 or end > len(text) or start >= end:
        return None

    # 1. Strongest signal: trigger phrase directly before the citation
    #    ("als bedoeld in artikel 5" — the trigger abuts the span).
    adjacent = text[max(0, start - _ADJACENT_CHARS) : start]
    hit = _match_in(adjacent)
    if hit is not None:
        name, semantic_type, match = hit
        return SemanticClassification(
            semantic_type=semantic_type,
            pattern=name,
            confidence=_confidence(name, CONFIDENCE_ADJACENT),
            explanation=f"Patroon '{match.group(0)}' direct vóór de verwijzing",
        )

    # 2. Weaker signal: trigger phrase elsewhere in the surrounding window.
    window = text[max(0, start - _WINDOW_CHARS) : min(len(text), end + _WINDOW_CHARS)]
    hit = _match_in(window)
    if hit is not None:
        name, semantic_type, match = hit
        return SemanticClassification(
            semantic_type=semantic_type,
            pattern=name,
            confidence=_confidence(name, CONFIDENCE_WINDOW),
            explanation=f"Patroon '{match.group(0)}' nabij de verwijzing",
        )

    # 3. Fallback: a plain reference without constraining language.
    return SemanticClassification(
        semantic_type=SEMANTIC_TYPE_CROSS_REFERENCE,
        pattern="cross_reference_fallback",
        confidence=_confidence("cross_reference_fallback", CONFIDENCE_FALLBACK),
        explanation="Verwijzing zonder herkend juridisch beperkend patroon",
    )
