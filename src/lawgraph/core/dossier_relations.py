"""Relations between dossiers of different numbers (pure functions, no I/O).

The Kamerstukdossier record names no other dossier. Three things do:

* the Kamer's own relation between two cases (``Zaak.GerelateerdNaar``), mostly a letter of
  the government and the motion it answers: :func:`related_dossiers` lifts it to the
  dossiers of the two cases (``RELATED_TO``);
* the titles of the budget laws, which follow a fixed form: :func:`budget_amendments` finds
  the budget a supplementary budget or a slotwet revises (``REVISES``), and
  :func:`accompanied_notas` the Voorjaarsnota, Najaarsnota or Miljoenennota a budget change
  is submitted with (``ACCOMPANIES``);
* the memorandum of a change in the Grondwet in its second reading, which refers to the papers
  of the first reading: :func:`first_readings` (``SECOND_READING_OF``).

``semantic tk-dossier-relations`` writes them as edges; the rules are described in
``docs/pipelines.md``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from lawgraph.config.constants import COLLECTION_CASES
from lawgraph.core.budget_titles import BudgetAct, BudgetTitle, parse_budget_title
from lawgraph.core.dossier_numbers import first_reading_dossiers
from lawgraph.core.models import make_node_key

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
    """What the rules read of a dossier: its label, number, suffix and title, and what the
    title says of the budget law it names."""

    label: str
    number: str
    suffix: str
    title: str
    budget: BudgetTitle | None

    @classmethod
    def of(cls, props: Mapping[str, Any]) -> DossierRef:
        title = " ".join(str(props.get("title") or "").split())
        return cls(
            label=str(props.get("label") or ""),
            number=str(props.get("number") or ""),
            suffix=str(props.get("suffix") or "").upper(),
            title=title,
            budget=parse_budget_title(title),
        )

    def budget_of(self, act: BudgetAct) -> BudgetTitle | None:
        """What the title says, where it names a budget law of *act* in a year."""
        budget = self.budget
        return budget if budget and budget.act == act and budget.year else None


@dataclass(frozen=True)
class DossierLink:
    """An edge between two dossiers by label, with what it carries in ``meta``."""

    from_label: str
    to_label: str
    meta: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)


def _chapters(dossier: DossierRef, budget: BudgetTitle) -> list[str]:
    """The chapter a budget change amends, most specific first: ``IXB`` and then ``IX``."""
    chapter = dossier.suffix or budget.chapter
    if not chapter:
        return []
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
        budget = dossier.budget_of("budget")
        if budget and budget.year and dossier.suffix:
            budgets[(dossier.suffix, budget.year)] = dossier

    for dossier in dossiers:
        change = dossier.budget_of("change") or (
            dossier.budget_of("slotwet") if dossier.suffix else None
        )
        if change is None or change.year is None:
            continue
        year = change.year
        target = next(
            (
                budgets[(chapter, year)]
                for chapter in _chapters(dossier, change)
                if (chapter, year) in budgets
            ),
            None,
        )
        if target is None and change.act == "change" and not dossier.suffix:
            target = _budget_by_name(change, budgets.values())
        if target is not None:
            rule = RULE_BUDGET_CHANGE if change.act == "change" else RULE_SLOTWET
            yield DossierLink(dossier.label, target.label, {"rule": rule})


def _budget_by_name(
    change: BudgetTitle, budgets: Iterable[DossierRef]
) -> DossierRef | None:
    if not change.subject:
        return None
    candidates = [
        budget
        for budget in budgets
        if budget.budget
        and budget.budget.year == change.year
        and budget.budget.subject.startswith(change.subject)
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
        change = dossier.budget_of("change")
        if change is None or change.year is None or change.nota is None:
            continue
        nota, year = change.nota, change.year
        target = notas.get((nota, year + 1 if nota == "miljoenennota" else year))
        if target is not None and target.label != dossier.label:
            yield DossierLink(dossier.label, target.label, {"nota": nota})


def _miljoenennotas(
    dossiers: list[DossierRef],
) -> Iterator[tuple[DossierRef, int]]:
    """``(dossier, budget year)`` of every Miljoenennota, dated by its budgets."""
    years: dict[str, Counter[int]] = {}
    for dossier in dossiers:
        budget = dossier.budget_of("budget")
        if budget and budget.year:
            years.setdefault(dossier.number, Counter())[budget.year] += 1
    for dossier in dossiers:
        if (
            not dossier.suffix
            and _MILJOENENNOTA.match(dossier.title)
            and dossier.number in years
        ):
            year = years[dossier.number].most_common(1)[0][0]
            yield dossier, year


def first_readings(memoranda: Iterable[Mapping[str, Any]]) -> Iterator[DossierLink]:
    """``SECOND_READING_OF`` links: from the dossier of a memorandum that refers to the
    papers of a first reading (``core.dossier_numbers.first_reading_dossiers``) to the
    dossiers of that first reading. *memoranda* are ``{labels, text}``."""
    for memorandum in memoranda:
        for number in first_reading_dossiers(memorandum.get("text")):
            for label in memorandum.get("labels") or []:
                if label.split("-")[0] != number:
                    yield DossierLink(label, number)


def _case_kinds(case: Mapping[str, Any], other: Mapping[str, Any]) -> str:
    """What two related cases are: ``Brief regering → Motie``."""
    return f"{case.get('kind') or '?'} → {other.get('kind') or '?'}"


def related_case_pairs(
    cases: Iterable[Mapping[str, Any]],
) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """``(case id, other case id, meta)`` for every pair of cases the Kamer relates
    (``GerelateerdNaar``), as TK ids, each pair once, also within one dossier or without
    one: a letter and the motion it answers. ``meta.case_kinds`` says what they are
    ("Brief regering → Motie")."""
    seen: set[tuple[str, str]] = set()
    for case in cases:
        own = str(case.get("id") or "")
        for other in case.get("related_cases") or []:
            other_id = str(other.get("id") or "")
            if not own or not other_id or own == other_id or (own, other_id) in seen:
                continue
            seen.add((own, other_id))
            yield own, other_id, {"case_kinds": _case_kinds(case, other)}


def related_case_ids(cases: Iterable[Mapping[str, Any]]) -> list[str]:
    """The TK ids of every case in *cases* and of every case they relate, once each."""
    ids = {
        str(i)
        for case in cases
        for i in (
            case.get("id"),
            *(other.get("id") for other in case.get("related_cases") or []),
        )
        if i
    }
    return sorted(ids)


def _side(
    case_id: str, papers: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The sides a case gives a pair: one per paper of its own kind (``case_papers``), each
    with the number of its case; the case alone when it has none in the graph."""
    found = papers.get(case_id) or {}
    number = found.get("number")
    own = [
        {
            "case": number,
            "paper": paper.get("id"),
            "kind": paper.get("kind"),
            "dossier_number": paper.get("dossier_number"),
            "dossier_suffix": paper.get("dossier_suffix"),
            "sequence": paper.get("sequence"),
            "date": paper.get("date"),
        }
        for paper in found.get("papers") or []
    ]
    return own or [{"case": number, "paper": None}]


