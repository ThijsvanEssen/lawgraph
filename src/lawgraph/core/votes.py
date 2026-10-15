"""How the Kamers vote and what a vote decides: the choice of a vote, the outcome of a
decision and of the motion or amendment it was taken on (pure functions, no I/O).

A decision of the Tweede Kamer is taken on the case of an agenda item; the document it was taken
on is the oldest of that case (``queries/decisions.motion_documents``). Its outcome is what the
Kamer writes: carried or not (``passed``: ``Stemmen - aangenomen``, ``Stemmen - zonder
stemming aannemen``, ``Stemmen - verworpen``, or the result of the Eerste Kamer), else the
``BesluitSoort`` of a decision that is no vote (``Stemmen - ingetrokken``, ``- aangehouden``,
``- vervallen``). ``Stemmen - uitstellen`` postpones the vote and is no outcome.

Of several decisions on one document (held twice, then voted) a vote decides before a decision
that is no vote, the latest first. A motion of the Eerste Kamer without a decision has the
status its page states (``behandelstatus``: ``verworpen``). A document without an outcome of its
own that a newer one replaces ("ter vervanging van nr. 19", ``REVISES`` with the rule
``vervanging``) is ``vervangen``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Final, Literal, get_args

# Stemming.Soort values that mean the vote was cast in favour / against; any other value
# ("Onthouden", "Niet deelgenomen") is kept as the source wrote it. A faction of the Eerste
# Kamer can also ask that its vote be noted.
VoteChoice = Literal["Voor", "Tegen"]
VOTE_FOR: Final[VoteChoice] = "Voor"
VOTE_AGAINST: Final[VoteChoice] = "Tegen"
VOTE_NOTED: Final = "Aantekening gevraagd"

# What a vote decided; a document can also end without one.
VoteOutcome = Literal["aangenomen", "verworpen"]
DocumentOutcome = Literal[
    VoteOutcome, "ingetrokken", "aangehouden", "vervallen", "vervangen"
]
OUTCOMES: tuple[DocumentOutcome, ...] = get_args(DocumentOutcome)
ADOPTED: Final[VoteOutcome] = "aangenomen"
REJECTED: Final[VoteOutcome] = "verworpen"
WITHDRAWN: Final[DocumentOutcome] = "ingetrokken"
HELD: Final[DocumentOutcome] = "aangehouden"
LAPSED: Final[DocumentOutcome] = "vervallen"
REPLACED: Final[DocumentOutcome] = "vervangen"

# The outcome of a chain of amendments (``queries/feed_events.CHAINS``): ``other`` for
# withdrawn, held, postponed, lapsed, not voted yet.
ChainOutcome = Literal[VoteOutcome, "other"]
CHAIN_OTHER: Final[ChainOutcome] = "other"
CHAIN_OUTCOMES: tuple[ChainOutcome, ...] = (ADOPTED, REJECTED, CHAIN_OTHER)

# The BesluitSoort of a decision to withdraw the document.
DECISION_KIND_WITHDRAWN: Final = f"Stemmen - {WITHDRAWN}"

# The outcomes of a decision that is no vote, as ``BesluitSoort`` (``Stemmen - ingetrokken``)
# or the result of the Eerste Kamer writes them.
_NOT_VOTED: tuple[DocumentOutcome, ...] = (WITHDRAWN, HELD, LAPSED)

# The props of a document that say how it ended (``semantic tk-paper-outcomes``).
DOCUMENT_OUTCOME_PROPS = ("outcome", "decided_on", "tally", "decision")


def vote_outcome(passed: object) -> VoteOutcome | None:
    """``aangenomen`` or ``verworpen`` as *passed* says; None for a decision that is no
    vote (*passed* null, or no boolean)."""
    if passed is True:
        return ADOPTED
    if passed is False:
        return REJECTED
    return None


def decision_outcome(
    passed: bool | None, decision_kind: str | None, result: str | None
) -> DocumentOutcome | None:
    """The outcome one decision gives its document: ``aangenomen`` or ``verworpen`` by
    *passed*, else the outcome its ``BesluitSoort`` (*decision_kind*) or its result in the
    Eerste Kamer names; None for a decision that is neither (postponed)."""
    if (outcome := vote_outcome(passed)) is not None:
        return outcome
    said = f"{decision_kind or ''} {result or ''}".lower()
    return next((outcome for outcome in _NOT_VOTED if outcome in said), None)


def stated_outcome(status: str | None) -> str | None:
    """The outcome the status a page states names (``verworpen``, ``Aangenomen``); None for
    another status (``in behandeling``)."""
    said = (status or "").lower()
    return next((outcome for outcome in OUTCOMES if outcome in said), None)


def document_outcome(
    decisions: Iterable[Mapping[str, Any]],
    replaced: bool,
    stated: str | None = None,
) -> dict[str, Any]:
    """``{outcome, decided_on, tally, decision}`` of a document with these *decisions*
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
            **dict.fromkeys(DOCUMENT_OUTCOME_PROPS),
            "outcome": stated_outcome(stated) or (REPLACED if replaced else None),
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
