"""Government responses: ministries, cabinets and their bewindspersonen, commitments."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.params import MinistryKey, Post
from lawgraph.core.ministries import MINISTRY_BY_KEY, POSTS, protocol_rank
from lawgraph.core.tk_records import NO_DUE_DATE

# The statuses of ``core.tk_records.COMMITMENT_STATUS``.
DatePrecision = Literal["day", "month", "year"]
CommitmentStatus = Literal["open", "done", "partly_done", "unfulfilled", "lapsed"]


class MinistryDTO(BaseModel):
    """A ministry of ``core.ministries``; a former one names its successor and the last
    day it had its name."""

    model_config = ConfigDict(extra="forbid")

    key: MinistryKey
    name: str
    successor: MinistryKey | None = None
    until: str | None = None


class PersonRefDTO(BaseModel):
    """A member named from another node."""

    model_config = ConfigDict(extra="forbid")

    key: str
    name: str | None = None


class CabinetPartyDTO(BaseModel):
    """A party at least two members of the cabinet belonged to when their post began."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    short: str | None = None
    faction: str | None = Field(
        None, description="The faction key; null for a party from before the TK data."
    )


class CabinetSummaryDTO(BaseModel):
    """A cabinet in the list, with its counts."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., description="``rutte_iv``, ``den_uyl``.")
    name: str = Field(..., description="``kabinet-Rutte IV``.")
    from_date: str | None = None
    to_date: str | None = Field(None, description="Null while in office.")
    from_date_precision: DatePrecision | None = Field(
        None,
        description="How precisely ``from_date`` is known: ``year`` for most cabinets "
        "before 1945, whose date is then the first of January.",
    )
    to_date_precision: DatePrecision | None = None
    previous: str | None = Field(None, description="The key of the cabinet before it.")
    prime_minister: PersonRefDTO | None = None
    parties: list[CabinetPartyDTO] = Field(default_factory=list)
    factions: list[str] = Field(
        default_factory=list, description="The faction keys of its parties."
    )
    wikidata_id: str | None = None
    members: int = Field(0, description="The people who held a post in it.")
    bills: int = Field(
        0,
        description="Dossiers of track ``wetsvoorstel`` a bewindspersoon brought in "
        "while it was in office (``initiative`` false, ``cabinet`` this one).",
    )
    commitments: int = Field(0, description="Commitments made while it was in office.")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CabinetSummaryDTO:
        cabinet = row["cabinet"]
        props = cabinet.get("props") or {}
        return cls(
            key=cabinet["_key"],
            name=props.get("name") or cabinet["_key"],
            from_date=props.get("from_date"),
            to_date=props.get("to_date"),
            from_date_precision=props.get("from_date_precision"),
            to_date_precision=props.get("to_date_precision"),
            previous=props.get("previous"),
            prime_minister=row.get("prime_minister"),
            parties=[
                CabinetPartyDTO(
                    name=p.get("name"), short=p.get("short"), faction=p.get("faction")
                )
                for p in props.get("parties") or []
            ],
            factions=props.get("factions") or [],
            wikidata_id=props.get("wikidata_id"),
            members=int(row.get("members") or 0),
            bills=int(row.get("bills") or 0),
            commitments=int(row.get("commitments") or 0),
        )


class CabinetPostDTO(BaseModel):
    """One post a person held in the cabinet, with their counts within it."""

    model_config = ConfigDict(extra="forbid")

    member: PersonRefDTO
    post: Post | None = None
    function: str | None = Field(None, description="As Wikidata names the post.")
    from_date: str | None = None
    to_date: str | None = None
    dossiers: int = Field(
        0,
        description="Dossiers with a paper the person signed as bewindspersoon within the "
        "cabinet's period (counted per person, the same on each of their posts).",
    )
    bills: int = Field(0, description="Of those, dossiers of track ``wetsvoorstel``.")
    open_commitments: int = Field(
        0, description="Their commitments made under this cabinet and still open."
    )


class CabinetMinistryDTO(BaseModel):
    """The posts under one ministry; ``ministry`` null for a post that names none (the
    viceminister-president, a minister without a named portfolio)."""

    model_config = ConfigDict(extra="forbid")

    ministry: MinistryKey | None = None
    name: str | None = None
    posts: list[CabinetPostDTO]


class CabinetDetailDTO(CabinetSummaryDTO):
    """A cabinet with its bewindspersonen grouped by ministry: ministries in protocol
    order (Algemene Zaken, with the minister-president, first), within a ministry the
    posts in order (minister-president, minister, minister without portfolio,
    staatssecretaris), then by start. A person with two posts is listed under each."""

    ministries: list[CabinetMinistryDTO] = Field(default_factory=list)

    @classmethod
    def from_detail(cls, row: dict[str, Any]) -> CabinetDetailDTO:
        members = row.get("members") or []
        summary = CabinetSummaryDTO.from_row({**row, "members": len(members)})
        groups: dict[str | None, list[CabinetPostDTO]] = {}
        for item in members:
            for post in item.get("posts") or []:
                groups.setdefault(post.get("ministry"), []).append(
                    CabinetPostDTO(
                        member=item["member"],
                        post=post.get("post"),
                        function=post.get("function"),
                        from_date=post.get("from_date"),
                        to_date=post.get("to_date"),
                        dossiers=int(item.get("dossiers") or 0),
                        bills=int(item.get("bills") or 0),
                        open_commitments=int(item.get("open_commitments") or 0),
                    )
                )
        post_rank = {post: i for i, post in enumerate(POSTS)}
        ministries = [
            CabinetMinistryDTO(
                ministry=MinistryKey(key) if key else None,
                name=MINISTRY_BY_KEY[key].name if key in MINISTRY_BY_KEY else None,
                posts=sorted(
                    posts,
                    key=lambda p: (
                        post_rank.get(p.post or "", len(POSTS)),
                        p.from_date or "",
                        p.member.name or "",
                    ),
                ),
            )
            for key, posts in sorted(groups.items(), key=lambda g: protocol_rank(g[0]))
        ]
        return cls(**summary.model_dump(), ministries=ministries)


class CommitmentDossierDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    number: str | None = None
    title: str | None = None


class CommitmentActivityDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    date: str | None = None
    number: str | None = None


class CommitmentMemberDTO(PersonRefDTO):
    """Who made the commitment, and the role they made it in as the source writes it."""

    function: str | None = None


class CommitmentDTO(BaseModel):
    """A commitment (toezegging) of a bewindspersoon to the Tweede Kamer."""

    model_config = ConfigDict(extra="forbid")

    key: str
    text: str | None = None
    status: CommitmentStatus | None = None
    date: str | None = Field(None, description="The day it was made.")
    expected_resolution: str | None = Field(
        None, description="The day it is due; null when the Kamer names none."
    )
    minister_name: str | None = Field(None, description="As the source writes it.")
    member: CommitmentMemberDTO | None = Field(
        None, description="The member who made it; null when no member fits the name."
    )
    post: Post | None = None
    ministry: MinistryKey | None = None
    cabinet: str | None = Field(None, description="The cabinet in office that day.")
    dossiers: list[CommitmentDossierDTO] = Field(default_factory=list)
    activity: CommitmentActivityDTO | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CommitmentDTO:
        commitment = row["commitment"]
        props = commitment.get("props") or {}
        member = row.get("member")
        due = props.get("expected_resolution")
        return cls(
            key=commitment["_key"],
            text=props.get("text"),
            status=(
                props.get("status")
                if props.get("status") in get_args(CommitmentStatus)
                else None
            ),
            date=props.get("made_on"),
            expected_resolution=due if due and due != NO_DUE_DATE else None,
            minister_name=props.get("minister_name"),
            member=(
                CommitmentMemberDTO(**member, function=props.get("minister_role"))
                if member
                else None
            ),
            post=props.get("post"),
            ministry=props.get("ministry"),
            cabinet=props.get("cabinet"),
            dossiers=[CommitmentDossierDTO(**d) for d in row.get("dossiers") or []],
            activity=row.get("activity"),
        )


class CommitmentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., description="Matching commitments, whatever the page.")
    items: list[CommitmentDTO]
