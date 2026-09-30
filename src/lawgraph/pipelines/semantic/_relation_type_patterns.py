"""Deterministic semantic classification of article-to-article references.

Pure functions — no store access — so the pattern logic is unit-testable.
Given an article's full text and the character span of a detected citation,
``classify_citation_context`` assigns one of the seven semantic relationship
types based on Dutch legal drafting patterns around the citation.

A type rests on a trigger phrase in the sentence of the reference, nothing more, so its
confidence is the share of such classifications that a hand check found right
(``CONFIDENCE``), not a strength of signal: a phrase directly before the reference ("in
afwijking van artikel 8") is right far more often than one elsewhere in the sentence, and
some phrases are right far more often than others. The explanation names the phrase and
where it stood. Per-pattern values are overridable via LAWGRAPH_CONFIDENCE_<PATTERN> env
vars.
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
from lawgraph.config.settings import confidence_override

# How far around the citation we look for trigger phrases.
_ADJACENT_CHARS = 40
_WINDOW_CHARS = 120

ADJACENT = "adjacent"
WINDOW = "window"

# The share of classifications a hand check found right, per pattern and where its phrase
# stood: 10 random references per cell of lawgraph_small (2026-09-29), with the audit's 12
# per type where it covered the cell. A plain reference (``cross_reference_fallback``) is
# right when no narrower type fits: 6 in 10.
CONFIDENCE: dict[tuple[str, str], float] = {
    ("limiting_exception", ADJACENT): 0.85,
    ("limiting_exception", WINDOW): 0.65,
    ("definitional_reference", ADJACENT): 0.85,
    ("definitional_reference", WINDOW): 0.25,
    ("definitional_reference_inverted", ADJACENT): 0.9,
    ("conditional_requirement", ADJACENT): 0.8,
    ("conditional_requirement", WINDOW): 0.3,
    ("prerequisite_procedure", ADJACENT): 0.6,
    ("prerequisite_procedure", WINDOW): 0.3,
    ("scope_limitation", ADJACENT): 0.8,
    ("scope_limitation", WINDOW): 0.8,
    ("delegated_discretion", ADJACENT): 0.3,
    ("delegated_discretion", WINDOW): 0.3,
    ("cross_reference_explicit", ADJACENT): 0.5,
    ("cross_reference_explicit", WINDOW): 0.5,
}
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
    # "als bedoeld in artikel X", "in de zin van artikel X", "genoemd in artikel X"
    (
        "definitional_reference",
        SEMANTIC_TYPE_DEFINITIONAL_REFERENCE,
        re.compile(
            r"\b(als bedoeld in|bedoeld in|in de zin van|als omschreven in"
            r"|zoals gedefinieerd in|wordt verstaan onder|vermeld in|genoemd in"
            r"|opgenomen in)\b",
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
    # "aangewezen krachtens artikel X", "zijn niet van toepassing op"
    (
        "scope_limitation",
        SEMANTIC_TYPE_SCOPE_LIMITATION,
        re.compile(
            r"\b(aangewezen (op grond van|krachtens)|van toepassing op)\b",
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


# Where a sentence ends: a full stop before a capital (not "art. 5", not "onder a."), a
# semicolon (the items of an enumeration), a line break (a lid).
_SENTENCE_END_RE = re.compile(r"\.\s+(?=[A-Z])|;|\n")


def _sentence(text: str, start: int, end: int) -> tuple[int, int]:
    """The bounds of the sentence around ``text[start:end]``: a trigger phrase in
    another sentence says nothing about this reference."""
    begin = 0
    # up to the first character of the reference: a capital there ends the sentence before
    for match in _SENTENCE_END_RE.finditer(text, 0, start + 1):
        begin = min(match.end(), start)
    after = _SENTENCE_END_RE.search(text, end)
    return begin, after.start() if after else len(text)


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

    first, last = _sentence(text, start, end)

    # 1. Strongest signal: trigger phrase directly before the citation
    #    ("als bedoeld in artikel 5" — the trigger abuts the span), or the inverted
    #    form of a definition around it ("de in artikel 5 bedoelde vergunning").
    adjacent = text[max(first, start - _ADJACENT_CHARS) : start]
    inverted = _inverted_definition(text, start, end, last)
    if inverted is not None:
        return _classified(
            "definitional_reference_inverted",
            SEMANTIC_TYPE_DEFINITIONAL_REFERENCE,
            ADJACENT,
            f"Patroon 'in … {inverted}' om de verwijzing",
        )
    hit = _match_in(adjacent)
    if hit is not None:
        name, semantic_type, match = hit
        return _classified(
            name,
            semantic_type,
            ADJACENT,
            f"Patroon '{match.group(0)}' direct vóór de verwijzing",
        )

    # 2. Weaker signal: trigger phrase elsewhere in the sentence around it.
    window = text[max(first, start - _WINDOW_CHARS) : min(last, end + _WINDOW_CHARS)]
    hit = _match_in(window)
    if hit is not None:
        name, semantic_type, match = hit
        return _classified(
            name,
            semantic_type,
            WINDOW,
            f"Patroon '{match.group(0)}' elders in de zin van de verwijzing",
        )

    # 3. Fallback: a plain reference without constraining language.
    return SemanticClassification(
        semantic_type=SEMANTIC_TYPE_CROSS_REFERENCE,
        pattern="cross_reference_fallback",
        confidence=confidence_override("cross_reference_fallback", CONFIDENCE_FALLBACK),
        explanation="Verwijzing zonder herkend juridisch beperkend patroon",
    )


# "de in [artikel 5] bedoelde vergunning": "in" right before the reference, the participle
# right after it (a lid or onderdeel of the reference may stand between).
_IN_BEFORE_RE = re.compile(r"\bin\s+(?:de\s+|het\s+)?$", re.IGNORECASE)
_PARTICIPLE_AFTER_RE = re.compile(
    r"^[^.;:]{0,30}?\b(bedoelde|genoemde|omschreven|vermelde|opgenomen)\b",
    re.IGNORECASE,
)


def _inverted_definition(text: str, start: int, end: int, last: int) -> str | None:
    """The participle of "in <reference> bedoelde", or ``None``."""
    if not _IN_BEFORE_RE.search(text[max(0, start - 12) : start]):
        return None
    after = _PARTICIPLE_AFTER_RE.match(text[end:last])
    return after.group(1) if after else None


def _classified(
    name: str, semantic_type: str, where: str, explanation: str
) -> SemanticClassification:
    pattern = f"{name}_{where}"
    return SemanticClassification(
        semantic_type=semantic_type,
        pattern=pattern,
        confidence=confidence_override(pattern, CONFIDENCE[(name, where)]),
        explanation=explanation,
    )
