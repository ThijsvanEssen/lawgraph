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


def _scope_type(text: str, start: int, end: int) -> str:
    """Discretionary when ministerial-designation language is near ``text[start:end]``."""
    window = text[max(0, start - _SCOPE_WINDOW_CHARS) : end + _SCOPE_WINDOW_CHARS]
    if _DISCRETIONARY_RE.search(window):
        return SCOPE_TYPE_DISCRETIONARY
    return SCOPE_TYPE_FIXED


# The articles an annex belongs to, after its name: "Bevoegdheidsregeling
# bestuursrechtspraak (artikelen 8:5, 8:6, 8:7, 8:105 en 8:106)".
_TRAILING_PARENTHESES = re.compile(r"\s*\([^()]*\)\s*$")
_MIN_NAME_WORDS = 2


def annex_name(title: str | None) -> str | None:
    """The name an article cites an annex by: its title without the parentheses at its end.

    None for a name of one word ("Tabel"), which is no name to find in a text."""
    name = _TRAILING_PARENTHESES.sub("", title or "").strip()
    return name if len(name.split()) >= _MIN_NAME_WORDS else None


def detect_annex_name(text: str, name: str) -> AnnexReferenceHit | None:
    """The first place *text* names the annex called *name* ("de bij deze wet behorende
    Bevoegdheidsregeling bestuursrechtspraak"), as a whole-word match; None when it does
    not."""
    match = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text)
    if match is None:
        return None
    return AnnexReferenceHit(
        label=None,
        start=match.start(),
        end=match.end(),
        text=match.group(0),
        scope_type=_scope_type(text, match.start(), match.end()),
    )


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
        hits.append(
            AnnexReferenceHit(
                label=label,
                start=match.start(),
                end=match.end(),
                text=match.group(0),
                scope_type=_scope_type(text, match.start(), match.end()),
            )
        )
    return hits
