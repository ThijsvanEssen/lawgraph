"""What the ECHR found per article, from the ``conclusion`` of a HUDOC record (pure functions,
no I/O).

HUDOC writes the conclusion of a judgment as its findings separated by ``;`` (also inside the
parentheses that detail each): "Violation of Article 8 - Right to respect for private and
family life (Article 8-1 - Respect for family life);Non-pecuniary damage - award (Article
41 …)", in French "Violation de l'article 5 - Droit à la liberté et à la sûreté (…)". A
finding on an article is ``schending`` ("Violation of", "Violation de") or ``geen
schending`` ("No violation of", "Non-violation de"); an article taken together with another
is written ``13+8-1`` (Article 13 with Article 8 § 1); an article of a protocol "Article 1 of
Protocol No. 1"; the aspect follows as "(Substantive aspect)" or "(Procedural aspect)". The
other findings (admissibility, just satisfaction) are no finding on an article.
"""

from __future__ import annotations

import re
from typing import Any, Final, Literal

EchrFinding = Literal["schending", "geen schending"]
EchrAspect = Literal["materieel", "procedureel"]
VIOLATION: Final[EchrFinding] = "schending"
NO_VIOLATION: Final[EchrFinding] = "geen schending"

_FINDING = re.compile(
    r"^(?P<finding>no\s+violation\s+of|non-violation\s+de|violation\s+of|violation\s+de)"
    r"\s+(?:article|l['’]article|art\.)\s+(?P<provision>[0-9][0-9a-z+\-]*)"
    r"(?:\s+(?:of\s+protocol\s+no\.?|du\s+protocole\s+n[°o]\.?)\s*(?P<protocol>\d+))?",
    re.IGNORECASE,
)
_ASPECTS: dict[str, EchrAspect] = {
    "substantive aspect": "materieel",
    "volet matériel": "materieel",
    "procedural aspect": "procedureel",
    "volet procédural": "procedureel",
}


def _segments(conclusion: str) -> list[str]:
    """The findings of *conclusion*: its parts between the ``;`` outside parentheses."""
    parts, depth, begin = [], 0, 0
    for n, char in enumerate(conclusion):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            parts.append(conclusion[begin:n])
            begin = n + 1
    parts.append(conclusion[begin:])
    return [part.strip() for part in parts if part.strip()]


def echr_findings(conclusion: str | None) -> list[dict[str, Any]]:
    """Per finding on an article of *conclusion*, in its order and each once: ``article``
    (``8``), ``protocol`` (``1`` for Article 1 of Protocol No. 1, else null),
    ``combined_with`` (``8`` of ``13+8-1``, else null), ``finding`` (``schending``, ``geen
    schending``), ``aspect`` (``materieel``, ``procedureel`` or null) and ``text`` (the
    finding as HUDOC writes it)."""
    found: list[dict[str, Any]] = []
    for segment in _segments(conclusion or ""):
        match = _FINDING.match(segment)
        if match is None:
            continue
        provision = match["provision"]
        article = re.match(r"\d+", provision)
        combined = provision.split("+", 1)[1] if "+" in provision else None
        combined_article = re.match(r"\d+", combined or "")
        lowered = segment.lower()
        finding = {
            "article": article[0] if article else provision,
            "protocol": match["protocol"],
            "combined_with": (
                combined_article[0]
                if combined_article and article and combined_article[0] != article[0]
                else None
            ),
            "finding": (
                NO_VIOLATION if match["finding"].lower().startswith("no") else VIOLATION
            ),
            "aspect": next(
                (aspect for words, aspect in _ASPECTS.items() if words in lowered), None
            ),
            "text": segment,
        }
        if not any(
            {k: v for k, v in f.items() if k != "text"}
            == {k: v for k, v in finding.items() if k != "text"}
            for f in found
        ):
            found.append(finding)
    return found


def echr_outcome_props(conclusion: str | None) -> dict[str, Any]:
    """``echr_findings`` of a judgment with this *conclusion*, and its ``outcome``: of its
    findings on articles ``schending`` when one is, else ``geen schending``, with the text
    of the first such finding as ``outcome_text``; null without findings on articles."""
    findings = echr_findings(conclusion)
    first = next((f for f in findings if f["finding"] == VIOLATION), None) or next(
        iter(findings), None
    )
    return {
        "echr_findings": findings or None,
        "outcome": first["finding"] if first else None,
        "outcome_text": first["text"] if first else None,
    }
