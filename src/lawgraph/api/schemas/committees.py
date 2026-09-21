"""Committee, member and faction responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.dossiers import DossierSummaryDTO


class MemberVoteDTO(BaseModel):
    """One vote a member took part in.

    ``party`` is the party they sat for on ``date``, which may differ from
    the party they sit for now.
    """

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(..., description="Arango _id of the decision.")
    decision_key: str
    external_id: str | None = Field(
        None, description="TK Besluit identifier of the decision."
    )
    date: str | None = Field(None, description="Date of the vote (YYYY-MM-DD).")
    subject: str | None = None
    passed: bool | None = None
    choice: str = Field(
        ..., description="The vote as the source wrote it: Voor, Tegen, Onthouden, …"
    )
    seats: int | None = Field(
        None, description="Seats behind this vote; 1 on a roll-call."
    )
    party: str | None = None
    faction_key: str | None = None


class MemberVotesResponse(BaseModel):
    """Response for GET /api/members/{key}/votes."""

    model_config = ConfigDict(extra="forbid")

    member_id: str = Field(..., description="Arango _id of the member.")
    count: int = Field(..., description="Votes returned; may be fewer than the total.")
    votes: list[MemberVoteDTO]


class TouchedInstrumentDTO(BaseModel):
    """One law an actor proposes changes to, with how often they do."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Arango _id of the instrument.")
    key: str
    display_name: str | None = None
    title: str | None = None
    short_title: str | None = None
    citation_title: str | None = None
    bwb_id: str | None = None
    celex: str | None = None
    count: int = Field(
        ..., description="Distinct documents by this actor that change the law."
    )


class TouchedInstrumentsResponse(BaseModel):
    """Wrapper for an actor's touched-instruments list."""

    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(..., description="Arango _id of the member or faction.")
    count: int = Field(
        ..., description="Instruments returned; may be fewer than the total."
    )
    items: list[TouchedInstrumentDTO]


class FactionDetailDTO(BaseModel):
    """Response for GET /api/factions/{key} — the node as stored."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    type: str = Field(..., description="Node type, e.g. ``faction``.")
    labels: list[str]
    props: dict[str, Any] | None = None


class CommitteeDTO(BaseModel):
    """A parliamentary committee.

    ``kind`` distinguishes standing ('vast'), temporary ('tijdelijk'),
    special ('bijzonder') and inquiry ('parlementaire_enquete') committees.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    name: str | None = None
    abbreviation: str | None = None
    slug: str | None = None
    kind: str | None = None
    active_dossier_count: int = 0

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], *, active_dossier_count: int = 0
    ) -> CommitteeDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            name=props.get("name"),
            abbreviation=props.get("abbreviation"),
            slug=props.get("slug"),
            kind=props.get("type"),
            active_dossier_count=active_dossier_count,
        )


class FactionDTO(BaseModel):
    """A parliamentary party."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    name: str | None = None
    abbreviation: str | None = None
    aliases: list[str] = []
    active: bool = True
    seats: int | None = None
    active_from: str | None = None
    active_until: str | None = None
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
        )


class FactionMembershipDTO(BaseModel):
    """One stretch of a member's membership of a faction."""

    model_config = ConfigDict(extra="forbid")

    faction_id: str
    faction_key: str
    name: str | None = None
    abbreviation: str | None = None
    aliases: list[str] = []
    from_date: str | None = None
    to_date: str | None = None
    role: str | None = None


