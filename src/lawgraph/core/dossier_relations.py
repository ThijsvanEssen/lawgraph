"""Relations between dossiers of different numbers (pure functions, no I/O).

The Kamerstukdossier record names no other dossier. Two things do:

* the Kamer's own relation between two cases (``Zaak.GerelateerdNaar``), mostly a letter of
  the government and the motion it answers: :func:`related_dossiers` lifts it to the
  dossiers of the two cases (``RELATED_TO``);
* the titles of the budget laws, which follow a fixed form: :func:`budget_amendments` finds
  the budget a supplementary budget or a slotwet revises (``REVISES``), and
  :func:`accompanied_notas` the Voorjaarsnota, Najaarsnota or Miljoenennota a budget change
  is submitted with (``ACCOMPANIES``).

``semantic tk-dossier-relations`` writes the three as edges; the rules are described in
``docs/pipelines.md``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

# "Wijziging van de begrotingsstaten van het Ministerie van … (XXII) voor het jaar 2026 …":
# a supplementary budget, whether it comes with the Voorjaarsnota, the Najaarsnota, the
# Miljoenennota or on its own ("Incidentele suppletoire begroting inzake …").
_BUDGET_CHANGE = re.compile(r"^wijziging van de begrotingssta", re.IGNORECASE)
# "Vaststelling van de begrotingsstaten van het Ministerie van … (XXII) voor het jaar 2026".
_BUDGET = re.compile(r"^vaststelling van de begrotingssta", re.IGNORECASE)
# "Jaarverslag en slotwet Ministerie van … 2024": the law that settles a year's budget.
_SLOTWET = re.compile(r"\bslotwet\b", re.IGNORECASE)
_BUDGET_YEAR = re.compile(r"voor het jaar\s+(\d{4})", re.IGNORECASE)
_LAST_YEAR = re.compile(r"\b(\d{4})\b(?!.*\b\d{4}\b)")
# The chapter a title names, for a supplementary budget with a number of its own: "(XIII)",
# "(IXB)", a fund "(K)". The first one is the budget amended.
_TITLE_CHAPTER = re.compile(r"\(([IVX]+[A-C]?|[A-Z])\)")
# The budget a title names: "van het Ministerie van Financiën", "van het gemeentefonds".
_BUDGET_NAME = re.compile(
    r"begrotingssta\w*\s+(?:van\s+|voor\s+)?(.*?)\s+voor het jaar", re.IGNORECASE
)
_PARENTHESES = re.compile(r"\s*\([^)]*\)")

# "(wijziging samenhangende met de Voorjaarsnota)", "… met Miljoenennota)".
_ACCOMPANIES = re.compile(
    r"samenhangend\w*\s+met\s+(?:de\s+)?(voorjaarsnota|najaarsnota|miljoenennota)\b",
    re.IGNORECASE,
)
# "Voorjaarsnota 2026", "Najaarsnota 2025".
_SEASONAL_NOTA = re.compile(r"^(voorjaarsnota|najaarsnota)\s+(\d{4})$", re.IGNORECASE)
# The Miljoenennota: "Nota over de toestand van ’s Rijks Financiën", the dossier without
# suffix of the number that holds the budgets of the next year.
_MILJOENENNOTA = re.compile(
    r"^nota over de toestand van .s rijks financi", re.IGNORECASE
)

RULE_BUDGET_CHANGE = "begrotingswijziging"
RULE_SLOTWET = "slotwet"


@dataclass(frozen=True)
class DossierRef:
    """What the rules read of a dossier: its label, number, suffix and title."""

    label: str
    number: str
    suffix: str
    title: str

    @classmethod
    def of(cls, props: Mapping[str, Any]) -> DossierRef:
        return cls(
            label=str(props.get("label") or ""),
            number=str(props.get("number") or ""),
            suffix=str(props.get("suffix") or "").upper(),
            title=" ".join(str(props.get("title") or "").split()),
        )


@dataclass(frozen=True)
class DossierLink:
    """An edge between two dossiers by label, with what it carries in ``meta``."""

    from_label: str
    to_label: str
    meta: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


def _budget_year(title: str) -> int | None:
    match = _BUDGET_YEAR.search(title)
    return int(match.group(1)) if match else None


def _budget_name(title: str) -> str:
    match = _BUDGET_NAME.search(title)
    return _PARENTHESES.sub("", match.group(1)).lower().strip() if match else ""


def _chapters(dossier: DossierRef) -> list[str]:
    """The chapter a budget change amends, most specific first: ``IXB`` and then ``IX``."""
    if dossier.suffix:
        chapter = dossier.suffix
    else:
        named = _TITLE_CHAPTER.search(dossier.title)
        if not named:
            return []
        chapter = named.group(1)
    general = chapter.rstrip("ABC") if len(chapter) > 1 else chapter
    return [chapter] if general == chapter else [chapter, general]


def budget_amendments(dossiers: Iterable[DossierRef]) -> Iterator[DossierLink]:
    """``REVISES`` links from a supplementary budget or slotwet to the budget it revises.

    A budget is "Vaststelling van de begrotingsstaten … voor het jaar Y" under a chapter (the
    suffix, ``XXII``) or a fund (``A``). A change "Wijziging van de begrotingsstaten … voor het
    jaar Y" amends the budget of year Y with its own suffix; a change with a number of its own
    (an incidental one) names its chapter in its title, "(XIII)", or else the budget by name
    ("van het Ministerie van Financiën"), which must then fit exactly one budget of the year.
    A slotwet, "Jaarverslag en slotwet … Y", revises the budget of year Y with its suffix.
    """
    dossiers = list(dossiers)
    budgets: dict[tuple[str, int], DossierRef] = {}
    for dossier in dossiers:
        year = _budget_year(dossier.title)
        if _BUDGET.match(dossier.title) and year and dossier.suffix:
            budgets[(dossier.suffix, year)] = dossier

    for dossier in dossiers:
        if _BUDGET_CHANGE.match(dossier.title):
            year, rule = _budget_year(dossier.title), RULE_BUDGET_CHANGE
        elif _SLOTWET.search(dossier.title) and dossier.suffix:
            last = _LAST_YEAR.search(dossier.title)
            year, rule = (int(last.group(1)) if last else None), RULE_SLOTWET
        else:
            continue
        if year is None:
            continue
        target = next(
            (
                budgets[(chapter, year)]
                for chapter in _chapters(dossier)
                if (chapter, year) in budgets
            ),
            None,
        )
        if target is None and rule == RULE_BUDGET_CHANGE and not dossier.suffix:
            target = _budget_by_name(dossier, year, budgets.values())
        if target is not None:
            yield DossierLink(dossier.label, target.label, {"rule": rule})


def _budget_by_name(
    change: DossierRef, year: int, budgets: Iterable[DossierRef]
) -> DossierRef | None:
    name = _budget_name(change.title)
    if not name:
        return None
    candidates = [
        budget
        for budget in budgets
        if _budget_year(budget.title) == year
        and _budget_name(budget.title).startswith(name)
    ]
    return candidates[0] if len(candidates) == 1 else None


def accompanied_notas(dossiers: Iterable[DossierRef]) -> Iterator[DossierLink]:
    """``ACCOMPANIES`` links from a budget change to the nota it is submitted with.

    "(wijziging samenhangende met de Voorjaarsnota)" of year Y goes with the dossier
    "Voorjaarsnota Y", and likewise the Najaarsnota. The Miljoenennota of Prinsjesdag in year Y
    presents the budgets of Y + 1; the changes of year Y "samenhangende met de Miljoenennota"
    go with it: the dossier "Nota over de toestand van ’s Rijks Financiën" whose number holds
    the budgets of Y + 1.
    """
    dossiers = list(dossiers)
    notas: dict[tuple[str, int], DossierRef] = {}
    for dossier in dossiers:
        seasonal = _SEASONAL_NOTA.match(dossier.title)
        if seasonal:
            notas[(seasonal.group(1).lower(), int(seasonal.group(2)))] = dossier
    for dossier, budget_year in _miljoenennotas(dossiers):
        notas[("miljoenennota", budget_year)] = dossier

    for dossier in dossiers:
        accompanies = _ACCOMPANIES.search(dossier.title)
        year = _budget_year(dossier.title)
        if not accompanies or not _BUDGET_CHANGE.match(dossier.title) or not year:
            continue
        nota = accompanies.group(1).lower()
        target = notas.get((nota, year + 1 if nota == "miljoenennota" else year))
        if target is not None and target.label != dossier.label:
            yield DossierLink(dossier.label, target.label, {"nota": nota})


def _miljoenennotas(
    dossiers: list[DossierRef],
) -> Iterator[tuple[DossierRef, int]]:
    """``(dossier, budget year)`` of every Miljoenennota, dated by its budgets."""
    years: dict[str, Counter[int]] = {}
    for dossier in dossiers:
        year = _budget_year(dossier.title)
        if _BUDGET.match(dossier.title) and year:
            years.setdefault(dossier.number, Counter())[year] += 1
    for dossier in dossiers:
        if (
            not dossier.suffix
            and _MILJOENENNOTA.match(dossier.title)
            and dossier.number in years
        ):
            year = years[dossier.number].most_common(1)[0][0]
            yield dossier, year


def related_dossiers(cases: Iterable[Mapping[str, Any]]) -> Iterator[DossierLink]:
    """``RELATED_TO`` links between the dossiers of two cases the Kamer relates.

    A case of dossier A that the Kamer relates to a case of dossier B (``GerelateerdNaar``)
    relates A to B. ``meta.cases`` is how many such pairs of cases there are, ``meta.case_kinds``
    their kinds ("Brief regering → Motie"). Cases within one dossier relate no dossiers.
    """
    pairs: dict[tuple[str, str], set[tuple[str, str]]] = {}
    kinds: dict[tuple[str, str], set[str]] = {}
    for case in cases:
        own = set(case.get("dossier_numbers") or [])
        for other in case.get("related_cases") or []:
            for from_label in own:
                for to_label in set(other.get("dossier_numbers") or []) - own:
                    key = (from_label, to_label)
                    pairs.setdefault(key, set()).add(
                        (str(case.get("id") or ""), str(other.get("id") or ""))
                    )
                    kinds.setdefault(key, set()).add(
                        f"{case.get('kind') or '?'} → {other.get('kind') or '?'}"
                    )
    for (from_label, to_label), case_pairs in sorted(pairs.items()):
        yield DossierLink(
            from_label,
            to_label,
            {
                "cases": len(case_pairs),
                "case_kinds": sorted(kinds[(from_label, to_label)]),
            },
        )
