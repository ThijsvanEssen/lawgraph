"""Detection of annex references inside Dutch article text.

Pure functions — no store access — so the pattern logic is unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lawgraph.config.constants import SCOPE_TYPE_DISCRETIONARY, SCOPE_TYPE_FIXED

# Dutch source wording: "bijlage I", "bijlage 2", "de bijlage", "bijlagen I en II".
# The label group accepts Roman numerals, digits, or a single capital letter.
_ANNEX_RE = re.compile(
    r"\bbijlagen?\b(?:\s+(?P<label>[0-9]+[a-z]?|[IVXLCDM]+\b|[A-Z]\b))?",
    re.IGNORECASE,
)

# Discretionary-scope signals: the list can be changed by ministerial
# designation rather than by formal amendment of the law itself.
_DISCRETIONARY_RE = re.compile(
    r"\b(bij ministeri[eë]le regeling|onze minister kan|kan worden gewijzigd"
    r"|kunnen .{0,40}? worden (aangewezen|toegevoegd)"
    r"|kan .{0,40}? (worden )?(aangewezen|aanwijzen|toevoegen|toegevoegd))\b",
    re.IGNORECASE,
)

_SCOPE_WINDOW_CHARS = 160


@dataclass(frozen=True)
class AnnexReferenceHit:
    """One annex reference detected in article text."""

    label: str | None  # "I", "2", "A" — None for an unlabelled "de bijlage"
    start: int
    end: int
    text: str
    scope_type: str  # SCOPE_TYPE_FIXED | SCOPE_TYPE_DISCRETIONARY


def _normalize_label(raw: str | None) -> str | None:
    if raw is None:
        return None
    label = raw.strip()
    if not label:
        return None
    # Roman numerals and letters are conventionally upper-case in citations.
    if not label.isdigit():
        return label.upper()
    return label


def detect_annex_references(text: str) -> list[AnnexReferenceHit]:
    """Return all annex references in *text*, deduplicated by label.

    A reference is marked discretionary when ministerial-designation
    language appears within the surrounding window — meaning the annex's
    scope can be expanded without formal amendment.
    """
    if not text:
        return []

    hits: list[AnnexReferenceHit] = []
    seen_labels: set[str | None] = set()
    for match in _ANNEX_RE.finditer(text):
        label = _normalize_label(match.group("label"))
        if label in seen_labels:
            continue
        seen_labels.add(label)

        window = text[
            max(0, match.start() - _SCOPE_WINDOW_CHARS) : match.end()
            + _SCOPE_WINDOW_CHARS
        ]
        scope_type = (
            SCOPE_TYPE_DISCRETIONARY
            if _DISCRETIONARY_RE.search(window)
            else SCOPE_TYPE_FIXED
        )
        hits.append(
            AnnexReferenceHit(
                label=label,
                start=match.start(),
                end=match.end(),
                text=match.group(0),
                scope_type=scope_type,
            )
        )
    return hits
