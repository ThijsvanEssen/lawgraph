"""What a dossier is, how far its bill got and how it ended, from the values the Tweede Kamer
gives (pure functions, no I/O).

Shared by the tk_dossiers normalize pipeline (which stores the result on dossier nodes),
``semantic tk-dossier-outcomes`` and the dossier API (which derives it on the fly for a
dossier the pipeline has not reached), so it lives in core rather than in either of them.

* The kind of a dossier is the ``Zaak.Soort`` of the zaak that is the dossier itself
  (``CARRYING_KINDS``), as the Kamer writes it; without one, a ``Voorstel van wet`` among
  its papers makes it a bill.
* The phases of a bill are the curated list ``phases`` (``data/curated/phases.json``): the
  one order the Kamer does not give, each phase marked by exact values of the Kamer.
* Its outcome is what the graph holds: the law published, or the Kamer voting the bill
  down; its last decision on the bill is ``BesluitSoort`` as the Kamer writes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.core.curated import LISTS

# ── What a dossier is ─────────────────────────────────────────────────────────

# The Zaak.Soort of a zaak that is the dossier itself; the other zaken of a dossier (a
# Motie, an Amendement, a Brief regering) are filed under it.
CARRYING_KINDS: tuple[str, ...] = (
    "Wetgeving",
    "Initiatiefwetgeving",
    "Begroting",
    "Verdrag",
    "Initiatiefnota",
    "PKB/Structuurvisie",
)

# The kinds that go the way of a bill, and so have phases; a treaty (approved tacitly),
# an initiatiefnota and a structuurvisie have no voorstel van wet.
LEGISLATIVE_KINDS: tuple[str, ...] = ("Wetgeving", "Initiatiefwetgeving", "Begroting")

# Where the kind comes from: a zaak of the dossier, or (without one) its voorstel van wet.
KIND_BASIS_CASE = "case"
KIND_BASIS_DOCUMENT = "document"

# Document.Soort of a bill, and of a bill of members; its explanatory memorandum.
BILL_DOCUMENT = "Voorstel van wet"
INITIATIVE_BILL_DOCUMENT = "Voorstel van wet (initiatiefvoorstel)"
MEMORANDUM_DOCUMENT = "Memorie van toelichting"

# Activiteit.Status of an activity announced and not (yet) held, also when its date passed.
ACTIVITY_PLANNED = "Gepland"

# Activiteit.Status of an activity that did not take place, or not then: it marks no phase.
ACTIVITY_NOT_HELD = frozenset(
    {ACTIVITY_PLANNED, "Geannuleerd", "Verplaatst", "Vervallen"}
)


def _is_bill(kind: str) -> bool:
    return kind == BILL_DOCUMENT or kind.startswith(BILL_DOCUMENT + " (")


def dossier_kind(
    case_kinds: list[str], document_kinds: list[str]
) -> tuple[str | None, str | None]:
    """``(kind, kind_basis)`` of a dossier: the first of ``CARRYING_KINDS`` among the
    Zaak.Soort of its zaken (``case``); else, from its papers, ``Initiatiefwetgeving`` for a
    ``Voorstel van wet (initiatiefvoorstel)`` and ``Wetgeving`` for another voorstel van wet
    (``document``); else ``(None, None)``."""
    kinds = set(case_kinds)
    for kind in CARRYING_KINDS:
        if kind in kinds:
            return kind, KIND_BASIS_CASE
    if INITIATIVE_BILL_DOCUMENT in document_kinds:
        return "Initiatiefwetgeving", KIND_BASIS_DOCUMENT
    if any(_is_bill(kind) for kind in document_kinds):
        return "Wetgeving", KIND_BASIS_DOCUMENT
    return None, None


# ── How far a bill got ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Phase:
    """A phase of the bar and the values of the Kamer that mark it."""

    name: str
    documents: frozenset[str]  # Document.Soort
    activities: frozenset[str]  # Activiteit.Soort, of an activity that took place
    decisions: frozenset[str]  # BesluitSoort, of a decision on the dossier's own zaak


def load_phases() -> tuple[Phase, ...]:
    """The curated list ``phases``, in its order."""
    return tuple(
        Phase(
            name=name,
            documents=frozenset(value.get("documents") or ()),
            activities=frozenset(value.get("activities") or ()),
            decisions=frozenset(value.get("decisions") or ()),
        )
        for name, value in LISTS["phases"].entries().items()
    )


PHASES = load_phases()


def _phase_dates(
    phase: Phase,
    docs: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> list[str | None]:
    """The date of every record that marks *phase* (None for one without a date)."""
    return [
        *(d.get("date") for d in docs if d.get("kind") in phase.documents),
        *(
            a.get("date")
            for a in activities
            if a.get("kind") in phase.activities
            and a.get("status") not in ACTIVITY_NOT_HELD
        ),
        *(
            d.get("date")
            for d in decisions
            if d.get("decision_kind") in phase.decisions
            and d.get("case_kind") in LEGISLATIVE_KINDS
        ),
    ]


def dossier_phases(
    kind: str | None,
    docs: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    phases: tuple[Phase, ...] = PHASES,
) -> list[dict[str, Any]] | None:
    """``[{name, done, date}]`` in the order of *phases* for a dossier of one of
    ``LEGISLATIVE_KINDS``, else None. A phase is done when a paper, an activity that took
    place or a decision on the bill marks it; ``date`` is the first date of those."""
    if kind not in LEGISLATIVE_KINDS:
        return None
    out = []
    for phase in phases:
        dates = _phase_dates(phase, docs, activities, decisions)
        known = [d for d in dates if d]
        out.append(
            {"name": phase.name, "done": bool(dates), "date": min(known, default=None)}
        )
    return out


def current_phase(phases: list[dict[str, Any]] | None) -> str | None:
    """The furthest done phase in the order of the list; None when none is done.

    Not the one with the latest date: the date of a paper is the ``Document.Datum`` the Kamer
    gives it, which may be the day it was received rather than made (the Nota n.a.v. het
    verslag of 36937 is dated four days after the bill passed as a hamerstuk).
    """
    done = [p["name"] for p in phases or [] if p["done"]]
    return done[-1] if done else None


def phase_props(
    case_kinds: list[str],
    docs: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """The props that record what a dossier is and how far its bill got."""
    kind, basis = dossier_kind(case_kinds, [d.get("kind") or "" for d in docs])
    phases = dossier_phases(kind, docs, activities, decisions)
    return {
        "kind": kind,
        "kind_basis": basis,
        "phases": phases,
        "current_phase": current_phase(phases),
    }


# ── When a dossier opened ─────────────────────────────────────────────────────

# Document.Soort of the royal message that brings a government bill to the Kamer.
ROYAL_MESSAGE_DOCUMENT = "Koninklijke boodschap"

OPENED_BY_FIRST_PAPER = "first_paper"
OPENED_BY_ROYAL_MESSAGE = "royal_message"
OPENED_BY_EARLIEST_RECORD = "earliest_record"


def last_activity(
    docs: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> str | None:
    """The day of the newest thing that happened in a dossier: a paper, an activity that
    took place (not one only planned, cancelled or moved) or a decision, as the Kamer dates
    them; None without any."""
    days = [
        *(d.get("date") for d in docs),
        *(
            a.get("date")
            for a in activities
            if a.get("status") not in ACTIVITY_NOT_HELD
        ),
        *(d.get("date") for d in decisions),
    ]
    return max((day for day in days if day), default=None)


def opened_on(
    number: str | None,
    suffix: str | None,
    docs: list[dict[str, Any]],
    activities: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    """``(opened_on, basis)`` of a dossier: the date of nr. 1 of its own numbering (a paper
    whose own dossier, ``Document.Kamerstukdossier``, is this one, with ``sequence`` 1),
    else of its Koninklijke boodschap, else of its earliest paper or activity; the date is
    the one the Kamer gives. ``(None, None)`` without any dated record."""
    own = [number, suffix or None]
    first = [
        d["date"]
        for d in docs
        if d.get("date") and d.get("sequence") == 1 and _own(d) == own
    ]
    if first:
        return min(first), OPENED_BY_FIRST_PAPER
    royal = [
        d["date"]
        for d in docs
        if d.get("date") and (d.get("kind") or "").startswith(ROYAL_MESSAGE_DOCUMENT)
    ]
    if royal:
        return min(royal), OPENED_BY_ROYAL_MESSAGE
    dated = [r["date"] for r in docs + activities if r.get("date")]
    return (min(dated), OPENED_BY_EARLIEST_RECORD) if dated else (None, None)


def _own(doc: dict[str, Any]) -> list[str | None] | None:
    own = doc.get("own")
    return [str(own[0]), own[1] or None] if own else None


# ── The title of a dossier ────────────────────────────────────────────────────


def select_title(
    props: dict[str, Any], docs: list[dict[str, Any]]
) -> tuple[str | None, str | None]:
    """``(title, source)`` where source is ``"dossier"`` or ``"document"``.

    A stored title equal to the dossier number is a placeholder, not a title. Without
    a real title the first title found is used, in order: bill, memorandum, any document.
    """
    stored = props.get("title")
    number = props.get("number") or ""
    if stored and stored != number:
        return stored, "dossier"
    for prefix in (BILL_DOCUMENT, MEMORANDUM_DOCUMENT, ""):
        for doc in docs:
            if doc.get("title") and (doc.get("kind") or "").startswith(prefix):
                return doc["title"], "document"
    return None, None


def dossier_display_name(number: str, suffix: str | None, title: str) -> str:
    """``Kamerstukdossier 36554-I: <title>``."""
    suffix = f"-{suffix}" if suffix else ""
    return f"Kamerstukdossier {number}{suffix}: {title}"


# ── How a dossier ended ───────────────────────────────────────────────────────

OUTCOME_ENACTED = "aangenomen"
OUTCOME_REJECTED = "verworpen"


# The outcome of a bill in the Eerste Kamer, as it writes it.
EK_ADOPTED = "Aangenomen"
EK_REJECTED = "Verworpen"


@dataclass(frozen=True)
class DossierOutcome:
    """Whether a dossier is closed, how it ended and on which date, the last decision of
    the Tweede Kamer on its bill, and its outcome in the Eerste Kamer."""

    closed: bool
    outcome: str | None = None
    closed_on: str | None = None
    tk_decision: dict[str, Any] | None = None
    ek_outcome: dict[str, Any] | None = None


def last_decision(bill_decisions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """``{kind, text, date}`` of the latest decision with a ``BesluitSoort`` on the
    dossier's own zaak (``Stemmen - zonder stemming aannemen``, ``Stemmen - aangenomen``,
    ``Stemmen - uitstellen``, …), as the Kamer writes it; None without one."""
    known = [d for d in bill_decisions if d.get("decision_kind")]
    if not known:
        return None
    last = max(known, key=lambda d: (d.get("date") or "", d["decision_kind"]))
    return {
        "kind": last["decision_kind"],
        "text": last.get("decision_text") or None,
        "date": last.get("date"),
    }


def ek_outcome(
    votes: list[dict[str, Any]], rejected: dict[str, Any] | None
) -> dict[str, Any] | None:
    """``{outcome, date, method, source_url, retrieved_on, decision}`` of a bill in the
    Eerste Kamer, as it writes them, from its votes (``normalize eerstekamer-votes``) and its
    list of rejected bills (*rejected*: ``{date, source_url, retrieved_on}``); None when
    neither decides it.

    The list of votes names a vote on a motion on a bill by the bill, so a vote
    ``Verworpen`` does not reject the bill: only the list of rejected bills does, with the
    vote ``Verworpen`` of that day as its vote when there is one. Otherwise the bill was
    adopted by its latest vote ``Aangenomen``. ``decision`` is the id of that vote.
    """
    if rejected and rejected.get("date"):
        day = rejected["date"]
        vote = next(
            (
                v
                for v in votes
                if v.get("result") == EK_REJECTED and v.get("date") == day
            ),
            None,
        )
        return {
            "outcome": EK_REJECTED,
            "date": day,
            "method": (vote or {}).get("method"),
            "source_url": (vote or {}).get("source_url") or rejected.get("source_url"),
            "retrieved_on": (vote or {}).get("retrieved_on")
            or rejected.get("retrieved_on"),
            "decision": (vote or {}).get("id"),
        }
    adopted = [v for v in votes if v.get("result") == EK_ADOPTED]
    if not adopted:
        return None
    vote = max(adopted, key=lambda v: (v.get("date") or "", v.get("id") or ""))
    return {
        "outcome": EK_ADOPTED,
        "date": vote.get("date"),
        "method": vote.get("method"),
        "source_url": vote.get("source_url"),
        "retrieved_on": vote.get("retrieved_on"),
        "decision": vote.get("id"),
    }


def derive_outcome(
    publications: list[dict[str, Any]],
    bill_decisions: list[dict[str, Any]],
    ek: dict[str, Any] | None = None,
) -> DossierOutcome:
    """How a dossier ended, from what the graph holds about it.

    * ``aangenomen``: an instrument is ``LEGISLATED_IN`` the dossier — the Staatsblad
      publication of the law, or a regulation whose metadata names the dossier. Closed on
      the first publication date (``date_published``, else ``date_signed``).
    * ``verworpen`` or ``aangenomen``: the outcome of the bill in the Eerste Kamer (*ek*,
      :func:`ek_outcome`). Closed on the day of that vote.
    * ``verworpen``: the last vote of the Tweede Kamer on the bill itself (a decision on
      its own zaak, of one of ``LEGISLATIVE_KINDS``, not on an amendment or a motion) did
      not pass. Closed on the date of that vote.

    Otherwise the dossier is open: a bill the Tweede Kamer passed waits for the Eerste
    Kamer, a withdrawn bill has no record of the Kamer that says so, and a dossier without a
    bill has no end in the graph.
    """
    decision = last_decision(bill_decisions)
    shown = {k: v for k, v in ek.items() if k != "decision"} if ek else None
    if publications:
        dates = [
            date
            for publication in publications
            if (
                date := publication.get("date_published")
                or publication.get("date_signed")
            )
        ]
        return DossierOutcome(
            True, OUTCOME_ENACTED, min(dates) if dates else None, decision, shown
        )
    if ek:
        outcome = OUTCOME_REJECTED if ek["outcome"] == EK_REJECTED else OUTCOME_ENACTED
        return DossierOutcome(True, outcome, ek.get("date"), decision, shown)
    votes = [d for d in bill_decisions if isinstance(d.get("passed"), bool)]
    if votes:
        last = max(votes, key=lambda vote: vote.get("date") or "")
        if last["passed"] is False:
            return DossierOutcome(True, OUTCOME_REJECTED, last.get("date"), decision)
    return DossierOutcome(False, tk_decision=decision)


def outcome_props(outcome: DossierOutcome) -> dict[str, Any]:
    """The props that record *outcome* on a dossier."""
    return {
        "closed": outcome.closed,
        "outcome": outcome.outcome,
        "closed_on": outcome.closed_on,
        "tk_decision": outcome.tk_decision,
        "ek_outcome": outcome.ek_outcome,
    }
