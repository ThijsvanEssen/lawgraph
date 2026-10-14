"""DTOs of ``GET /api/activities/{key}`` and ``/records``: one activity of a chamber (a
debate, a hearing, a vote) and what was made in it."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import (
    DossierNameDTO,
    StrictModel,
    WithPath,
    dossier_names_of,
)
from lawgraph.api.schemas.dossiers import TimelineCommitteeDTO
from lawgraph.config.constants import Chamber
from lawgraph.core.documents import chamber_of
from lawgraph.core.models import NodeType
from lawgraph.core.tk_links import tk_url
from lawgraph.core.tk_records import due_date

_STATUS = (
    "``Activiteit.Status`` as the source writes it: ``Gepland`` (still to come, also when "
    "its date has passed), ``Uitgevoerd``, ``Geannuleerd``, ``Verplaatst``, "
    "``Vervallen``; null when the source gives none (the Eerste Kamer gives none)."
)


class ActivityMoveDTO(WithPath):
    """An activity that took the place of another, or whose place another took
    (``CONTINUES``, ``Activiteit.VervangenDoor``)."""

    path_collection = "activities"

    id: str
    key: str
    number: str | None = None
    date: str | None = None
    status: str | None = Field(None, description=_STATUS)


class ActivityDTO(WithPath):
    """One activity: what it is, when, who leads it and what it is about."""

    path_collection = "activities"

    id: str
    key: str
    number: str | None = Field(
        None, description="``Activiteit.Nummer`` (``2026A01323``), its address."
    )
    chamber: Chamber | None = None
    kind: str | None = Field(
        None,
        description="As the source writes it: ``Wetgevingsoverleg``, ``Commissiedebat``, "
        "``Plenair debat (wetgeving)``, ``Stemmingen``.",
    )
    date: str | None = Field(None, description="The day it was (to be) held.")
    status: str | None = Field(None, description=_STATUS)
    agenda_title: str | None = Field(
        None, description="Its subject (``Activiteit.Onderwerp``)."
    )
    tk_url: str | None = Field(
        None, description="Its page on tweedekamer.nl, by its number."
    )
    committee: TimelineCommitteeDTO | None = Field(
        None,
        description="The committee that leads it (``LED_BY``); null for a plenary one.",
    )
    dossier_numbers: list[str] = Field(
        default_factory=list, description="The dossiers of the cases on its agenda."
    )
    dossiers: list[DossierNameDTO] = Field(
        default_factory=list,
        description="The names of ``dossier_numbers``, in their order: ``number``, "
        "``short_title``, ``title`` as ``/api/dossiers`` gives them.",
    )
    moved_from: list[ActivityMoveDTO] = Field(
        default_factory=list,
        description="The activities it took the place of: moved to it (it ``CONTINUES`` "
        "them).",
    )
    moved_to: list[ActivityMoveDTO] = Field(
        default_factory=list,
        description="The activities that took its place: it was moved to them.",
    )

    @classmethod
    def from_row(
        cls, row: dict[str, Any], names: dict[str, dict[str, Any]]
    ) -> ActivityDTO:
        """From a row of ``get_activity`` and the names of the dossiers
        (``load_dossier_names``)."""
        props = row.get("props") or {}
        numbers = [str(n) for n in props.get("dossier_numbers") or [] if n]
        committee = row.get("committee")
        return cls(
            id=row["id"],
            key=row["key"],
            number=props.get("number") or None,
            chamber=chamber_of(row.get("labels")),
            kind=props.get("kind") or None,
            date=props.get("date"),
            status=props.get("status"),
            agenda_title=props.get("agenda_title") or None,
            tk_url=tk_url(NodeType.ACTIVITY.value, props),
            committee=TimelineCommitteeDTO(**committee) if committee else None,
            dossier_numbers=numbers,
            dossiers=dossier_names_of(numbers, names),
            moved_from=[ActivityMoveDTO(**m) for m in row.get("moved_from") or []],
            moved_to=[ActivityMoveDTO(**m) for m in row.get("moved_to") or []],
        )


class ActivityPaperDTO(WithPath):
    """A paper made in the activity: its record (a stenogram, a verslag), its convocatie,
    or a motion submitted in it."""

    path_collection = "documents"

    id: str
    key: str
    kind: str | None = Field(
        None, description="As the chamber writes it: ``Stenogram``."
    )
    date: str | None = None
    title: str | None = None
    dossier_number: str | None = None
    dossier_suffix: str | None = None
    sequence: int | None = Field(
        None, description="Its number in its dossier (nr. 32); null for none."
    )
    dictum: str | None = Field(
        None, description="Of a motion, what it asks or says; null for any other paper."
    )
    has_text: bool = Field(False, description="Whether its text is in the data.")


class ActivityCommitmentDTO(WithPath):
    """A commitment made in the activity."""

    path_collection = "commitments"

    id: str
    key: str
    number: str | None = Field(None, description="``TZ202604-064``.")
    text: str | None = None
    status: str | None = Field(None, description="``Toezegging.Status``.")
    registered_on: str | None = Field(
        None, description="The day the Kamer registered it (``Aanmaakdatum``)."
    )
    expected_resolution: str | None = Field(
        None, description="The day it is due; null when the Kamer names none."
    )
    minister_name: str | None = Field(None, description="As the source writes it.")
    minister_role: str | None = Field(None, description="As the source writes it.")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ActivityCommitmentDTO:
        due = row.get("expected_resolution")
        return cls(
            id=row["id"],
            key=row["key"],
            number=row.get("number"),
            text=row.get("text"),
            status=row.get("status"),
            registered_on=row.get("made_on"),
            expected_resolution=due_date(due),
            minister_name=row.get("minister_name"),
            minister_role=row.get("minister_role"),
        )


class ActivityDecisionDTO(WithPath):
    """A decision taken in the activity (on an item of its agenda)."""

    path_collection = "decisions"

    id: str
    key: str
    date: str | None = None
    subject: str | None = None
    kind: str | None = Field(
        None, description="What was decided on: the ``Zaak.Soort`` (``Motie``)."
    )
    decision_kind: str | None = Field(
        None, description="``BesluitSoort``: ``Stemmen - aangenomen``."
    )
    decision_text: str | None = None
    passed: bool | None = None
    tally: dict[str, int] = Field(
        default_factory=dict, description="Seats per choice (``Voor``, ``Tegen``)."
    )


class ActivityCaseDTO(WithPath):
    """A case (zaak) on the agenda of the activity."""

    path_collection = "cases"

    id: str
    key: str
    number: str | None = Field(None, description="``2026Z05830``.")
    kind: str | None = Field(
        None, description="``Zaak.Soort``: ``Motie``, ``Wetgeving``."
    )
    title: str | None = None


class ActivityRecordsResponse(StrictModel):
    """What was made in an activity (``MADE_IN``) and what was on its agenda."""

    activity_id: str
    documents: list[ActivityPaperDTO] = Field(
        default_factory=list,
        description="Its papers but the motions: the stenogram and the verslag of a debate "
        "(``Document.Activiteit``), its convocatie; oldest first.",
    )
    motions: list[ActivityPaperDTO] = Field(
        default_factory=list,
        description="The motions submitted in it, by their number in the dossier.",
    )
    commitments: list[ActivityCommitmentDTO] = Field(
        default_factory=list, description="The commitments made in it, by number."
    )
    decisions: list[ActivityDecisionDTO] = Field(
        default_factory=list,
        description="The decisions taken in it (``Agendapunt.Activiteit``), in the order "
        "of its agenda.",
    )
    cases: list[ActivityCaseDTO] = Field(
        default_factory=list,
        description="The cases on its agenda (``ABOUT``), by number: of a debate the bill "
        "and the motions submitted in it.",
    )

    @classmethod
    def from_row(cls, activity_id: str, row: dict[str, Any]) -> ActivityRecordsResponse:
        """From the row of ``get_activity_records``."""
        return cls(
            activity_id=activity_id,
            documents=[
                ActivityPaperDTO(**_paper(p)) for p in row.get("documents") or []
            ],
            motions=[ActivityPaperDTO(**_paper(p)) for p in row.get("motions") or []],
            commitments=[
                ActivityCommitmentDTO.from_row(c) for c in row.get("commitments") or []
            ],
            decisions=[
                ActivityDecisionDTO(**{**d, "tally": d.get("tally") or {}})
                for d in row.get("decisions") or []
            ],
            cases=[ActivityCaseDTO(**c) for c in row.get("cases") or []],
        )


def _paper(row: dict[str, Any]) -> dict[str, Any]:
    sequence = row.get("sequence")
    return {
        **row,
        "sequence": sequence if isinstance(sequence, int) else None,
        "has_text": bool(row.get("has_text")),
    }
