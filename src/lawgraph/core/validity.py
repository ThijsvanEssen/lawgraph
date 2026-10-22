"""``validity``: whether a law or an article holds on a day, from the dates its source gives.

One shape for an instrument and an article (docs/api.md "Validity")::

    validity: {state, date, as_of, successors}

``state`` is one of ``ValidityState``. A law of the BWB is ``expired`` from ``date_expired`` on (the
first day it no longer held, as the SRU record of its toestand gives it), ``not_in_force_yet``
before its ``date_in_force``, else ``in_force``; a law of the Staatsblad the BWB does not hold
(yet) is ``not_in_force_yet`` (``status`` `vastgesteld`); a treaty of the Verdragenbank is
``in_force`` when the register says `inwerkinggetreden`. An article holds as long as its law
does, and until its own end: the ``valid_until`` of its newest version (the version that
says it lapsed, or the first toestand without it). Where the source says none of this (an EU
act, any other treaty) there is no validity: not known is not in force.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, NamedTuple

from lawgraph.core.staatsblad_laws import STATUS_ENACTED


class ValidityState(StrEnum):
    """Whether it holds on the day asked."""

    IN_FORCE = "in_force"
    EXPIRED = "expired"
    NOT_IN_FORCE_YET = "not_in_force_yet"


class Validity(NamedTuple):
    """The state on a day and the date that goes with it: of ``expired`` the first day it no
    longer held; of ``not_in_force_yet`` the day it comes into force (None when not known);
    of ``in_force`` the first day it will no longer hold, when the source says so already."""

    state: ValidityState
    date: str | None = None


def _day(value: Any) -> str | None:
    """The ``YYYY-MM-DD`` of a date prop, None for none."""
    text = str(value or "").strip()[:10]
    return text or None


def instrument_validity(props: Mapping[str, Any], today: str) -> Validity | None:
    """The validity on *today* of the instrument of *props*; None where its source says
    nothing of it."""
    if props.get("stub"):
        return None
    expired, start = _day(props.get("date_expired")), _day(props.get("date_in_force"))
    if expired and expired <= today:
        return Validity(ValidityState.EXPIRED, expired)
    if props.get("in_force") is False:
        if props.get("status") != STATUS_ENACTED:
            return None
        return Validity(
            ValidityState.NOT_IN_FORCE_YET, start if start and start > today else None
        )
    if start and start > today:
        return Validity(ValidityState.NOT_IN_FORCE_YET, start)
    if props.get("bwb_id") or props.get("in_force") is True:
        return Validity(ValidityState.IN_FORCE, expired)
    return None


def article_validity(
    law: Validity | None, ended: str | None, repealed: bool, today: str
) -> Validity | None:
    """The validity on *today* of an article of the law of validity *law*, whose newest
    version ends on *ended* (its ``valid_until``, None while it holds); *repealed* when the
    source says it lapsed (``props.repealed``), also without a version that says when."""
    ended = _day(ended)
    own = None
    if ended and ended <= today:
        own = Validity(ValidityState.EXPIRED, ended)
    elif repealed:
        own = Validity(ValidityState.EXPIRED)
    if law is not None and law.state is ValidityState.EXPIRED:
        if own is None or own.date is None or str(law.date) < own.date:
            return law
        return own
    if own is not None:
        return own
    if law is None or law.state is ValidityState.NOT_IN_FORCE_YET:
        return law
    ends = sorted(day for day in (ended, law.date) if day)
    return Validity(ValidityState.IN_FORCE, ends[0] if ends else None)
