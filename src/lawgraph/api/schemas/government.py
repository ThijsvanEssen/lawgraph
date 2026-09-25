"""Government responses: ministries, cabinets and their bewindspersonen, commitments."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.params import MinistryKey, Post
from lawgraph.api.schemas.committees import PartyRefDTO
from lawgraph.core.ministries import MINISTRY_BY_KEY, POSTS, protocol_rank
from lawgraph.core.tk_records import NO_DUE_DATE

# The statuses of ``core.tk_records.COMMITMENT_STATUS``.
DatePrecision = Literal["day", "month", "year"]
CommitmentStatus = Literal["open", "done", "partly_done", "unfulfilled", "lapsed"]
# The kinds of ``core.cabinet_phases.PHASE_KINDS``.
PhaseKind = Literal[
    "formatie", "in_functie", "demissionair", "dubbel_demissionair", "missionair"
]


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


class SourceRefDTO(BaseModel):
    """Where it was read: ``rijksoverheid`` with the page and the day, or ``wikidata``."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    url: str | None = None
    read_on: str | None = None


class CabinetPhaseDTO(BaseModel):
    """A phase of a cabinet; it ends where the next begins, the last with the cabinet
    (null while it is in office)."""

    model_config = ConfigDict(extra="forbid")

    kind: PhaseKind | None = Field(
        None,
        description="Null for the stretch after elections held while the cabinet was in "
        "office, when the source gives no day of its resignation.",
    )
    from_date: str | None = None
    to_date: str | None = None
    label: str | None = Field(None, description="The source's own words.")
    source: SourceRefDTO | None = None


