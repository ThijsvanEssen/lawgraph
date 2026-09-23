"""Dossier stage / kind classification (pure functions, no I/O).

Shared by the tk_dossiers normalize pipeline (which stores the result on
dossier nodes) and the dossier API (which derives it on the fly), so it lives in
core rather than in either of those layers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# The stages of a bill, in the order it passes them.
DOSSIER_STAGES: tuple[str, ...] = (
    "wetsvoorstel",
    "mvt",
    "advies_rvs",
    "verslag",
    "nota_naar_aanleiding_van_verslag",
    "amendementen",
    "behandeling",
    "stemming",
    "afgehandeld",
)

# The kinds of dossier that are a bill and so pass the stages above; the others (a policy
# dossier of letters and motions, an initiatiefnota) only end.
BILL_TRACKS = frozenset(
    {"wetsvoorstel", "initiatiefwetsvoorstel", "begroting", "verdrag"}
)

# Document.Soort by its beginning. "Verslag" is the stage on its own or for a bill only:
# a "Verslag van een commissiedebat" reports on a meeting.
_DOCUMENT_STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("wetsvoorstel", ("voorstel van wet", "koninklijke boodschap")),
    ("mvt", ("memorie van toelichting",)),
    ("advies_rvs", ("advies afdeling advisering raad van state", "nader rapport")),
    (
        "verslag",
        ("verslag (initiatief)wetsvoorstel", "verslag houdende een lijst van vragen"),
    ),
    ("nota_naar_aanleiding_van_verslag", ("nota n.a.v. het",)),
    ("amendementen", ("amendement", "nota van wijziging")),
    ("behandeling", ("motie", "verslag van een wetgevingsoverleg")),
    ("stemming", ("stemmingslijst",)),
)

# Activiteit.Soort, whole.
_ACTIVITY_STAGES: dict[str, str] = {
    "inbreng verslag (wetsvoorstel)": "verslag",
    "wetgevingsoverleg": "behandeling",
    "plenair debat (wetgeving)": "behandeling",
    "plenair debat (initiatiefwetgeving)": "behandeling",
    "stemmingen": "stemming",
    "hamerstukken": "stemming",
}

# Zaak.Soort by its beginning.
_CASE_STAGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("wetsvoorstel", ("wetgeving", "initiatiefwetgeving", "begroting")),
    ("nota_naar_aanleiding_van_verslag", ("nota n.a.v. het",)),
    ("amendementen", ("amendement", "nota van wijziging")),
    ("behandeling", ("motie",)),
)


def _by_prefix(
    kind: str | None, table: tuple[tuple[str, tuple[str, ...]], ...]
) -> str | None:
    if not kind:
        return None
    s = kind.lower()
    return next((stage for stage, prefixes in table if s.startswith(prefixes)), None)


def classify_document_kind(kind: str | None) -> str | None:
    """The bill stage a Document.Soort marks, or None when it marks none."""
    if kind and kind.lower() == "verslag":
        return "verslag"
    return _by_prefix(kind, _DOCUMENT_STAGES)


def classify_activity_kind(kind: str | None) -> str | None:
    """The bill stage an Activiteit.Soort marks, or None when it marks none."""
    return _ACTIVITY_STAGES.get((kind or "").lower())


def classify_case_kind(kind: str | None) -> str | None:
    """The bill stage a Zaak.Soort marks, or None when it marks none.

    Coarser than ``classify_document_kind`` and without a date, but available for a
    dossier that has no documents linked.
    """
    return _by_prefix(kind, _CASE_STAGES)


def classify_track_kind(
    case_kinds: list[str] | None,
    *,
    title: str | None = None,
    document_kinds: list[str] | None = None,
) -> str | None:
    """Pick the canonical *kind* of a dossier (its legislative path).

    This answers "what kind of dossier is this?" — separate from
    ``current_stage`` (the latest stage). A dossier whose own cases include
    'Initiatiefwetgeving' is an initiatiefwetsvoorstel for its entire life,
    regardless of whether the current stage is 'verslag' or 'stemming'.

    Returns ``None`` only when no signal at all is available.
    """
    kinds = {s.lower() for s in (case_kinds or []) if s}
    documents = [s.lower() for s in (document_kinds or []) if s]
    if "initiatiefwetgeving" in kinds or any(
        s.startswith("voorstel van wet (initiatiefvoorstel)") for s in documents
    ):
        return "initiatiefwetsvoorstel"
    for track, case_kind in (
        ("wetsvoorstel", "wetgeving"),
        ("begroting", "begroting"),
        ("verdrag", "verdrag"),
        ("initiatiefnota", "initiatiefnota"),
    ):
        if case_kind in kinds:
            return track
    if "initiatiefnota" in documents:
        return "initiatiefnota"
    if any(s.startswith("voorstel van wet") for s in documents):
        return "wetsvoorstel"
    return _track_from_title(title) or (
        ("motie" if "motie" in kinds else "overig") if kinds else None
    )


def _track_from_title(title: str | None) -> str | None:
    t = (title or "").lower()
    if t.startswith("voorstel van wet van het lid") or "initiatiefwetsvoorstel" in t:
        return "initiatiefwetsvoorstel"
    if t.startswith(("voorstel van wet", "wetsvoorstel")):
        return "wetsvoorstel"
    if "begroting" in t:
        return "begroting"
    return None


# ── deriving a dossier's stage and title from its documents / activities / votes ──


@dataclass(frozen=True)
class StageSignals:
    """First and last date per stage, and whether any signal was found at all."""

    first: dict[str, str]
    last: dict[str, str]
    any_signal: bool


def accumulate_stage_signals(
    docs: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    case_kinds: list[str],
) -> StageSignals:
    """Combine every kind of evidence into per-stage first/last dates.

    Documents are the richest signal, then activities (by their own kind), then the
    dossier-level ``Zaak.Soort`` roll-up (presence only, no date), and finally votes
    (their presence implies ``stemming``).
    """
    first: dict[str, str] = {}
    last: dict[str, str] = {}
    any_signal = False

    def record(stage: str | None, date: str | None) -> None:
        nonlocal any_signal
        if stage is None:
            return
        any_signal = True
        d = date or ""
        if stage not in first or (d and d < first[stage]):
            first[stage] = d
        if stage not in last or (d and d > last[stage]):
            last[stage] = d

    for doc in docs:
        record(classify_document_kind(doc.get("kind")), doc.get("date"))
    for act in activities:
        record(classify_activity_kind(act.get("kind")), act.get("date"))
    for kind in case_kinds:
        stage = classify_case_kind(kind)
        if stage is not None and stage not in first:
            any_signal = True
            first[stage] = ""
            last[stage] = ""
    if decisions:
        dates = [v["date"] for v in decisions if v.get("date")]
        record("stemming", min(dates) if dates else None)
        if dates:
            last["stemming"] = max(dates)
    return StageSignals(first, last, any_signal)


def dossier_stages(
    track: str | None,
    docs: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    case_kinds: list[str],
    *,
    closed: bool,
) -> tuple[str | None, list[str]]:
    """``(current stage or None, stages present in chronological order)``.

    Only a bill passes stages; any other dossier is ``afgehandeld`` once closed and
    has no stage before that.
    """
    if track in BILL_TRACKS:
        signals = accumulate_stage_signals(docs, activities, decisions, case_kinds)
    else:
        signals = StageSignals({}, {}, any_signal=False)
    return pick_current_stage(signals, closed=closed)


def pick_current_stage(
    signals: StageSignals, *, closed: bool
) -> tuple[str | None, list[str]]:
    """``(current stage or None, stages present in chronological order)``.

    A closed dossier is ``afgehandeld``; otherwise the stage with the latest date,
    or ``None`` when there was no evidence.
    """
    stages = sorted(
        signals.first,
        key=lambda st: (signals.first[st] or "", DOSSIER_STAGES.index(st)),
    )
    if closed:
        return "afgehandeld", (
            stages if "afgehandeld" in stages else [*stages, "afgehandeld"]
        )
    if signals.any_signal:
        current = max(
            signals.last,
            key=lambda st: (signals.last[st] or "", DOSSIER_STAGES.index(st)),
        )
        return current, stages
    return None, stages


def select_title(
    props: dict[str, Any], docs: list[dict[str, Any]]
) -> tuple[str | None, str | None]:
    """``(title, source)`` where source is ``"dossier"`` or ``"document"``.

    A stored title equal to the dossier number is a placeholder, not a title. Without
    a real title the first title found is used, in order: bill, MvT, any document.
    """
    stored = props.get("title")
    number = props.get("number") or ""
    if stored and stored != number:
        return stored, "dossier"
    for stage in ("wetsvoorstel", "mvt", None):
        for doc in docs:
            if doc.get("title") and (
                stage is None or classify_document_kind(doc.get("kind")) == stage
            ):
                return doc["title"], "document"
    return None, None


def dossier_display_name(number: str, suffix: str | None, title: str) -> str:
    """``Kamerstukdossier 36554-I: <title>``."""
    suffix = f"-{suffix}" if suffix else ""
    return f"Kamerstukdossier {number}{suffix}: {title}"


# ── how a dossier ended ───────────────────────────────────────────────────────

OUTCOME_ENACTED = "aangenomen"
OUTCOME_REJECTED = "verworpen"
OUTCOME_WITHDRAWN = "ingetrokken"

# The Zaak.Soort of the case of a bill itself, next to the cases of its amendments and
# motions in the same dossier.
BILL_CASE_KINDS: tuple[str, ...] = ("Wetgeving", "Initiatiefwetgeving")

# "Brief houdende intrekking van het wetsvoorstel", "... houdende overname en intrekking
# van het voorstel", "... overname van de verdediging en intrekking van het
# initiatiefvoorstel", "Intrekking wetsvoorstel ...".
_WITHDRAWAL = re.compile(
    r"\bintrekking\s+(?:van\s+het\s+)?(?:initiatief|wets)?(?:wets)?voorstel", re.I
)
# A letter about a withdrawal that does not withdraw: asked for, announced, taken back,
# a report on the letter or a letter from a committee.
_NOT_A_WITHDRAWAL = re.compile(
    r"verzoek\s+tot|voornemen|aankondiging|herroeping|\bniet\b|verslag|vragen", re.I
)


@dataclass(frozen=True)
class DossierOutcome:
    """Whether a dossier is closed, how it ended and on which date."""

    closed: bool
    outcome: str | None = None
    closed_on: str | None = None


OPEN = DossierOutcome(closed=False)


def is_withdrawal_letter(letter: dict[str, Any]) -> bool:
    """Whether a document is the letter that withdraws the bill of its dossier.

    A letter of the government or of the members who proposed it, on the case of the bill
    itself, whose subject says it withdraws the bill.
    """
    kind = (letter.get("kind") or "").lower()
    if not kind.startswith("brief") or "commissie" in kind:
        return False
    if not set(letter.get("case_kinds") or []) & set(BILL_CASE_KINDS):
        return False
    subject = letter.get("subject") or ""
    return bool(_WITHDRAWAL.search(subject)) and not _NOT_A_WITHDRAWAL.search(subject)


def derive_outcome(
    publications: list[dict[str, Any]],
    letters: list[dict[str, Any]],
    bill_votes: list[dict[str, Any]],
) -> DossierOutcome:
    """How a dossier ended, from what the graph holds about it.

    * ``aangenomen``: an instrument is ``LEGISLATED_IN`` the dossier — the Staatsblad
      publication of the law, or a regulation whose metadata names the dossier. Closed on
      the first publication date (``date_published``, else ``date_signed``).
    * ``ingetrokken``: the bill was withdrawn by letter (:func:`is_withdrawal_letter`).
      Closed on the date of the letter.
    * ``verworpen``: the last vote of the Tweede Kamer on the bill itself (a decision on
      its ``Wetgeving`` case, not on an amendment or a motion) did not pass. Closed on the
      date of that vote.

    Otherwise the dossier is open: a bill the Tweede Kamer passed still waits for the
    Eerste Kamer and the Staatsblad, and a dossier without a bill has no end in the graph.
    """
    if publications:
        dates = [
            date
            for publication in publications
            if (
                date := publication.get("date_published")
                or publication.get("date_signed")
            )
        ]
        return DossierOutcome(True, OUTCOME_ENACTED, min(dates) if dates else None)
    withdrawals = [letter for letter in letters if is_withdrawal_letter(letter)]
    if withdrawals:
        dates = [letter["date"] for letter in withdrawals if letter.get("date")]
        return DossierOutcome(True, OUTCOME_WITHDRAWN, min(dates) if dates else None)
    if bill_votes:
        last = max(bill_votes, key=lambda vote: vote.get("date") or "")
        if last.get("passed") is False:
            return DossierOutcome(True, OUTCOME_REJECTED, last.get("date"))
    return OPEN
