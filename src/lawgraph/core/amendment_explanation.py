"""What an amendment is for, as its Toelichting opens: the line a row shows under it.

An amendment of the Tweede Kamer has one form: "Amendement van het lid … De ondergetekende
stelt het volgende amendement voor: I In artikel 21 … Toelichting Dit amendement regelt dat
…". Its explanation is the first paragraph of the section headed "Toelichting", up to
``EXPLANATION_CHARS`` characters: whole sentences as long as they fit, else cut at a word.
Of 2,320 amendments with a Toelichting on the small database 2,298 say "stelt het volgende
(sub)amendement voor", the others open with "(Gewijzigd) (sub)amendement van het lid"; no
other paper does either, so a paper without the form has none.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from lawgraph.core.display import shorten

# The characters of an explanation at most.
EXPLANATION_CHARS = 400

_FORM = re.compile(
    r"stel(?:t|len)\s+(?:het|de)\s+volgende\s+(?:sub)?amendement(?:en)?\s+voor"
    r"|^\s*(?:(?:nader\s+)?gewijzigd\s+)?(?:sub)?amendement\s+van\s+(?:het\s+lid|de\s+leden)\b",
    re.IGNORECASE | re.MULTILINE,
)
_HEADING = "toelichting"
# The end of a sentence: a full stop, question or exclamation mark before a space.
_SENTENCE_END = re.compile(r"[.?!](?=\s)")


def read_explanation(
    text: str | None, sections: Sequence[Mapping[str, Any]] | None
) -> str | None:
    """The opening of the Toelichting of the amendment *text* with these *sections* (each
    ``{heading, char_start, char_end}``); None for a paper without the form of an amendment
    or without a Toelichting."""
    if not text or not sections:
        return None
    section = next(
        (
            s
            for s in sections
            if str(s.get("heading") or "").strip(" .:").lower() == _HEADING
        ),
        None,
    )
    if section is None:
        return None
    start, end = int(section["char_start"]), int(section["char_end"])
    if not _FORM.search(text[:start]):
        return None
    lines = [line.strip() for line in text[start:end].splitlines()]
    if lines and lines[0].strip(" .:").lower() == _HEADING:
        lines = lines[1:]
    first = next((line for line in lines if line), None)
    return _cut(first) if first else None


def _cut(paragraph: str) -> str:
    """*paragraph* whole when it fits; else its sentences that fit, or its words with an
    ellipsis when not even the first does."""
    if len(paragraph) <= EXPLANATION_CHARS:
        return paragraph
    ends = [m.end() for m in _SENTENCE_END.finditer(paragraph, 0, EXPLANATION_CHARS)]
    if ends:
        return paragraph[: ends[-1]]
    return shorten(paragraph, EXPLANATION_CHARS)
