"""The SQL the lists of committees, members and factions share: the columns of a node, the
period a list asks for, a name that holds the words asked, the Kamer of a node and the
faction period of the day of a vote."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import CHAMBER_EK
from lawgraph.db.queries._json_sql import period_holds

# The columns of a node row (``node_doc``) of the table named ``{t}``.
NODE = "{t}.id, {t}.key, {t}.type, {t}.labels, {t}.props"


# The period a list asks for (``asked_period``): open on a side it leaves out.
ASKED = ("%(active_from)s", "%(active_to)s")


def asked_period(
    bind: dict[str, Any], active_from: str | None, active_to: str | None
) -> bool:
    """Put the period asked in *bind*; whether one was asked."""
    bind["active_from"] = active_from
    bind["active_to"] = active_to
    return bool(active_from or active_to)


def contains(text: str) -> str:
    """SQL: *text* holds ``%(q)s``, both folded as the search folds them (``lg_fold``: lower
    case, no accents: ``yesilgoz`` finds Yeşilgöz); null holds nothing, and nothing holds
    ``""``."""
    return (
        f"(%(q)s <> '' AND strpos(lg_fold(coalesce({text}, '')), lg_fold(%(q)s)) > 0)"
    )


def of_chamber(table: str, chamber: str) -> str:
    """SQL: *table* (a faction or committee) is of *chamber* (``TK`` or ``EK``)."""
    test = "=" if chamber == CHAMBER_EK else "IS DISTINCT FROM"
    return f"lg_str({table}.props -> 'chamber') {test} '{CHAMBER_EK}'"


# The membership ``f.period`` held on the day ``d.date``.
IN_MEMBERSHIP = period_holds(
    "f.period -> 'from_date'", "f.period -> 'to_date'", "d.date"
)