class CabinetSummaryDTO(BaseModel):
    """A cabinet in the list, with its counts."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., description="``rutte_iv``, ``den_uyl``.")
    name: str = Field(..., description="``kabinet-Rutte IV``.")
    from_date: str | None = Field(None, description="The day of its beëdiging.")
    to_date: str | None = Field(None, description="Null while in office.")
    from_date_precision: DatePrecision | None = Field(
        None,
        description="How precisely ``from_date`` is known: ``year`` for most cabinets "
        "before 1945, whose date is then the first of January.",
    )
    to_date_precision: DatePrecision | None = None
    previous: str | None = Field(None, description="The key of the cabinet before it.")
    prime_minister: PersonRefDTO | None = None
    parties: list[PartyRefDTO] = Field(
        default_factory=list,
        description="The parties of the bewindspersonen sworn in on its first day, the "
        "party with the most first; empty before 1945.",
    )
    factions: list[str] = Field(
        default_factory=list, description="The faction keys of its parties."
    )
    demissionary_from: str | None = Field(
        None, description="The start of its first ``demissionair`` phase."
    )
    phases: list[CabinetPhaseDTO] = Field(
        default_factory=list,
        description="Formatie, in functie, demissionair, dubbel demissionair, missionair, "
        "in order; empty before 1945 (no official source gives them).",
    )
    source: SourceRefDTO | None = Field(
        None, description="Rijksoverheid since 1945; Wikidata before (name and period)."
    )
    wikidata_id: str | None = Field(None, description="For a cabinet from Wikidata.")
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
            parties=[PartyRefDTO(**p) for p in props.get("parties") or []],
            factions=props.get("factions") or [],
            demissionary_from=props.get("demissionary_from"),
            phases=[CabinetPhaseDTO(**p) for p in props.get("phases") or []],
            source=props.get("origin"),
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
    function: str | None = Field(None, description="As Rijksoverheid names the post.")
    also_named: list[str] = Field(
        default_factory=list,
        description="The same post under another name (``minister van Algemene Zaken`` "
        "beside ``Minister-president``).",
    )
    seat: str | None = None
    portfolio: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    from_date_source: str | None = Field(
        None, description="The start the source gives; null when it gives none."
    )
    to_date_source: str | None = Field(
        None,
        description="The end the source gives; null when it gives none (the post then "
        "ends with the cabinet, or where the next holder of the seat begins).",
    )
    corrected: list[str] = Field(
        default_factory=list,
        description="Which dates the rules of a seat set, and why.",
    )
    acting: bool = Field(False, description="A stand-in (ad interim).")
    acting_basis: str | None = Field(
        None,
        description="Why: ``rijksoverheid: a.i.``, a temporary arrangement, or the rule "
        "(held another seat throughout and ended where the next holder began).",
    )
    party: PartyRefDTO | None = None
    overlaps_with: list[str] = Field(
        default_factory=list,
        description="The members who held the same seat at the same time, after the "
        "rules: a conflict in the source, not hidden.",
    )
    absent: list[str] | None = Field(
        None, description="``[from, to]`` of a ``tijdelijk afwezig`` in the post."
    )
    source: SourceRefDTO | None = None
    dossiers: int = Field(
        0,
        description="Dossiers with a paper the person signed as bewindspersoon within the "
        "cabinet's period (counted per person, the same on each of their posts).",
    )
    bills: int = Field(0, description="Of those, dossiers of track ``wetsvoorstel``.")
    open_commitments: int = Field(
        0, description="Their commitments made under this cabinet and still open."
    )


class CabinetSeatDTO(BaseModel):
    """One seat and its holders in order of start: a successor is the next post, a
    stand-in a post with ``acting``."""

    model_config = ConfigDict(extra="forbid")

    seat: str = Field(..., description="``ienw/minister``, ``viceminister-president``.")
    post: Post | None = None
    portfolio: str | None = None
    function: str | None = Field(None, description="The name of its first post.")
    posts: list[CabinetPostDTO]


class CabinetMinistryDTO(BaseModel):
    """The seats under one ministry; ``ministry`` null for a seat that names none (the
    viceminister-president, a minister without a named portfolio)."""

    model_config = ConfigDict(extra="forbid")

    ministry: MinistryKey | None = None
    name: str | None = None
    seats: list[CabinetSeatDTO]


def _post_dto(item: dict[str, Any], post: dict[str, Any]) -> CabinetPostDTO:
    return CabinetPostDTO(
        member=item["member"],
        post=post.get("post"),
        function=post.get("function"),
        also_named=post.get("also_named") or [],
        seat=post.get("seat"),
        portfolio=post.get("portfolio"),
        from_date=post.get("from_date"),
        to_date=post.get("to_date"),
        from_date_source=post.get("from_date_source"),
        to_date_source=post.get("to_date_source"),
        corrected=post.get("corrected") or [],
        acting=bool(post.get("acting")),
        acting_basis=post.get("acting_basis"),
        party=post.get("party"),
        overlaps_with=post.get("overlaps_with") or [],
        absent=post.get("absent"),
        source=post.get("source"),
        dossiers=int(item.get("dossiers") or 0),
        bills=int(item.get("bills") or 0),
        open_commitments=int(item.get("open_commitments") or 0),
    )


def _seats(posts: list[CabinetPostDTO]) -> list[CabinetSeatDTO]:
    """The posts grouped by seat: the seats in protocol order (minister-president,
    viceminister-president, minister, minister without portfolio, staatssecretaris),
    the posts in order of start."""
    by_seat: dict[str, list[CabinetPostDTO]] = {}
    for post in posts:
        by_seat.setdefault(post.seat or "", []).append(post)
    post_rank = {post: i for i, post in enumerate(POSTS)}
    seats = []
    for seat, held in by_seat.items():
        held.sort(key=lambda p: (p.from_date or "", p.member.name or ""))
        seats.append(
            CabinetSeatDTO(
                seat=seat,
                post=held[0].post,
                portfolio=held[0].portfolio,
                function=held[0].function,
                posts=held,
            )
        )
    return sorted(
        seats,
        key=lambda s: (
            post_rank.get(s.post or "", len(POSTS)),
            s.posts[0].from_date or "",
            s.seat,
        ),
    )


class CabinetDetailDTO(CabinetSummaryDTO):
    """A cabinet with its bewindspersonen: ministries in protocol order (Algemene Zaken,
    with the minister-president, first), within a ministry the seats (``_seats``). A
    person with two posts is listed under each."""

    ministries: list[CabinetMinistryDTO] = Field(default_factory=list)

    @classmethod
    def from_detail(cls, row: dict[str, Any]) -> CabinetDetailDTO:
        members = row.get("members") or []
        summary = CabinetSummaryDTO.from_row({**row, "members": len(members)})
        groups: dict[str | None, list[CabinetPostDTO]] = {}
        for item in members:
            for post in item.get("posts") or []:
                groups.setdefault(post.get("ministry"), []).append(
                    _post_dto(item, post)
                )
        ministries = [
            CabinetMinistryDTO(
                ministry=MinistryKey(key) if key else None,
                name=MINISTRY_BY_KEY[key].name if key in MINISTRY_BY_KEY else None,
                seats=_seats(posts),
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
