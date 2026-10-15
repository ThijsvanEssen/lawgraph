"""The kind of a Rechtspraak decision: arrest, vonnis, beschikking, uitspraak, beslissing,
conclusie or prejudiciële beslissing, from its metadata, its kop or its court."""

from __future__ import annotations

import re
from typing import Final, Literal, get_args

from lawgraph.core.curated import LISTS
from lawgraph.core.judgment_metadata import (
    AREA_ADMINISTRATIVE,
    DOCUMENT_TYPE_CONCLUSION,
    PROCEDURE_PRELIMINARY_RULING,
    area_of_law,
)

# What a decision is called: a court of cassation or appeal gives an arrest, a court of
# first instance a vonnis, a court on a request (verzoekschrift) a beschikking, an
# administrative court an uitspraak, the advocate-general a conclusie, and the Hoge Raad
# answers the questions of a lower court in a prejudiciële beslissing. The kantonrechter
# rules on an appeal against a traffic fine (Wahv) in a beslissing.

DecisionKind = Literal[
    "arrest",
    "vonnis",
    "beschikking",
    "uitspraak",
    "beslissing",
    "conclusie",
    "prejudiciële beslissing",
]
DECISION_KINDS: tuple[DecisionKind, ...] = get_args(DecisionKind)
KIND_UITSPRAAK: Final[DecisionKind] = "uitspraak"
KIND_CONCLUSIE: Final[DecisionKind] = "conclusie"
KIND_PRELIMINARY_RULING: Final[DecisionKind] = "prejudiciële beslissing"

# The curated kinds: the kind a procedure (``psi:procedure``) names where the kop does not;
# the kind a kind of court gives when nothing else tells (by ``court_kind``: a tier of one
# kind of court is its own); the kinds of court of every area of law, which give an
# uitspraak in administrative law (tax law too).
KIND_OF_PROCEDURE: dict[str, str] = LISTS["procedure-kinds"].entries()
KIND_OF_COURT_KIND: dict[str, str] = LISTS["decision-kinds"].entries()
_GENERAL_COURTS = frozenset(LISTS["general-courts"].entries())

# A kop line that names the decision: "Arrest", "ARREST", "Uitspraak op het hoger beroep
# van:", "beschikking van de meervoudige kamer", "Tussenvonnis", "beslissing van de
# kantonrechter". Not a label with its value
# ("Uitspraak : 10 augustus 2026", "Uitspraak d.d. : 28 augustus 2026").
_KIND_LINE = re.compile(
    r"^(?:tussen|eind|deel|herstel|verstek)?"
    r"(arrest|vonnis|beschikking|uitspraak|beslissing(?=\s+van\b))\b"
    r"(?!\s*(?:d\.d\.|datum)?\s*:)",
    re.IGNORECASE,
)
# What follows the kind in a line that may only give the date of the decision: "Uitspraak
# van 21 september 2026" above "Arrest van de meervoudige kamer voor strafzaken".
_ONLY_A_DATE = re.compile(
    r"\s*(?:van|d\.d\.)?\s*\d{1,2}\s+[a-z]+\s+\d{4}\.?\s*", re.IGNORECASE
)


def kind_in_kop(lines: list[str]) -> str | None:
    """The kind the kop names (``_KIND_LINE``): the first line that names one, one with no
    more than a date after the kind only when no other line names one. ``None`` when none
    does."""
    dated: str | None = None
    for line in lines:
        match = _KIND_LINE.match(line.strip())
        if match is None:
            continue
        if not _ONLY_A_DATE.fullmatch(line.strip()[match.end() :]):
            return match[1].lower()
        dated = dated or match[1].lower()
    return dated


def kind_of_court(court_kind: str | None, area: str | None = None) -> str | None:
    """The kind a kind of court gives (``KIND_OF_COURT_KIND``); a court of every area gives
    an uitspraak in administrative law."""
    if court_kind in _GENERAL_COURTS and area == AREA_ADMINISTRATIVE:
        return KIND_UITSPRAAK
    return KIND_OF_COURT_KIND.get(court_kind or "")


def decision_kind(
    *,
    document_type: str | None,
    procedure: str | None,
    kop: list[str],
    court_kind: str | None,
    subjects: list[str] | None,
) -> str | None:
    """The kind of a decision (``DECISION_KINDS``), from the first that tells: the document
    type (``Conclusie``), the procedure (``Prejudiciële beslissing``), the kop (the line that
    names the decision), the procedure again (``Beschikking``, ``Raadkamer``, ...), and last
    the kind of court and the area of law (``kind_of_court``). ``None`` when none does."""
    if document_type == DOCUMENT_TYPE_CONCLUSION:
        return KIND_CONCLUSIE
    if procedure == PROCEDURE_PRELIMINARY_RULING:
        return KIND_PRELIMINARY_RULING
    return (
        kind_in_kop(kop)
        or KIND_OF_PROCEDURE.get(procedure or "")
        or kind_of_court(court_kind, area_of_law(subjects))
    )
