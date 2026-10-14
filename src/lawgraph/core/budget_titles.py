"""The titles of the budget laws, read once (pure functions, no I/O).

The Kamer gives a budget law a title of a fixed form:

* a budget: "Vaststelling van de begrotingsstaten van het Ministerie van Defensie (X) voor
  het jaar 2027";
* a change of it, a supplementary budget: "Wijziging van de begrotingsstaat van het
  gemeentefonds voor het jaar 2026 (wijziging samenhangende met de Miljoenennota)", or one
  with a number of its own: "… (IXB) voor het jaar 2020 (Incidentele suppletoire begroting
  inzake …)";
* the law that settles a year: "Jaarverslag en slotwet Ministerie van Defensie 2025".

:func:`parse_budget_title` reads what such a title says. ``core.dossier_numbers.short_title``
names a dossier by it, ``core.dossier_relations`` ties a change to the budget it revises and
to the nota it goes with.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from lawgraph.core.xml import collapse_ws

BudgetAct = Literal["budget", "change", "slotwet"]

_ACTS: dict[str, BudgetAct] = {"vaststelling": "budget", "wijziging": "change"}

_BUDGET = re.compile(
    r"^(?P<act>vaststelling|wijziging) van de begrotingssta\w* (?P<of>(?:van|voor) )?"
    r"(?P<subject>.*?) voor het jaar (?P<year>\d{4})(?P<rest>.*)$",
    re.IGNORECASE,
)
# The chapter or fund a title names, short: "Defensie" of "het Ministerie van Defensie (X)",
# "Financiën" of "het Ministerie van Financiën (IXB) en de begrotingsstaat van …".
_NAME = re.compile(
    r"^(?:het Ministerie van |het |de )?(?P<name>.+?)(?= \(| en (?:de|het) |, (?:de|het) |$)",
    re.IGNORECASE,
)
# What may follow the year of a title of the plain form: the year again, of a second budget
# it changes, and the occasion of a change, "(wijziging samenhangende met de Voorjaarsnota)".
_PLAIN_REST = re.compile(
    r"(?:.* voor het jaar \d{4})? ?"
    r"(?:\(wijziging samenhangend\w* met (?:de )?(?P<occasion>[^()]+)\))?",
    re.IGNORECASE,
)
# "samenhangende met de Voorjaarsnota": the nota a change is submitted with.
_NOTA = re.compile(
    r"samenhangend\w* met (?:de )?(?P<nota>voorjaarsnota|najaarsnota|miljoenennota)\b",
    re.IGNORECASE,
)
_SLOTWET = re.compile(r"\bslotwet\b", re.IGNORECASE)
# "Jaarverslag en slotwet Ministerie van Defensie 2025": the form a slotwet is named by.
_FINAL_ACT = re.compile(
    r"^Jaarverslag en slotwet (?:(?:het )?Ministerie van )?(?P<name>.+?) (?P<year>\d{4})$",
    re.IGNORECASE,
)
_LAST_YEAR = re.compile(r"\b(\d{4})\b(?!.*\b\d{4}\b)")
# The chapter a title names: "(XIII)", "(IXB)", a fund "(K)". The first one is the budget's.
_CHAPTER = re.compile(r"\(([IVX]+[A-C]?|[A-Z])\)")
_PARENTHESES = re.compile(r" ?\([^)]*\)")


@dataclass(frozen=True)
class BudgetTitle:
    """What the title of a budget law says.

    *subject* is what it budgets as the title words it, lower case and without chapters
    ("het ministerie van financiën en de begrotingsstaat van nationale schuld"); *name* the
    chapter or fund it is named by ("Financiën"), None where the title is not of the plain
    form; *occasion* what a change of the plain form comes with, as written ("Najaarsnota");
    *nota* the nota a change goes with (``voorjaarsnota``, ``najaarsnota``,
    ``miljoenennota``); *chapter* the first chapter the title names (``IXB``).
    """

    act: BudgetAct
    year: int | None
    subject: str
    name: str | None
    occasion: str | None
    nota: str | None
    chapter: str | None

    @property
    def short_title(self) -> str | None:
        """``Begroting Defensie 2027``, ``Suppletoire begroting gemeentefonds 2026
        (Miljoenennota)``, ``Slotwet Defensie 2025``; None where the title is not of the plain
        form."""
        if self.name is None:
            return None
        if self.act == "slotwet":
            return f"Slotwet {self.name} {self.year}"
        act = "Begroting" if self.act == "budget" else "Suppletoire begroting"
        name = f"{act} {self.name} {self.year}"
        return f"{name} ({self.occasion})" if self.occasion else name


def parse_budget_title(title: str | None) -> BudgetTitle | None:
    """What *title* says of the budget law it names; None for another title."""
    text = collapse_ws(title)
    chapter = _CHAPTER.search(text)
    budget = _BUDGET.match(text)
    if budget:
        rest = budget["rest"].strip()
        nota = _NOTA.search(rest)
        plain = _PLAIN_REST.fullmatch(rest) if budget["of"] else None
        named = _NAME.match(budget["subject"])
        return BudgetTitle(
            act=_ACTS[budget["act"].lower()],
            year=int(budget["year"]),
            subject=_PARENTHESES.sub("", budget["subject"]).lower().strip(),
            name=named["name"] if plain and named else None,
            occasion=plain["occasion"] if plain else None,
            nota=nota["nota"].lower() if nota else None,
            chapter=chapter.group(1) if chapter else None,
        )
    if _SLOTWET.search(text):
        final = _FINAL_ACT.match(text)
        last = _LAST_YEAR.search(text)
        return BudgetTitle(
            act="slotwet",
            year=int(last.group(1)) if last else None,
            subject="",
            name=final["name"] if final else None,
            occasion=None,
            nota=None,
            chapter=chapter.group(1) if chapter else None,
        )
    return None
