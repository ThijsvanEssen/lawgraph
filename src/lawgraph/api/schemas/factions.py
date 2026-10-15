"""Faction responses."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import (
    DossierNameDTO,
    PathSource,
    StrictModel,
    WithPath,
)
from lawgraph.api.schemas.ek_source import (
    OBSERVED_FROM,
    OBSERVED_UNTIL,
    EkSourceDTO,
    ek_source,
)
from lawgraph.config.constants import Chamber
from lawgraph.core.ek_votes import VoteLabel


class FactionDetailDTO(StrictModel):
    """Response for GET /api/factions/{key} — the node as stored."""

    id: str
    key: str
    type: str = Field(..., description="Node type, e.g. ``faction``.")
    labels: list[str]
    props: dict[str, Any] | None = None


class FactionBoardSeatDTO(StrictModel):
    """A seat on the board of a faction of the Eerste Kamer, as its page gives it."""

    function: str = Field(..., description="``fractievoorzitter``, ``penningmeester``.")
    name: str | None = None
    member: str | None = Field(None, description="The member key.")
    since: str | None = Field(None, description="The day the page gives: ``sinds``.")


class FactionDTO(WithPath):
    """A parliamentary party."""

    path_source = PathSource("factions")

    id: str
    key: str
    chamber: Chamber = "TK"
    observed_from: str | None = Field(None, description=OBSERVED_FROM)
    observed_until: str | None = Field(None, description=OBSERVED_UNTIL)
    board: list[FactionBoardSeatDTO] = Field(
        default_factory=list, description="Of the Eerste Kamer: its board."
    )
    source: EkSourceDTO | None = Field(
        None, description="Of the Eerste Kamer: the page it was read from."
    )
    name: str | None = None
    abbreviation: str | None = None
    aliases: list[str] = []
    active: bool = True
    seats: int | None = None
    active_from: str | None = None
    active_until: str | None = Field(
        None,
        description="The last day, inclusive (the Kamer's TotEnMet); null while open.",
    )
    member_count: int = 0

    @classmethod
    def from_document(cls, doc: dict[str, Any], *, member_count: int = 0) -> FactionDTO:
        props = doc.get("props") or {}
        active = bool(props.get("active", True))
        seats = props.get("seats")
        # A seated party always has a seat count; default to 0 rather than
        # null so callers can always compare numerically.
        if active and seats is None:
            seats = 0
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            name=props.get("name"),
            abbreviation=props.get("abbreviation"),
            aliases=list(props.get("aliases") or []),
            active=active,
            seats=seats,
            active_from=props.get("active_from"),
            active_until=props.get("active_until"),
            member_count=member_count,
            chamber=props.get("chamber") or "TK",
            observed_from=props.get("observed_from"),
            observed_until=props.get("observed_until"),
            board=[FactionBoardSeatDTO(**b) for b in props.get("board") or []],
            source=ek_source(props),
        )


class EkFactionVoteDTO(StrictModel):
    """How a faction of the Eerste Kamer voted on one vote of its list."""

    decision_id: str
    decision_key: str
    date: str | None = None
    subject: str | None = None
    dossier_numbers: list[str] = []
    dossiers: list[DossierNameDTO] = Field(
        default_factory=list,
        description="The names of ``dossier_numbers``, in their order: ``number``, "
        "``short_title``, ``title`` as ``/api/dossiers`` gives them.",
    )
    result: str | None = Field(None, description="``Aangenomen``, ``Verworpen``.")
    method: str | None = None
    bill_decision: bool | None = Field(
        None,
        description="Whether it is the vote that decided the bill (else a vote on a "
        "motion on it).",
    )
    choice: VoteLabel = Field(
        ..., description="As the list of the Eerste Kamer names the faction's vote."
    )


class EkFactionVotesResponse(StrictModel):
    """The votes of a faction of the Eerste Kamer, newest first."""

    faction_key: str
    total: int = Field(..., description="The votes that name the faction.")
    counts: dict[str, int] = Field(
        default_factory=dict,
        description="Per choice (``voor``, ``tegen``, ``aantekening gevraagd``), over "
        "every vote that names the faction.",
    )
    items: list[EkFactionVoteDTO] = []
    source: EkSourceDTO