class MemberDTO(BaseModel):
    """A member of parliament or a minister.

    ``active`` means they hold an open faction membership — currently seated.
    ``party`` comes from that same membership, so the two always agree.

    ``from_date`` / ``to_date`` are only filled when the member is returned
    as part of a committee, where they carry that committee seat's period.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    name: str | None = None
    party: str | None = None
    active: bool = False
    faction_memberships: list[FactionMembershipDTO] = []
    from_date: str | None = None
    to_date: str | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> MemberDTO:
        props = doc.get("props") or {}
        memberships = [
            FactionMembershipDTO(**m) for m in (props.get("faction_memberships") or [])
        ]
        open_memberships = [m for m in memberships if m.to_date is None]
        current = (
            open_memberships[-1]
            if open_memberships
            else (
                max(memberships, key=lambda m: m.from_date or "")
                if memberships
                else None
            )
        )
        party = (current.abbreviation or current.name) if current else None

        return cls(
            id=doc["_id"],
            key=doc["_key"],
            name=props.get("name"),
            party=party or props.get("party"),
            active=bool(open_memberships),
            faction_memberships=memberships,
            from_date=doc.get("from_date"),
            to_date=doc.get("to_date"),
        )


class CommitteeWithMembersDTO(CommitteeDTO):
    """A committee and its members, without the dossiers payload."""

    model_config = ConfigDict(extra="forbid")

    members: list[MemberDTO] = []

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], *, active_dossier_count: int = 0
    ) -> CommitteeWithMembersDTO:
        props = doc.get("props") or {}
        stored = props.get("active_dossier_count")
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            name=props.get("name"),
            abbreviation=props.get("abbreviation"),
            slug=props.get("slug"),
            kind=props.get("type"),
            active_dossier_count=(
                stored if stored is not None else active_dossier_count
            ),
            members=[MemberDTO.from_document(m) for m in doc.get("members") or []],
        )


class CommitteeDetailDTO(CommitteeDTO):
    """A committee with its members and a page of the dossiers it leads.

    ``dossiers`` is one page; ``dossier_total`` counts every dossier that matches the
    ``status`` filter, and ``active_dossier_count`` the open ones whatever the filter.
    """

    model_config = ConfigDict(extra="forbid")

    members: list[MemberDTO] = []
    dossiers: list[DossierSummaryDTO] = []
    dossier_total: int = Field(
        0, description="Dossiers matching ``status``, independent of limit and offset."
    )

    @classmethod
    def from_detail_document(cls, doc: dict[str, Any]) -> CommitteeDetailDTO:
        props = doc.get("props") or {}
        dossiers = [
            DossierSummaryDTO.from_document(d) for d in doc.get("dossiers") or []
        ]
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            name=props.get("name"),
            abbreviation=props.get("abbreviation"),
            slug=props.get("slug"),
            kind=props.get("type"),
            active_dossier_count=int(doc.get("open_dossier_count") or 0),
            members=[MemberDTO.from_document(m) for m in doc.get("members") or []],
            dossiers=dossiers,
            dossier_total=int(doc.get("dossier_total") or 0),
        )


class CommitteeActivityDTO(BaseModel):
    """One activity (debate, hearing) a committee leads."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    date: str | None = Field(None, description="YYYY-MM-DD.")
    kind: str | None = Field(
        None, description="The source's ``Soort``, e.g. Commissiedebat."
    )
    agenda_title: str | None = None
    dossier_numbers: list[str] = Field(
        default_factory=list, description="Dossiers on the agenda of the activity."
    )


class CommitteeActivitiesResponse(BaseModel):
    """A page of a committee's activities, newest first."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(
        ..., description="Activities of the committee, independent of limit and offset."
    )
    items: list[CommitteeActivityDTO]


class ActorDossierDTO(DossierSummaryDTO):
    """A dossier a member or faction authored documents in.

    ``roles`` are the distinct ``AUTHORED`` roles as the source wrote them
    (``Eerste ondertekenaar``, ``Mede ondertekenaar``, ...); ``document_count`` the distinct
    documents authored in the dossier.
    """

    model_config = ConfigDict(extra="forbid")

    roles: list[str] = Field(default_factory=list)
    document_count: int = 0

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ActorDossierDTO:
        return cls(
            **DossierSummaryDTO.from_document(row["dossier"]).model_dump(),
            roles=list(row.get("roles") or []),
            document_count=int(row.get("document_count") or 0),
        )


class ActorDossiersResponse(BaseModel):
    """A page of the dossiers a member or faction authored documents in."""

    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(..., description="Arango _id of the member or faction.")
    total: int = Field(..., description="Dossiers, independent of limit and offset.")
    items: list[ActorDossierDTO]