# The pairs of papers an edge between two dossiers keeps (``meta.pairs``): the newest. Two
# dossiers may share hundreds (21501-02 and a budget); ``meta.cases`` counts them all.
PAIRS_KEPT = 5


def _newest(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ``PAIRS_KEPT`` newest *pairs*, by the day of their papers (the later side), in
    that order; a pair without a paper in the graph last."""

    def day(pair: dict[str, Any]) -> str:
        return max(
            str(pair["from"].get("date") or ""), str(pair["to"].get("date") or "")
        )

    return sorted(pairs, key=day, reverse=True)[:PAIRS_KEPT]


def related_dossiers(
    cases: Iterable[Mapping[str, Any]],
    papers: Mapping[str, Mapping[str, Any]] | None = None,
) -> Iterator[DossierLink]:
    """``RELATED_TO`` links between the dossiers of two cases the Kamer relates.

    A case of dossier A that the Kamer relates to a case of dossier B (``GerelateerdNaar``)
    relates A to B. ``meta.cases`` is how many such pairs of cases there are, ``meta.case_kinds``
    their kinds ("Brief regering → Motie"), and ``meta.pairs`` the papers of the newest pairs
    (``PAIRS_KEPT``): per pair of papers of the two cases' own kinds (*papers*,
    ``case_papers``: the letter and the motion) ``{kinds, from, to}``, each side ``{case,
    paper, kind, dossier_number, dossier_suffix, sequence, date}``, or ``{case, paper:
    null}`` for a case without such a paper in the graph. Cases within one dossier relate
    no dossiers.
    """
    papers = papers or {}
    pairs: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
    for case in cases:
        own = set(case.get("dossier_numbers") or [])
        for other in case.get("related_cases") or []:
            for from_label in own:
                for to_label in set(other.get("dossier_numbers") or []) - own:
                    pairs.setdefault((from_label, to_label), set()).add(
                        (
                            str(case.get("id") or ""),
                            str(other.get("id") or ""),
                            _case_kinds(case, other),
                        )
                    )
    for (from_label, to_label), case_pairs in sorted(pairs.items()):
        yield DossierLink(
            from_label,
            to_label,
            {
                "cases": len(case_pairs),
                "case_kinds": sorted({kinds for _, _, kinds in case_pairs}),
                "pairs": _newest(
                    [
                        {"kinds": kinds, "from": one, "to": two}
                        for case, other, kinds in sorted(case_pairs)
                        for one in _side(case, papers)
                        for two in _side(other, papers)
                    ]
                ),
            },
        )


def moved_activities(
    activities: Iterable[Mapping[str, Any]],
) -> Iterator[tuple[str, str]]:
    """``(id of the activity that replaced, id of the moved one)``: a moved activity names
    the number of the one that replaced it (``replaced_by``, ``Activiteit.VervangenDoor``),
    read from rows of ``{id, number, replaced_by}``; a number not stored is none."""
    rows = list(activities)
    by_number = {
        str(row["number"]): str(row["id"]) for row in rows if row.get("number")
    }
    for row in rows:
        for number in row.get("replaced_by") or []:
            replacing = by_number.get(str(number))
            if replacing and replacing != row["id"]:
                yield replacing, str(row["id"])


def replaced_cases(rows: Iterable[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """``(id of the case, id of the case it replaces)`` from rows of ``{id, replaces}``
    (``Zaak.VervangenVanuit``, the TK ids of the cases replaced), in order."""
    return [
        (str(row["id"]), f"{COLLECTION_CASES}/{make_node_key(str(old))}")
        for row in rows
        for old in row.get("replaces") or []
        if old
    ]


def replaced_papers(
    cases: Iterable[tuple[str, str]], papers: Mapping[str, list[str]]
) -> Iterator[tuple[str, str]]:
    """``(paper, paper it replaces)``: each paper of a case that replaces another revises
    each paper of that case ("Gewijzigd amendement ter vervanging van nr. 21"); a case
    without papers in the graph none."""
    for case, replaced in cases:
        for paper in papers.get(case, []):
            for old in papers.get(replaced, []):
                if old != paper:
                    yield paper, old
