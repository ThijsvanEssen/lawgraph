"""Delegation clauses in the text of an article, and which regulations fill them — pure, no I/O.

A law delegates rule-making with a fixed formula: "bij of krachtens algemene maatregel van
bestuur", "bij algemene maatregel van bestuur", "bij ministeriële regeling", "bij regeling van
Onze Minister". :func:`delegation_clauses` finds those formulas in the text of an article,
each with the part (lid, onderdeel) it stands in. A formula that names rules already made
("de bij algemene maatregel van bestuur gestelde regels") delegates nothing and is left out.

A regulation names the articles it is issued under in its preamble ("Gelet op artikel 16,
eerste lid, van de Cyberbeveiligingswet"); ``semantic bwb-grondslagen`` writes that as
``BASED_ON``. :func:`fills` decides whether such a regulation fills a clause: its BWB type fits
the formula (an AMvB for "algemene maatregel van bestuur"; with "krachtens" also a ministerial
regulation, which the AMvB may delegate to), and the preamble names the lid of the clause or
no lid at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.core.qualifiers import part_slug

DelegationKind = Literal["amvb", "ministeriele_regeling"]

_CLAUSE = re.compile(
    r"\bbij\s+(?P<krachtens>of\s+krachtens\s+)?(?:een\s+)?"
    r"(?:(?P<amvb>algemene\s+maatregel(?:en)?\s+van\s+(?:rijks)?bestuur)"
    r"|ministeri[eë]le\s+regeling|regeling\s+van\s+Onze\s+Minister(?:s)?)\b",
    re.IGNORECASE,
)
# What follows a formula that names rules already made, not a power to make them.
_MADE = re.compile(r"\s+(?:vast)?gestelde\b|\s+gegeven(?:e)?\b", re.IGNORECASE)

# BWB types (``props.kind``) per formula.
_AMVB_KINDS = frozenset({"AMvB", "rijksAMvB", "AMvB-BES"})
_REGELING_KINDS = frozenset(
    {
        "ministeriele-regeling",
        "ministeriele-regeling-BES",
        "ministeriele-regeling-archiefselectielijst",
    }
)


@dataclass(frozen=True)
class DelegationClause:
    """A delegation formula as a span of the text of an article."""

    start: int
    end: int
    text: str
    kind: DelegationKind
    krachtens: bool
    part: str | None
    lid: str | None


def delegation_clauses(
    text: str | None, parts: Iterable[Mapping[str, Any]] | None = None
) -> list[DelegationClause]:
    """The delegation formulas in *text*, in text order, each with the innermost part of
    *parts* (``props.parts`` of the article) it stands in and the number of its lid."""
    if not text:
        return []
    spans = [p for p in parts or () if _fits(p, len(text))]
    clauses: list[DelegationClause] = []
    for match in _CLAUSE.finditer(text):
        if _MADE.match(text, match.end()):
            continue
        inside = [p for p in spans if p["start"] <= match.start() < p["end"]]
        innermost = min(inside, key=lambda p: p["end"] - p["start"], default=None)
        lid = next((p for p in inside if p.get("kind") == "lid"), None)
        clauses.append(
            DelegationClause(
                start=match.start(),
                end=match.end(),
                text=match.group(0),
                kind="amvb" if match["amvb"] else "ministeriele_regeling",
                krachtens=bool(match["krachtens"]),
                part=str(innermost["id"]) if innermost else None,
                lid=(part_slug(lid.get("number")) or None) if lid else None,
            )
        )
    return clauses


def _fits(part: Mapping[str, Any], length: int) -> bool:
    start, end = part.get("start"), part.get("end")
    return (
        isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= length
    )


def fills(clause: DelegationClause, kind: str | None, leden: Iterable[str]) -> bool:
    """Whether a regulation of BWB type *kind*, issued under the article of *clause* with
    *leden* named in its preamble (none: the whole article), fills the clause."""
    if clause.kind == "amvb":
        kinds = _AMVB_KINDS | _REGELING_KINDS if clause.krachtens else _AMVB_KINDS
    else:
        kinds = _REGELING_KINDS
    if kind not in kinds:
        return False
    named = set(leden)
    return not named or clause.lid is None or clause.lid in named


def kind_rank(kind: str | None) -> int:
    """The order of regulations of BWB type *kind* under an article: AMvBs, then ministerial
    regulations, then the others."""
    if kind in _AMVB_KINDS:
        return 0
    return 1 if kind in _REGELING_KINDS else 2
