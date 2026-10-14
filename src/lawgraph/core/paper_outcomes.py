"""How a motion or an amendment ended: from the decisions of the Kamer on it (pure functions,
no I/O).

A decision of the Tweede Kamer is taken on the case of an agenda item; the paper it was taken
on is the oldest of that case (``queries/decisions.motion_papers``). Its outcome is what the
Kamer writes: carried or not (``passed``: ``Stemmen - aangenomen``, ``Stemmen - zonder
stemming aannemen``, ``Stemmen - verworpen``, or the result of the Eerste Kamer), else the
``BesluitSoort`` of a decision that is no vote (``Stemmen - ingetrokken``, ``- aangehouden``,
``- vervallen``). ``Stemmen - uitstellen`` postpones the vote and is no outcome.

Of several decisions on one paper (held twice, then voted) a vote decides before a decision
that is no vote, the latest first. A motion of the Eerste Kamer without a decision has the
status its page states (``behandelstatus``: ``verworpen``). A paper without an outcome of its
own that a newer one replaces ("ter vervanging van nr. 19", ``REVISES`` with the rule
``vervanging``) is ``vervangen``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final, Literal, get_args

# What a vote decided; a paper can also end without one.
VoteOutcome = Literal["aangenomen", "verworpen"]
PaperOutcome = Literal[
    VoteOutcome, "ingetrokken", "aangehouden", "vervallen", "vervangen"
]
OUTCOMES: tuple[PaperOutcome, ...] = get_args(PaperOutcome)
ADOPTED: Final[VoteOutcome] = "aangenomen"
REJECTED: Final[VoteOutcome] = "verworpen"
WITHDRAWN: Final[PaperOutcome] = "ingetrokken"
HELD: Final[PaperOutcome] = "aangehouden"
LAPSED: Final[PaperOutcome] = "vervallen"
REPLACED: Final[PaperOutcome] = "vervangen"

# The words of a decision that is no vote, as ``BesluitSoort`` (``Stemmen - ingetrokken``) or
# the result of the Eerste Kamer writes them, and the outcome each says.
_NOT_VOTED = ((WITHDRAWN, WITHDRAWN), (HELD, HELD), (LAPSED, LAPSED))

# The props of a paper this keeps (``semantic tk-paper-outcomes``).
PAPER_OUTCOME_PROPS = ("outcome", "decided_on", "tally", "decision")


def decision_outcome(
    passed: bool | None, decision_kind: str | None, result: str | None
) -> str | None:
    """The outcome one decision gives its paper: ``aangenomen`` or ``verworpen`` by
    *passed*, else the outcome its ``BesluitSoort`` (*decision_kind*) or its result in the
    Eerste Kamer names; None for a decision that is neither (postponed)."""
    if passed is True:
        return ADOPTED
    if passed is False:
        return REJECTED
    said = f"{decision_kind or ''} {result or ''}".lower()
    return next((outcome for word, outcome in _NOT_VOTED if word in said), None)


def stated_outcome(status: str | None) -> str | None:
    """The outcome the status a page states names (``verworpen``, ``Aangenomen``); None for
    another status (``in behandeling``)."""
    said = (status or "").lower()
    return next((outcome for outcome in OUTCOMES if outcome in said), None)


def paper_outcome(
    decisions: Iterable[Mapping[str, Any]],
    replaced: bool,
    stated: str | None = None,
) -> dict[str, Any]:
    """``{outcome, decided_on, tally, decision}`` of a paper with these *decisions*
    (``{key, date, passed, decision_kind, result, tally}``): of those with an outcome a vote
    before the others, the latest first (by date, then key); without one the outcome its
    *stated* status names, then ``vervangen`` when *replaced*; every value null without any.
    ``tally`` is the seats per choice of the vote (``{"Voor": 150}``), null for a decision
    without votes."""
    found = [
        (outcome, decision)
        for decision in decisions
        if (
            outcome := decision_outcome(
                decision.get("passed"),
                decision.get("decision_kind"),
                decision.get("result"),
            )
        )
    ]
    if not found:
        return {
            "outcome": stated_outcome(stated) or (REPLACED if replaced else None),
            "decided_on": None,
            "tally": None,
            "decision": None,
        }
    outcome, chosen = max(
        found,
        key=lambda item: (
            item[1].get("passed") is not None,
            item[1].get("date") or "",
            item[1].get("key") or "",
        ),
    )
    return {
        "outcome": outcome,
        "decided_on": chosen.get("date"),
        "tally": chosen.get("tally") or None,
        "decision": chosen.get("key"),
    }
