"""Shared citation-detection primitives used across semantic pipelines.

This module provides a single source of truth for the ``CitationHit`` dataclass
and the helper utilities that are otherwise copy-pasted across
``eu_articles.py``, ``tk_articles.py``, and ``rechtspraak_articles.py``.

Public API
----------
CitationHit
    Unified dataclass for any detected legal citation.
ArticleKind
    ``Literal["article", "instrument"]`` discriminant.
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


def format_celex(
    kind: Literal["directive", "regulation"],
    year: str,
    number: str,
) -> str:
    """Render a numeric CELEX identifier.

    Example: ``format_celex("directive", "2010", "64")`` → ``"32010L0064"``
    """
    letter = "L" if kind == "directive" else "R"
    padded = 0
    try:
        padded = int(number)
    except ValueError:
        pass
    return f"3{year}{letter}{padded:04d}"


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
